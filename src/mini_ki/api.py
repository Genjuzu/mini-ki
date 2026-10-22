"""Dünne HTTP-API v1 über einem Kern.

Voreingestellt hört der Dienst nur auf 127.0.0.1. Ein optionaler Zugang
steht im Kopf `Authorization: Bearer`. Ohne gesetzten Zugang ist kein
Schlüssel nötig. Mandant ist `standard`, bis die Trennung aus #15 da ist.

Daumen runter folgt `entscheidungen/daumen-runter.md`. Ist `ablehnen` am
Kern vorhanden (#17), wird es gerufen. Sonst wird eine neue Antwort als
`schlecht` gespeichert, ein Speicher-Treffer nur für diese Anfrage gesperrt.

`GET` und `PUT /v1/einstellungen` lesen und schreiben die Einbettung.
Der Schlüssel wird nur gespeichert und nie zurückgegeben.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
import traceback
from collections.abc import Callable, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import NoReturn
from urllib.parse import unquote

from .einstellungen import Einstellungen, EinstellungenFehler, aus_kern
from .sperre import gesperrt
from .sprachmodell import Sprachmodell
from .sprachmodell import SprachmodellFehler
from .sprachmodell import neu as antwort_neu
from .sprachmodell import verweis_umschreiben

_MAX_JSON = 1_000_000
_MAX_ANHANG = 32 * 1024 * 1024
_AUDIO = "audio/ogg; codecs=opus"
_DATEI = "application/octet-stream"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_ART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_BEARER = re.compile(r"^Bearer\s+(\S+)\s*$", re.IGNORECASE)
_HERKUNFT = {"speicher", "ki", "neu", "fehltreffer"}

Ki = Callable[[str], str]


class _Abbruch(Exception):
    def __init__(self, antwort: tuple[int, dict[str, str], bytes]) -> None:
        self.antwort = antwort


def _bytes(daten: dict) -> bytes:
    return json.dumps(daten, ensure_ascii=False).encode("utf-8")


def _kopfzeilen(inhalt: bytes, typ: str, extra: Mapping[str, str] | None = None) -> dict[str, str]:
    koepfe = {
        "Content-Type": typ,
        "Content-Length": str(len(inhalt)),
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
    }
    if extra:
        koepfe.update(extra)
    return koepfe


def _json(
    status: int,
    daten: dict,
    extra: Mapping[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    inhalt = _bytes(daten)
    return status, _kopfzeilen(inhalt, "application/json; charset=utf-8", extra), inhalt


def _gleich(links: str, rechts: str) -> bool:
    return hmac.compare_digest(
        hashlib.sha256(links.encode("utf-8")).digest(),
        hashlib.sha256(rechts.encode("utf-8")).digest(),
    )


def _segment(roh: str, muster: re.Pattern[str]) -> str | None:
    text = unquote(roh)
    if muster.fullmatch(text):
        return text
    return None


def _satz(wert: object) -> str | None:
    """Text oder None, wenn der Wert kein Text ist."""
    if not isinstance(wert, str):
        return None
    return wert.strip()


class Api:
    """HTTP-Schicht. Der Kern, das Sprachmodell und die KI kommen von außen."""

    def __init__(
        self,
        kern: object,
        *,
        token: str | None = None,
        sprachmodell: Sprachmodell | None = None,
        ki: Ki | None = None,
        einstellungen: Einstellungen | None = None,
        einbettung_fabrik=None,
    ) -> None:
        if sprachmodell is not None and not callable(sprachmodell):
            raise TypeError("Das Sprachmodell muss aufrufbar sein.")
        if ki is not None and not callable(ki):
            raise TypeError("Die KI muss aufrufbar sein.")
        self._kern = kern
        self._token = _zugang(token)
        self._sprachmodell = sprachmodell
        self._ki = ki
        self._einstellungen = einstellungen
        self._einbettung_fabrik = einbettung_fabrik
        self._lock = threading.Lock()
        self._herkunft: dict[str, str] = {}
        self._fragen: dict[str, str] = {}

    def __repr__(self) -> str:
        return f"Api(mandant='standard', zugang={self._token is not None})"

    def bearbeiten(
        self,
        methode: str,
        pfad: str,
        koerper: bytes = b"",
        koepfe: Mapping[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        """Eine Anfrage. Liefert Status, Kopfreihen und Inhalt."""
        try:
            if not isinstance(koerper, (bytes, bytearray)):
                return _json(400, {"fehler": "Der Inhalt ist ungültig."})
            roh = bytes(koerper)
            if not self._zugang_ok(koepfe or {}):
                return _json(
                    401,
                    {"fehler": "Der Zugang fehlt."},
                    {"WWW-Authenticate": 'Bearer realm="mini-ki"'},
                )
            weg = _pfad(pfad)
            if weg is None:
                return _json(400, {"fehler": "Der Pfad ist ungültig."})
            return self._route(methode.upper(), weg, roh)
        except _Abbruch as abbruch:
            return abbruch.antwort
        except Exception:
            traceback.print_exc()
            return _json(500, {"fehler": "Interner Fehler."})

    def _zugang_ok(self, koepfe: Mapping[str, str]) -> bool:
        if self._token is None:
            return True
        roh = ""
        for name, wert in koepfe.items():
            if name.lower() == "authorization" and isinstance(wert, str):
                roh = wert
                break
        treffer = _BEARER.fullmatch(roh.strip())
        gegeben = treffer.group(1) if treffer else ""
        return _gleich(gegeben, self._token)

    def _route(
        self,
        methode: str,
        pfad: str,
        koerper: bytes,
    ) -> tuple[int, dict[str, str], bytes]:
        if pfad == "/v1/anfragen":
            self._nur(methode, "POST")
            return self._anfragen(self._objekt(koerper))
        if pfad == "/v1/eintraege":
            self._nur(methode, "POST")
            return self._eintraege(self._objekt(koerper))
        if pfad == "/v1/gesundheit":
            self._nur(methode, "GET")
            return self._gesundheit()
        if pfad == "/v1/einstellungen":
            if methode == "GET":
                return self._einstellungen_lesen()
            if methode == "PUT":
                return self._einstellungen_schreiben(self._objekt(koerper))
            self._nur(methode, "GET, PUT")
        if pfad.startswith("/v1/anfragen/"):
            return self._unter(methode, pfad[len("/v1/anfragen/") :], koerper)
        self._fehler(404, "Nicht gefunden.")

    def _unter(
        self,
        methode: str,
        rest: str,
        koerper: bytes,
    ) -> tuple[int, dict[str, str], bytes]:
        teile = rest.split("/")
        eintrag_id = _segment(teile[0], _ID) if teile and teile[0] else None
        if not eintrag_id:
            self._fehler(404, "Nicht gefunden.")
        if len(teile) == 1:
            self._nur(methode, "DELETE")
            return self._loeschen(eintrag_id)
        aktion = teile[1]
        if aktion == "bewertung" and len(teile) == 2:
            self._nur(methode, "POST")
            return self._bewerten(eintrag_id, self._objekt(koerper))
        if aktion == "neu" and len(teile) == 2:
            self._nur(methode, "POST")
            daten = self._objekt(koerper, leer={})
            return self._neu(eintrag_id, daten)
        if aktion == "text" and len(teile) == 2:
            self._nur(methode, "PUT")
            return self._text(eintrag_id, self._objekt(koerper))
        if aktion == "trennen" and len(teile) == 2:
            self._nur(methode, "POST")
            return self._trennen(eintrag_id, self._objekt(koerper))
        if aktion == "anhaenge" and len(teile) == 3:
            art = _segment(teile[2], _ART)
            if art is None:
                self._fehler(404, "Nicht gefunden.")
            if methode == "GET":
                return self._anhang_lesen(eintrag_id, art)
            if methode == "PUT":
                if len(koerper) > _MAX_ANHANG:
                    self._fehler(413, "Der Inhalt ist zu groß.")
                return self._anhang_setzen(eintrag_id, art, koerper)
            self._nur(methode, "GET, PUT")
        self._fehler(404, "Nicht gefunden.")

    def _anfragen(self, daten: dict) -> tuple[int, dict[str, str], bytes]:
        text = _satz(daten.get("text"))
        if text is None or text == "":
            self._fehler(400, "Der Text fehlt.")
        if "verlauf" in daten and daten["verlauf"] is not None:
            if not isinstance(daten["verlauf"], str):
                self._fehler(400, "Der Verlauf muss Text sein.")
            verlauf = daten["verlauf"]
        else:
            verlauf = ""
        if daten.get("nur_suchen") not in (None, False, True):
            self._fehler(400, "nur_suchen muss wahr oder falsch sein.")
        nur_suchen = daten.get("nur_suchen") is True
        if gesperrt(text):
            return _json(200, {"id": None, "herkunft": "fehltreffer", "text": ""})
        frage = text
        if self._sprachmodell is not None and not gesperrt(verlauf):
            frage = verweis_umschreiben(self._sprachmodell, text, verlauf)
        if not frage or gesperrt(frage):
            return _json(200, {"id": None, "herkunft": "fehltreffer", "text": ""})
        treffer = self._kern.finden(frage)
        if treffer:
            self._merke(treffer["id"], "speicher", frage)
            koerper = {
                "id": treffer["id"],
                "herkunft": "speicher",
                "text": treffer["antwort"],
                "aehnlichkeit": treffer["aehnlichkeit"],
            }
            if treffer.get("anhaenge"):
                koerper["anhaenge"] = treffer["anhaenge"]
            return _json(200, koerper)
        if not nur_suchen and self._ki is not None:
            antwort = self._ki_holen(frage)
            if antwort:
                kennung = self._kern.merken(frage, antwort)
                if kennung:
                    self._merke(kennung, "ki", frage)
                    return _json(
                        200,
                        {"id": kennung, "herkunft": "ki", "text": antwort},
                    )
        return _json(200, {"id": None, "herkunft": "fehltreffer", "text": ""})

    def _ki_holen(self, frage: str) -> str:
        if self._ki is None:
            return ""
        try:
            roh = self._ki(frage)
        except Exception:
            return ""
        if not isinstance(roh, str):
            return ""
        text = roh.strip()
        if not text or gesperrt(text):
            return ""
        return text

    def _eintraege(self, daten: dict) -> tuple[int, dict[str, str], bytes]:
        frage = _satz(daten.get("frage"))
        antwort = _satz(daten.get("antwort"))
        if not frage or not antwort:
            self._fehler(400, "Frage und Antwort fehlen.")
        bewertung = daten.get("bewertung", None)
        if bewertung is not None:
            bewertung = _satz(bewertung)
            if bewertung not in ("gut", "schlecht"):
                self._fehler(400, "Die Bewertung muss gut oder schlecht sein.")
        kennung = self._kern.merken(frage, antwort, bewertung=bewertung)
        if not kennung:
            self._fehler(400, "Der Eintrag wurde nicht gespeichert.")
        self._merke(kennung, "neu", frage)
        return _json(201, {"id": kennung})

    def _bewerten(
        self,
        eintrag_id: str,
        daten: dict,
    ) -> tuple[int, dict[str, str], bytes]:
        eintrag = self._kern.laden(eintrag_id)
        if eintrag is None:
            self._fehler(404, "Nicht gefunden.")
        bewertung = _satz(daten.get("bewertung"))
        if bewertung not in ("gut", "schlecht"):
            self._fehler(400, "Die Bewertung muss gut oder schlecht sein.")
        if bewertung == "gut":
            if not self._kern.bewerten(eintrag_id, "gut"):
                self._fehler(404, "Nicht gefunden.")
            return _json(200, {"ok": True})
        herkunft = self._herkunft_fuer(eintrag_id, eintrag, daten.get("herkunft"))
        frage = self._frage_fuer(eintrag_id, eintrag, daten.get("frage"))
        if not self._daumen_runter(eintrag_id, frage, herkunft):
            self._fehler(400, "Die Bewertung wurde nicht gespeichert.")
        return _json(200, {"ok": True})

    def _daumen_runter(self, eintrag_id: str, frage: str, herkunft: str) -> bool:
        methode = getattr(self._kern, "ablehnen", None)
        if callable(methode):
            return bool(methode(eintrag_id, frage, herkunft))
        if herkunft == "speicher":
            if not frage:
                return False
            return bool(self._kern.trennen(frage, eintrag_id))
        return bool(self._kern.bewerten(eintrag_id, "schlecht"))

    def _neu(
        self,
        eintrag_id: str,
        daten: dict,
    ) -> tuple[int, dict[str, str], bytes]:
        eintrag = self._kern.laden(eintrag_id)
        if eintrag is None:
            self._fehler(404, "Nicht gefunden.")
        if "zusatz" in daten and daten["zusatz"] is not None:
            if not isinstance(daten["zusatz"], str):
                self._fehler(400, "Der Zusatz muss Text sein.")
            zusatz = daten["zusatz"]
        else:
            zusatz = ""
        methode = getattr(self._kern, "neu", None)
        if callable(methode):
            try:
                text = methode(eintrag_id, zusatz)
            except (SprachmodellFehler, ValueError):
                self._fehler(502, "Das Sprachmodell hat keine neue Antwort geliefert.")
            if not isinstance(text, str) or not text.strip():
                self._fehler(502, "Das Sprachmodell hat keine neue Antwort geliefert.")
            return _json(200, {"id": eintrag_id, "text": text.strip()})
        if self._sprachmodell is None:
            self._fehler(503, "Kein Sprachmodell.")
        try:
            text = antwort_neu(
                self._sprachmodell,
                eintrag["frage"],
                eintrag["antwort"],
                zusatz,
            )
        except SprachmodellFehler:
            self._fehler(502, "Das Sprachmodell hat keine neue Antwort geliefert.")
        if not self._kern.umschreiben(eintrag_id, text):
            self._fehler(409, "Der Text bleibt unverändert.")
        return _json(200, {"id": eintrag_id, "text": text})

    def _text(
        self,
        eintrag_id: str,
        daten: dict,
    ) -> tuple[int, dict[str, str], bytes]:
        if self._kern.laden(eintrag_id) is None:
            self._fehler(404, "Nicht gefunden.")
        text = _satz(daten.get("text"))
        if not text:
            self._fehler(400, "Der Text fehlt.")
        if not self._kern.umschreiben(eintrag_id, text):
            self._fehler(400, "Der Text wurde nicht gespeichert.")
        return _json(200, {"id": eintrag_id, "text": text})

    def _trennen(
        self,
        eintrag_id: str,
        daten: dict,
    ) -> tuple[int, dict[str, str], bytes]:
        if self._kern.laden(eintrag_id) is None:
            self._fehler(404, "Nicht gefunden.")
        frage = _satz(daten.get("frage"))
        if not frage:
            self._fehler(400, "Die Frage fehlt.")
        if not self._kern.trennen(frage, eintrag_id):
            self._fehler(400, "Die Frage wurde nicht getrennt.")
        return _json(200, {"ok": True})

    def _loeschen(self, eintrag_id: str) -> tuple[int, dict[str, str], bytes]:
        if not self._kern.vergessen(eintrag_id):
            self._fehler(404, "Nicht gefunden.")
        with self._lock:
            self._herkunft.pop(eintrag_id, None)
            self._fragen.pop(eintrag_id, None)
        return 204, {"Content-Length": "0"}, b""

    def _anhang_setzen(
        self,
        eintrag_id: str,
        art: str,
        daten: bytes,
    ) -> tuple[int, dict[str, str], bytes]:
        if self._kern.laden(eintrag_id) is None:
            self._fehler(404, "Nicht gefunden.")
        if not self._kern.anhang_setzen(eintrag_id, art, daten):
            self._fehler(400, "Der Anhang wurde nicht gespeichert.")
        return _json(200, {"art": art, "groesse": len(daten)})

    def _anhang_lesen(
        self,
        eintrag_id: str,
        art: str,
    ) -> tuple[int, dict[str, str], bytes]:
        if self._kern.laden(eintrag_id) is None:
            self._fehler(404, "Nicht gefunden.")
        daten = self._kern.anhang_lesen(eintrag_id, art)
        if daten is None:
            self._fehler(404, "Nicht gefunden.")
        typ = _AUDIO if art == "audio" else _DATEI
        return 200, _kopfzeilen(daten, typ), daten

    def _konfiguration(self) -> Einstellungen:
        if self._einstellungen is None:
            self._einstellungen = aus_kern(self._kern, self._einbettung_fabrik)
        return self._einstellungen

    def _einstellungen_lesen(self) -> tuple[int, dict[str, str], bytes]:
        try:
            sicht = self._konfiguration().lesen(self._kern)
        except EinstellungenFehler as fehler:
            self._fehler(fehler.status, fehler.meldung)
        return _json(200, sicht)

    def _einstellungen_schreiben(self, daten: dict) -> tuple[int, dict[str, str], bytes]:
        try:
            sicht = self._konfiguration().schreiben(daten, self._kern)
        except EinstellungenFehler as fehler:
            self._fehler(fehler.status, fehler.meldung)
        return _json(200, sicht)

    def _gesundheit(self) -> tuple[int, dict[str, str], bytes]:
        einbettung = getattr(self._kern, "_einbettung", None)
        speicher = getattr(self._kern, "_speicher", None)
        modell = getattr(einbettung, "modell", None)
        breite = getattr(einbettung, "breite", None)
        if not isinstance(modell, str) or modell == "":
            modell = getattr(speicher, "modell", "") or ""
        if isinstance(breite, bool) or not isinstance(breite, int) or breite < 1:
            breite = getattr(speicher, "breite", 0)
            if isinstance(breite, bool) or not isinstance(breite, int):
                breite = 0
        bereit = (
            einbettung is not None
            and isinstance(modell, str)
            and modell != ""
            and isinstance(breite, int)
            and not isinstance(breite, bool)
            and breite > 0
        )
        return _json(
            200,
            {
                "modell": modell,
                "breite": breite,
                "anzahl": self._anzahl(speicher),
                "einbettung_bereit": bereit,
            },
        )

    def _anzahl(self, speicher: object) -> int:
        laufen = getattr(speicher, "_laufen", None)
        if not callable(laufen):
            return 0
        zahl = laufen(
            lambda conn: conn.execute("SELECT COUNT(*) FROM eintrag").fetchone()[0]
        )
        return int(zahl)

    def _merke(self, eintrag_id: str, herkunft: str, frage: str) -> None:
        with self._lock:
            self._herkunft[eintrag_id] = herkunft
            if frage:
                self._fragen[eintrag_id] = frage

    def _herkunft_fuer(self, eintrag_id: str, eintrag: dict, angegeben: object) -> str:
        if angegeben is not None:
            text = _satz(angegeben)
            if text not in _HERKUNFT:
                self._fehler(400, "Die Herkunft ist unbekannt.")
            return text
        with self._lock:
            gemerkt = self._herkunft.get(eintrag_id)
        if gemerkt in _HERKUNFT:
            return gemerkt
        if eintrag.get("bewertung") == "gut":
            return "speicher"
        return "neu"

    def _frage_fuer(self, eintrag_id: str, eintrag: dict, angegeben: object) -> str:
        if angegeben is not None:
            if not isinstance(angegeben, str):
                self._fehler(400, "Die Frage muss Text sein.")
            text = angegeben.strip()
            if text:
                return text
        with self._lock:
            gemerkt = self._fragen.get(eintrag_id)
        if gemerkt:
            return gemerkt
        return eintrag.get("frage") or ""

    def _objekt(self, koerper: bytes, *, leer: dict | None = None) -> dict:
        if not koerper:
            if leer is not None:
                return dict(leer)
            self._fehler(400, "Der Inhalt fehlt.")
        if len(koerper) > _MAX_JSON:
            self._fehler(413, "Der Inhalt ist zu groß.")
        try:
            daten = json.loads(koerper.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._fehler(400, "Der Inhalt ist kein JSON.")
        if not isinstance(daten, dict):
            self._fehler(400, "Der Inhalt muss ein Objekt sein.")
        return daten

    def _nur(self, methode: str, erlaubt: str) -> None:
        if methode not in {teil.strip() for teil in erlaubt.split(",")}:
            self._fehler(
                405,
                "Diese Methode ist hier nicht erlaubt.",
                Allow=erlaubt,
            )

    def _fehler(self, status: int, text: str, **extra: str) -> NoReturn:
        raise _Abbruch(_json(status, {"fehler": text}, extra or None))


def _zugang(token: str | None) -> str | None:
    if token is None or token == "":
        return None
    if not isinstance(token, str):
        raise TypeError("Der Zugang muss Text sein.")
    try:
        roh = token.encode("latin-1")
    except UnicodeEncodeError:
        raise ValueError("Der Zugang ist als HTTP-Kopf unzulässig.") from None
    if any(byte < 32 or byte == 127 for byte in roh):
        raise ValueError("Der Zugang ist als HTTP-Kopf unzulässig.")
    return token


def _pfad(pfad: str) -> str | None:
    if not isinstance(pfad, str) or not pfad.startswith("/"):
        return None
    ohne = pfad.split("?", 1)[0].split("#", 1)[0]
    if not ohne.startswith("/"):
        return None
    if len(ohne) > 1:
        ohne = ohne.rstrip("/")
    if not ohne.startswith("/") or "\\" in ohne or "\x00" in ohne:
        return None
    return ohne


class _Server(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address, handler) -> None:
        super().__init__(server_address, handler)
        self.bereit = threading.Event()

    def service_actions(self) -> None:
        self.bereit.set()


def _handler(api: Api) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._ausliefern("GET")

        def do_POST(self) -> None:
            self._ausliefern("POST")

        def do_PUT(self) -> None:
            self._ausliefern("PUT")

        def do_DELETE(self) -> None:
            self._ausliefern("DELETE")

        def _ausliefern(self, methode: str) -> None:
            try:
                laenge = int(self.headers.get("Content-Length") or "0")
            except (TypeError, ValueError):
                laenge = -1
            if laenge < 0 or laenge > _MAX_ANHANG:
                status, koepfe, inhalt = _json(413, {"fehler": "Der Inhalt ist zu groß."})
            else:
                roh = self.rfile.read(laenge) if laenge else b""
                status, koepfe, inhalt = api.bearbeiten(
                    methode,
                    self.path,
                    roh,
                    {name: wert for name, wert in self.headers.items()},
                )
            self.send_response(status)
            for name, wert in koepfe.items():
                self.send_header(name, wert)
            self.end_headers()
            if inhalt:
                self.wfile.write(inhalt)

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


class Dienst:
    """Laufender Dienst. Voreingestellt nur auf 127.0.0.1."""

    def __init__(self, api: Api, host: str = "127.0.0.1", port: int = 0) -> None:
        if not isinstance(host, str) or host.strip() == "":
            raise ValueError("Der Rechner fehlt.")
        if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
            raise ValueError("Der Port ist ungültig.")
        self._httpd = _Server((host, port), _handler(api))
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            kwargs={"poll_interval": 0.05},
            daemon=True,
        )

    def __enter__(self) -> Dienst:
        self._thread.start()
        if not self._httpd.bereit.wait(2):
            self._httpd.server_close()
            raise RuntimeError("Der Dienst ist nicht bereit.")
        return self

    def __exit__(self, *args: object) -> bool:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=2)
        return False

    @property
    def basis(self) -> str:
        host, port = self._httpd.server_address
        return f"http://{host}:{port}"

    @property
    def host(self) -> str:
        return self._httpd.server_address[0]


def dienen(api: Api, *, host: str = "127.0.0.1", port: int = 0) -> Dienst:
    """Startet die API. Ohne `host` nur auf 127.0.0.1. Port 0 wählt frei."""
    return Dienst(api, host, port)


def laufen(api: Api, *, host: str = "127.0.0.1", port: int = 0) -> None:
    """Bedient Anfragen im Vordergrund, bis der Prozess endet."""
    dienst = Dienst(api, host, port)
    try:
        dienst._httpd.serve_forever(poll_interval=0.5)
    finally:
        dienst._httpd.server_close()


__all__ = ["Api", "Dienst", "Ki", "dienen", "laufen"]
