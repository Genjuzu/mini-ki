"""HTTP-API v1 mit fester Einbettung. Kein Modell, kein Netz, kein Zugang aus der Umgebung."""

import json
import math
import urllib.error
import urllib.request

import pytest

from mini_ki import MiniKI
from mini_ki.api import Api, dienen

FRAGE = "Wie erreiche ich Avatari?"
ANDERE = "Wie kann ich Avatari erreichen?"
ANTWORT = "Die Kontaktdaten stehen auf der Webseite von Avatari."
NEU = "Avatari erreichen Sie über die Webseite, dort stehen die Kontaktdaten."
KI_TEXT = "Die KI nennt die Webseite von Avatari als Kontakt."
E0 = [1.0, 0.0, 0.0, 0.0]
E3 = [0.0, 0.0, 0.0, 1.0]
AUDIO = b"OggS" + b"\x00mini-ki-api-test\xff" * 20
MARKER = b"MINI-KI-API-AUSBRUCH" * 8
TOKEN = "pruef-zugang-8f3c"


class FesteEinbettung:
    """Wörterbuch Text → Vektor. Breite folgt aus den Vektoren."""

    def __init__(self, vektoren: dict[str, list[float]]) -> None:
        breiten = {len(vektor) for vektor in vektoren.values()}
        if len(breiten) != 1:
            raise ValueError("Alle Vektoren brauchen dieselbe Breite.")
        self.modell = "test-modell"
        self.breite = breiten.pop()
        self._vektoren = dict(vektoren)
        self.aufrufe: list[list[str]] = []

    def vektoren(self, texte: list[str]) -> list[list[float]]:
        self.aufrufe.append(list(texte))
        fehlend = [text for text in texte if text not in self._vektoren]
        if fehlend:
            raise KeyError(fehlend[0])
        return [list(self._vektoren[text]) for text in texte]


class _Modell:
    def __init__(self, antwort) -> None:
        self.antwort = antwort
        self.aufrufe: list[tuple[str, str]] = []

    def __call__(self, system: str, nutzer: str) -> str:
        self.aufrufe.append((system, nutzer))
        if isinstance(self.antwort, BaseException):
            raise self.antwort
        if callable(self.antwort):
            return self.antwort(system, nutzer)
        return self.antwort


def richtung(kosinus: float) -> list[float]:
    rest = math.sqrt(1.0 - kosinus * kosinus)
    return [kosinus, rest, 0.0, 0.0]


def bauen(tmp_path, vektoren: dict[str, list[float]], **kwargs):
    einbettung = FesteEinbettung(vektoren)
    kern = MiniKI(tmp_path / "mini-ki.sqlite", einbettung)
    return Api(kern, **kwargs), kern, einbettung


def kopf(koepfe, name: str) -> str:
    for schluessel, wert in koepfe.items():
        if schluessel.lower() == name.lower():
            return wert
    return ""


def deuten(koepfe, roh: bytes):
    if "application/json" in kopf(koepfe, "content-type") and roh:
        return json.loads(roh.decode("utf-8"))
    return roh


def ruf(api: Api, methode: str, pfad: str, daten=None, roh: bytes | None = None, token=None):
    koepfe = {}
    inhalt = b"" if roh is None else roh
    if daten is not None:
        inhalt = json.dumps(daten, ensure_ascii=False).encode("utf-8")
        koepfe["Content-Type"] = "application/json"
    if token is not None:
        koepfe["Authorization"] = f"Bearer {token}"
    status, antwort_kopf, antwort = api.bearbeiten(methode, pfad, inhalt, koepfe)
    return status, antwort_kopf, deuten(antwort_kopf, antwort)


def holen(url: str, methode: str, daten=None, roh: bytes | None = None, token=None, typ=None):
    inhalt = roh
    if daten is not None:
        inhalt = json.dumps(daten, ensure_ascii=False).encode("utf-8")
        typ = "application/json"
    anfrage = urllib.request.Request(url, data=inhalt, method=methode)
    if typ:
        anfrage.add_header("Content-Type", typ)
    if token is not None:
        anfrage.add_header("Authorization", f"Bearer {token}")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        antwort = opener.open(anfrage, timeout=5)
    except urllib.error.HTTPError as fehler:
        antwort = fehler
    try:
        koerper = antwort.read()
        koepfe = {name: wert for name, wert in antwort.headers.items()}
        return antwort.getcode(), koepfe, deuten(koepfe, koerper)
    finally:
        antwort.close()


def test_check_fehltreffer_daumen_hoch_dann_speicher_und_runter(tmp_path):
    """Fehltreffer, Eintrag, Daumen hoch, Herkunft speicher, Daumen runter ohne Treffer."""
    vektor_b = richtung(0.85)
    assert sum(x * y for x, y in zip(E0, vektor_b)) == pytest.approx(0.85)
    api, kern, _einbettung = bauen(tmp_path, {FRAGE: E0, ANDERE: vektor_b})

    status, _, leer = ruf(api, "POST", "/v1/anfragen", {"text": FRAGE})
    assert status == 200
    assert leer == {"id": None, "herkunft": "fehltreffer", "text": ""}

    status, _, angelegt = ruf(
        api,
        "POST",
        "/v1/eintraege",
        {"frage": FRAGE, "antwort": ANTWORT},
    )
    assert status == 201
    kennung = angelegt["id"]
    assert isinstance(kennung, str) and kennung
    assert kern.laden(kennung)["bewertung"] is None

    status, _, daumen = ruf(
        api,
        "POST",
        f"/v1/anfragen/{kennung}/bewertung",
        {"bewertung": "gut"},
    )
    assert status == 200
    assert daumen == {"ok": True}

    status, _, treffer = ruf(api, "POST", "/v1/anfragen", {"text": FRAGE})
    assert status == 200
    assert treffer["id"] == kennung
    assert treffer["herkunft"] == "speicher"
    assert treffer["text"] == ANTWORT
    assert treffer["aehnlichkeit"] == 1.0

    status, _, _ = ruf(
        api,
        "POST",
        f"/v1/anfragen/{kennung}/bewertung",
        {"bewertung": "schlecht"},
    )
    assert status == 200
    status, _, danach = ruf(api, "POST", "/v1/anfragen", {"text": FRAGE})
    assert danach["herkunft"] == "fehltreffer"
    bleibt = ruf(api, "POST", "/v1/anfragen", {"text": ANDERE})[2]
    assert bleibt["herkunft"] == "speicher"
    assert bleibt["id"] == kennung
    assert bleibt["text"] == ANTWORT
    assert kern.laden(kennung)["bewertung"] == "gut"


def test_daumen_runter_auf_neue_antwort_wird_nie_geliefert(tmp_path):
    api, kern, _einbettung = bauen(tmp_path, {FRAGE: E0, ANDERE: E3})
    status, _, angelegt = ruf(
        api,
        "POST",
        "/v1/eintraege",
        {"frage": FRAGE, "antwort": ANTWORT},
    )
    kennung = angelegt["id"]
    status, _, _ = ruf(
        api,
        "POST",
        f"/v1/anfragen/{kennung}/bewertung",
        {"bewertung": "schlecht"},
    )
    assert status == 200
    assert kern.laden(kennung)["bewertung"] == "schlecht"
    assert ruf(api, "POST", "/v1/anfragen", {"text": FRAGE})[2]["herkunft"] == "fehltreffer"

    status, _, andere = ruf(
        api,
        "POST",
        "/v1/eintraege",
        {"frage": ANDERE, "antwort": "Das Büro ist im ersten Stock.", "bewertung": "gut"},
    )
    assert status == 201
    treffer = ruf(api, "POST", "/v1/anfragen", {"text": ANDERE})[2]
    assert treffer["herkunft"] == "speicher"
    assert treffer["id"] == andere["id"]


def test_audio_anhang_hin_und_zurueck(tmp_path):
    api, _kern, _einbettung = bauen(tmp_path, {FRAGE: E0})
    kennung = ruf(
        api,
        "POST",
        "/v1/eintraege",
        {"frage": FRAGE, "antwort": ANTWORT, "bewertung": "gut"},
    )[2]["id"]
    pfad = f"/v1/anfragen/{kennung}/anhaenge/audio"
    status, _, meta = ruf(api, "PUT", pfad, roh=AUDIO)
    assert status == 200
    assert meta == {"art": "audio", "groesse": len(AUDIO)}

    status, koepfe, roh = ruf(api, "GET", pfad)
    assert status == 200
    assert roh == AUDIO
    assert kopf(koepfe, "content-type") == "audio/ogg; codecs=opus"

    treffer = ruf(api, "POST", "/v1/anfragen", {"text": FRAGE})[2]
    assert treffer["anhaenge"][0]["art"] == "audio"
    assert treffer["anhaenge"][0]["medientyp"] == "audio/ogg; codecs=opus"
    assert treffer["anhaenge"][0]["groesse"] == len(AUDIO)
    assert AUDIO not in json.dumps(treffer).encode("utf-8")

    notiz = f"/v1/anfragen/{kennung}/anhaenge/notiz"
    assert ruf(api, "PUT", notiz, roh=b"hello")[0] == 200
    status, koepfe, roh = ruf(api, "GET", notiz)
    assert status == 200
    assert roh == b"hello"
    assert kopf(koepfe, "content-type") == "application/octet-stream"

    status, _, _ = ruf(
        api,
        "PUT",
        f"/v1/anfragen/{kennung}/anhaenge/..%2Fgeheim",
        roh=MARKER,
    )
    assert status == 404
    for datei in tmp_path.rglob("*"):
        if datei.is_file():
            assert MARKER not in datei.read_bytes()


def test_token_fehlt_ergibt_401_wenn_gesetzt(tmp_path):
    offen, kern, _einbettung = bauen(tmp_path, {FRAGE: E0})
    assert ruf(offen, "GET", "/v1/gesundheit")[0] == 200
    assert ruf(Api(kern, token=""), "GET", "/v1/gesundheit")[0] == 200

    api = Api(kern, token=TOKEN)
    assert TOKEN not in repr(api)
    status, koepfe, daten = ruf(api, "GET", "/v1/gesundheit")
    assert status == 401
    assert daten == {"fehler": "Der Zugang fehlt."}
    assert TOKEN not in json.dumps(daten)
    assert kopf(koepfe, "WWW-Authenticate").startswith("Bearer")
    assert TOKEN not in kopf(koepfe, "WWW-Authenticate")

    assert ruf(api, "GET", "/v1/gesundheit", token="falsch")[0] == 401
    status, _, _ = api.bearbeiten(
        "POST",
        "/v1/anfragen",
        json.dumps({"text": FRAGE}).encode("utf-8"),
        {"Authorization": "Basic abc"},
    )
    assert status == 401

    status, _, daten = ruf(api, "POST", "/v1/anfragen", {"text": FRAGE}, token=TOKEN)
    assert status == 200
    assert daten["herkunft"] == "fehltreffer"
    status, _, gesund = ruf(api, "GET", "/v1/gesundheit", token=TOKEN)
    assert status == 200
    assert gesund["einbettung_bereit"] is True


def test_gesundheit_pfad_und_json(tmp_path):
    api, _kern, _einbettung = bauen(tmp_path, {FRAGE: E0})
    status, _, daten = ruf(api, "GET", "/v1/gesundheit?quelle=test")
    assert status == 200
    assert daten == {
        "modell": "test-modell",
        "breite": 4,
        "anzahl": 0,
        "einbettung_bereit": True,
    }
    status, koepfe, daten = ruf(api, "GET", "/v1/anfragen")
    assert status == 405
    assert "POST" in kopf(koepfe, "allow")
    assert ruf(api, "GET", "/v1/fehlt")[0] == 404
    assert ruf(api, "POST", "/v1/anfragen", roh=b"{")[0] == 400
    assert ruf(api, "POST", "/v1/anfragen", {"text": "   "})[0] == 400
    status, _, daten = ruf(api, "POST", "/v1/anfragen", [])
    assert status == 400
    assert "fehler" in daten
    status, _, daten = ruf(api, "POST", "/v1/anfragen", {"text": FRAGE})
    assert daten["herkunft"] == "fehltreffer"
    assert ruf(api, "GET", "/v1/gesundheit/")[2]["anzahl"] == 0


def test_neu_schreibt_um_ohne_zu_suchen(tmp_path):
    modell = _Modell(NEU)
    api, kern, einbettung = bauen(tmp_path, {FRAGE: E0}, sprachmodell=modell)
    kennung = ruf(
        api,
        "POST",
        "/v1/eintraege",
        {"frage": FRAGE, "antwort": ANTWORT, "bewertung": "gut"},
    )[2]["id"]
    assert ruf(api, "PUT", f"/v1/anfragen/{kennung}/anhaenge/audio", roh=AUDIO)[0] == 200
    gesehen = []
    original = kern.finden

    def spy(frage):
        gesehen.append(frage)
        return original(frage)

    kern.finden = spy
    vorher = len(einbettung.aufrufe)
    status, _, daten = ruf(
        api,
        "POST",
        f"/v1/anfragen/{kennung}/neu",
        {"zusatz": "Bitte kürzer."},
    )
    assert status == 200
    assert daten == {"id": kennung, "text": NEU}
    assert gesehen == []
    assert len(einbettung.aufrufe) == vorher
    assert "Bitte kürzer." in modell.aufrufe[0][1]
    assert ruf(api, "GET", f"/v1/anfragen/{kennung}/anhaenge/audio")[0] == 404
    assert kern.laden(kennung)["antwort"] == NEU
    assert kern.laden(kennung)["bewertung"] == "gut"
    treffer = ruf(api, "POST", "/v1/anfragen", {"text": FRAGE})[2]
    assert treffer["text"] == NEU
    assert "anhaenge" not in treffer
    assert gesehen == [FRAGE]

    ohne = Api(kern)
    assert ruf(ohne, "POST", f"/v1/anfragen/{kennung}/neu", {})[0] == 503
    geheim = _Modell(RuntimeError("geheimer-hinweis"))
    mit_fehler = Api(kern, sprachmodell=geheim)
    status, _, daten = ruf(mit_fehler, "POST", f"/v1/anfragen/{kennung}/neu", {})
    assert status == 502
    assert "geheimer-hinweis" not in json.dumps(daten)
    assert kern.laden(kennung)["antwort"] == NEU


def test_neu_am_kern_wird_genutzt(tmp_path):
    class MitNeu(MiniKI):
        def neu(self, id: str, zusatz: str = "") -> str:
            self.gesehen.append((id, zusatz))
            return "Aus dem Kern."

    einbettung = FesteEinbettung({FRAGE: E0})
    kern = MitNeu(tmp_path / "mini-ki.sqlite", einbettung)
    kern.gesehen = []
    modell = _Modell(NEU)
    api = Api(kern, sprachmodell=modell)
    kennung = kern.merken(FRAGE, ANTWORT, bewertung="gut")
    status, _, daten = ruf(
        api,
        "POST",
        f"/v1/anfragen/{kennung}/neu",
        {"zusatz": "Kürzer."},
    )
    assert status == 200
    assert daten["text"] == "Aus dem Kern."
    assert kern.gesehen == [(kennung, "Kürzer.")]
    assert modell.aufrufe == []
    assert kern.laden(kennung)["antwort"] == ANTWORT


def test_text_trennen_und_loeschen(tmp_path):
    vektor_b = richtung(0.85)
    api, kern, _einbettung = bauen(tmp_path, {FRAGE: E0, ANDERE: vektor_b})
    kennung = ruf(
        api,
        "POST",
        "/v1/eintraege",
        {"frage": FRAGE, "antwort": ANTWORT, "bewertung": "gut"},
    )[2]["id"]
    assert ruf(api, "PUT", f"/v1/anfragen/{kennung}/anhaenge/audio", roh=AUDIO)[0] == 200
    neuer = "Wir haben täglich von neun bis fünf geöffnet."
    status, _, daten = ruf(
        api,
        "PUT",
        f"/v1/anfragen/{kennung}/text",
        {"text": neuer},
    )
    assert status == 200
    assert daten == {"id": kennung, "text": neuer}
    assert ruf(api, "GET", f"/v1/anfragen/{kennung}/anhaenge/audio")[0] == 404
    treffer = ruf(api, "POST", "/v1/anfragen", {"text": FRAGE})[2]
    assert treffer["text"] == neuer
    assert "anhaenge" not in treffer

    assert ruf(api, "POST", "/v1/anfragen", {"text": ANDERE})[2]["id"] == kennung
    status, _, _ = ruf(
        api,
        "POST",
        f"/v1/anfragen/{kennung}/trennen",
        {"frage": ANDERE},
    )
    assert status == 200
    assert ruf(api, "POST", "/v1/anfragen", {"text": ANDERE})[2]["herkunft"] == "fehltreffer"
    assert ruf(api, "POST", "/v1/anfragen", {"text": FRAGE})[2]["id"] == kennung
    assert ruf(api, "POST", f"/v1/anfragen/fehlt-id/trennen", {"frage": ANDERE})[0] == 404

    status, _, inhalt = ruf(api, "DELETE", f"/v1/anfragen/{kennung}")
    assert status == 204
    assert inhalt == b""
    assert kern.laden(kennung) is None
    assert ruf(api, "POST", "/v1/anfragen", {"text": FRAGE})[2]["herkunft"] == "fehltreffer"
    assert ruf(api, "DELETE", f"/v1/anfragen/{kennung}")[0] == 404


def test_ki_merkt_unbewertet_und_nur_suchen_nicht(tmp_path):
    aufrufe = []

    def ki(frage: str) -> str:
        aufrufe.append(frage)
        return KI_TEXT

    api, kern, _einbettung = bauen(tmp_path, {FRAGE: E0, ANDERE: E3}, ki=ki)
    status, _, daten = ruf(
        api,
        "POST",
        "/v1/anfragen",
        {"text": FRAGE, "nur_suchen": True},
    )
    assert daten == {"id": None, "herkunft": "fehltreffer", "text": ""}
    assert aufrufe == []

    status, _, daten = ruf(api, "POST", "/v1/anfragen", {"text": FRAGE})
    assert status == 200
    assert daten["herkunft"] == "ki"
    assert daten["text"] == KI_TEXT
    assert kern.laden(daten["id"])["bewertung"] is None
    assert aufrufe == [FRAGE]

    assert ruf(
        api,
        "POST",
        f"/v1/anfragen/{daten['id']}/bewertung",
        {"bewertung": "gut"},
    )[0] == 200
    treffer = ruf(api, "POST", "/v1/anfragen", {"text": FRAGE})[2]
    assert treffer["herkunft"] == "speicher"
    assert treffer["text"] == KI_TEXT
    assert aufrufe == [FRAGE]

    def kaputt(frage: str) -> str:
        raise RuntimeError("geheimer-hinweis")

    api_fehler = Api(kern, ki=kaputt)
    status, _, daten = ruf(api_fehler, "POST", "/v1/anfragen", {"text": ANDERE})
    assert status == 200
    assert daten["herkunft"] == "fehltreffer"
    assert "geheimer-hinweis" not in json.dumps(daten)

    def mit_mail(frage: str) -> str:
        return "Bitte an ada@example.com schreiben."

    status, _, daten = ruf(Api(kern, ki=mit_mail), "POST", "/v1/anfragen", {"text": ANDERE})
    assert daten["herkunft"] == "fehltreffer"
    assert "ada@example.com" not in json.dumps(daten)
    assert ruf(api, "GET", "/v1/gesundheit")[2]["anzahl"] == 1


def test_nach_speicher_ablehnung_darf_die_ki_neu_antworten(tmp_path):
    vektor_b = richtung(0.85)

    def ki(frage: str) -> str:
        assert frage == ANDERE
        return KI_TEXT

    api, kern, _einbettung = bauen(
        tmp_path,
        {FRAGE: E0, ANDERE: vektor_b},
        ki=ki,
    )
    kennung = ruf(
        api,
        "POST",
        "/v1/eintraege",
        {"frage": FRAGE, "antwort": ANTWORT, "bewertung": "gut"},
    )[2]["id"]
    assert ruf(api, "POST", "/v1/anfragen", {"text": ANDERE})[2]["id"] == kennung
    assert ruf(
        api,
        "POST",
        f"/v1/anfragen/{kennung}/bewertung",
        {"bewertung": "schlecht"},
    )[0] == 200
    neu = ruf(api, "POST", "/v1/anfragen", {"text": ANDERE})[2]
    assert neu["herkunft"] == "ki"
    assert neu["text"] == KI_TEXT
    assert neu["id"] != kennung
    bleibt = ruf(api, "POST", "/v1/anfragen", {"text": FRAGE})[2]
    assert bleibt["herkunft"] == "speicher"
    assert bleibt["id"] == kennung
    assert bleibt["text"] == ANTWORT
    assert kern.laden(kennung)["bewertung"] == "gut"
    assert kern.laden(neu["id"])["bewertung"] is None


def test_verweis_wird_vor_der_suche_aufgeloest(tmp_path):
    modell = _Modell(FRAGE)
    api, _kern, _einbettung = bauen(tmp_path, {FRAGE: E0}, sprachmodell=modell)
    kennung = ruf(
        api,
        "POST",
        "/v1/eintraege",
        {"frage": FRAGE, "antwort": ANTWORT, "bewertung": "gut"},
    )[2]["id"]
    treffer = ruf(api, "POST", "/v1/anfragen", {"text": FRAGE})[2]
    assert treffer["id"] == kennung
    assert modell.aufrufe == []

    status, _, daten = ruf(
        api,
        "POST",
        "/v1/anfragen",
        {"text": "Ja, dazu", "verlauf": "Gast: " + FRAGE + "\nAntwort: " + ANTWORT},
    )
    assert status == 200
    assert daten["herkunft"] == "speicher"
    assert daten["id"] == kennung
    assert len(modell.aufrufe) == 1
    assert "Ja, dazu" in modell.aufrufe[0][1]
    assert ruf(api, "POST", "/v1/anfragen", {"text": FRAGE, "verlauf": 3})[0] == 400


def test_ablehnen_wird_gerufen_wenn_vorhanden(tmp_path):
    class Kern:
        def __init__(self) -> None:
            self.ablehnen_aufrufe = []
            self.sonst = []

        def laden(self, id: str):
            if id == "abc":
                return {
                    "frage": "Wie spät ist es?",
                    "antwort": "Drei Uhr.",
                    "bewertung": "gut",
                }
            if id == "neu-id":
                return {
                    "frage": "Wo ist das Büro?",
                    "antwort": "Im ersten Stock.",
                    "bewertung": None,
                }
            return None

        def ablehnen(self, id: str, frage: str, herkunft: str) -> bool:
            self.ablehnen_aufrufe.append((id, frage, herkunft))
            return self.ok

        def bewerten(self, *args):
            self.sonst.append(("bewerten", args))
            return True

        def trennen(self, *args):
            self.sonst.append(("trennen", args))
            return True

        ok = True

    kern = Kern()
    api = Api(kern)
    status, _, daten = ruf(
        api,
        "POST",
        "/v1/anfragen/abc/bewertung",
        {
            "bewertung": "schlecht",
            "frage": "Wie spät ist es heute?",
            "herkunft": "speicher",
        },
    )
    assert status == 200
    assert daten == {"ok": True}
    status, _, _ = ruf(
        api,
        "POST",
        "/v1/anfragen/neu-id/bewertung",
        {"bewertung": "schlecht"},
    )
    assert status == 200
    assert kern.ablehnen_aufrufe == [
        ("abc", "Wie spät ist es heute?", "speicher"),
        ("neu-id", "Wo ist das Büro?", "neu"),
    ]
    assert kern.sonst == []
    assert ruf(api, "POST", "/v1/anfragen/fehlt/bewertung", {"bewertung": "schlecht"})[0] == 404
    kern.ok = False
    assert ruf(
        api,
        "POST",
        "/v1/anfragen/abc/bewertung",
        {"bewertung": "schlecht", "herkunft": "speicher"},
    )[0] == 400
    assert "trennen" not in [name for name, _args in kern.sonst]


def test_sperre_kommt_nicht_in_den_speicher(tmp_path):
    aufrufe = []

    def ki(frage: str) -> str:
        aufrufe.append(frage)
        return ANTWORT

    api, _kern, einbettung = bauen(tmp_path, {FRAGE: E0}, ki=ki)
    status, _, daten = ruf(api, "POST", "/v1/anfragen", {"text": "ada@example.com"})
    assert status == 200
    assert daten["herkunft"] == "fehltreffer"
    assert "ada@example.com" not in json.dumps(daten)
    assert aufrufe == []
    assert einbettung.aufrufe == []
    status, _, daten = ruf(
        api,
        "POST",
        "/v1/eintraege",
        {"frage": FRAGE, "antwort": "Bitte +49 151 23456789 anrufen."},
    )
    assert status == 400
    assert "23456789" not in json.dumps(daten)
    assert ruf(api, "GET", "/v1/gesundheit")[2]["anzahl"] == 0


def test_integration_ueber_http_auf_loopback(tmp_path):
    """Dieselbe Strecke über einen echten Dienst, nur auf 127.0.0.1."""
    vektor_b = richtung(0.85)
    api, kern, _einbettung = bauen(tmp_path, {FRAGE: E0, ANDERE: vektor_b}, token=TOKEN)
    with dienen(api) as dienst:
        assert dienst.host == "127.0.0.1"
        assert dienst.basis.startswith("http://127.0.0.1:")
        basis = dienst.basis

        status, _, roh = holen(basis + "/v1/anfragen", "POST", {"text": FRAGE})
        assert status == 401
        assert TOKEN.encode("utf-8") not in (
            roh if isinstance(roh, bytes) else json.dumps(roh).encode("utf-8")
        )

        status, _, daten = holen(
            basis + "/v1/anfragen",
            "POST",
            {"text": FRAGE},
            token=TOKEN,
        )
        assert status == 200
        assert daten == {"id": None, "herkunft": "fehltreffer", "text": ""}

        status, _, angelegt = holen(
            basis + "/v1/eintraege",
            "POST",
            {"frage": FRAGE, "antwort": ANTWORT},
            token=TOKEN,
        )
        assert status == 201
        kennung = angelegt["id"]

        assert holen(
            f"{basis}/v1/anfragen/{kennung}/bewertung",
            "POST",
            {"bewertung": "gut"},
            token=TOKEN,
        )[0] == 200
        treffer = holen(
            basis + "/v1/anfragen",
            "POST",
            {"text": FRAGE},
            token=TOKEN,
        )[2]
        assert treffer["herkunft"] == "speicher"
        assert treffer["id"] == kennung
        assert treffer["text"] == ANTWORT

        audio_pfad = f"{basis}/v1/anfragen/{kennung}/anhaenge/audio"
        assert holen(audio_pfad, "PUT", roh=AUDIO, token=TOKEN)[0] == 200
        status, koepfe, roh = holen(audio_pfad, "GET", token=TOKEN)
        assert status == 200
        assert roh == AUDIO
        assert kopf(koepfe, "content-type") == "audio/ogg; codecs=opus"

        assert holen(
            f"{basis}/v1/anfragen/{kennung}/bewertung",
            "POST",
            {"bewertung": "schlecht"},
            token=TOKEN,
        )[0] == 200
        assert holen(
            basis + "/v1/anfragen",
            "POST",
            {"text": FRAGE},
            token=TOKEN,
        )[2]["herkunft"] == "fehltreffer"
        bleibt = holen(
            basis + "/v1/anfragen",
            "POST",
            {"text": ANDERE},
            token=TOKEN,
        )[2]
        assert bleibt["herkunft"] == "speicher"
        assert bleibt["id"] == kennung
        assert bleibt["anhaenge"][0]["groesse"] == len(AUDIO)
        assert kern.laden(kennung)["bewertung"] == "gut"

        gesund = holen(basis + "/v1/gesundheit", "GET", token=TOKEN)[2]
        assert gesund == {
            "modell": "test-modell",
            "breite": 4,
            "anzahl": 1,
            "einbettung_bereit": True,
        }
        assert holen(basis + "/v1/gesundheit", "GET")[0] == 401
