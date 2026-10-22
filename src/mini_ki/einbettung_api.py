"""Einbettung über einen OpenAI-kompatiblen Endpunkt `/embeddings`.

Adresse, Modell, Schlüssel und Breite kommen von außen. Der Schlüssel steht
nur im Kopf `Authorization` und weder in Fehlermeldungen noch in einem Log.
Nur die Standardbibliothek, kein extra Paket.
"""

from __future__ import annotations

import http.client
import json
import math
from urllib.parse import quote, urlsplit, urlunsplit

_REDAKTION = "[redigiert]"


class EinbettungApiFehler(RuntimeError):
    """Der Endpunkt war nicht erreichbar oder hat einen Fehler gemeldet."""


def _endpunkt(adresse: str) -> str:
    if not isinstance(adresse, str):
        raise ValueError("Die Adresse fehlt.")
    text = adresse.strip()
    if not text:
        raise ValueError("Die Adresse fehlt.")
    teile = urlsplit(text)
    if teile.scheme not in {"http", "https"} or not teile.hostname:
        raise ValueError("Die Adresse muss eine http- oder https-Adresse sein.")
    pfad = teile.path.rstrip("/")
    if not pfad.endswith("/embeddings"):
        pfad = f"{pfad}/embeddings"
    return urlunsplit((teile.scheme, teile.netloc, pfad, teile.query, ""))


def _schluessel_pruefen(schluessel: object) -> str:
    if not isinstance(schluessel, str) or schluessel == "":
        raise ValueError("Der Schlüssel fehlt.")
    try:
        roh = schluessel.encode("latin-1")
    except UnicodeEncodeError:
        raise ValueError("Der Schlüssel ist als HTTP-Kopf unzulässig.") from None
    if any(byte < 32 or byte == 127 for byte in roh):
        raise ValueError("Der Schlüssel ist als HTTP-Kopf unzulässig.")
    return schluessel


class ApiEinbettung:
    """OpenAI-kompatible Einbettung, zum Beispiel OpenRouter.

    `adresse` ist die Basis (`https://openrouter.ai/api/v1`) oder schon
    der Endpunkt (`…/embeddings`). `breite` wird an der Antwort geprüft
    und nicht mitgeschickt.
    """

    def __init__(
        self,
        adresse: str,
        modell: str,
        schluessel: str,
        breite: int,
        *,
        wartezeit: float = 30.0,
    ) -> None:
        self._schluessel = _schluessel_pruefen(schluessel)
        try:
            self._adresse = _endpunkt(adresse)
        except ValueError as fehler:
            raise ValueError(self._schwaerzen(str(fehler))) from None
        if not isinstance(modell, str) or modell.strip() == "":
            raise ValueError("Der Modellname fehlt.")
        if isinstance(breite, bool) or not isinstance(breite, int) or breite < 1:
            raise ValueError("Die Breite muss eine positive ganze Zahl sein.")
        if (
            isinstance(wartezeit, bool)
            or not isinstance(wartezeit, (int, float))
            or wartezeit <= 0
        ):
            raise ValueError("Die Wartezeit muss eine positive Zahl sein.")
        self.modell = modell
        self.breite = breite
        self._wartezeit = float(wartezeit)

    def __repr__(self) -> str:
        adresse = self._schwaerzen(self._adresse)
        return (
            f"ApiEinbettung(adresse={adresse!r}, modell={self.modell!r}, "
            f"breite={self.breite})"
        )

    def vektoren(self, texte: list[str]) -> list[list[float]]:
        """Ein Vektor pro Text. Die Länge jedes Vektors ist `breite`."""
        if isinstance(texte, str) or not isinstance(texte, list):
            raise TypeError("Texte müssen eine Liste sein.")
        if any(not isinstance(text, str) for text in texte):
            raise TypeError("Jeder Text muss eine Zeichenkette sein.")
        if not texte:
            return []
        nutzlast = json.dumps(
            {"model": self.modell, "input": list(texte)},
            ensure_ascii=False,
        ).encode("utf-8")
        roh = self._posten(nutzlast)
        return self._auswerten(roh, len(texte))

    def _schwaerzen(self, text: str) -> str:
        geheim = self._schluessel
        if not geheim or not text:
            return text
        text = text.replace(geheim, _REDAKTION)
        kodiert = quote(geheim, safe="")
        if kodiert and kodiert != geheim:
            text = text.replace(kodiert, _REDAKTION)
        return text

    def _verbinden(self) -> http.client.HTTPConnection:
        teile = urlsplit(self._adresse)
        host = teile.hostname or ""
        if teile.scheme == "https":
            verbindung: http.client.HTTPConnection = http.client.HTTPSConnection(
                host,
                teile.port,
                timeout=self._wartezeit,
            )
        else:
            verbindung = http.client.HTTPConnection(
                host,
                teile.port,
                timeout=self._wartezeit,
            )
        verbindung.set_debuglevel(0)
        return verbindung

    def _pfad(self) -> str:
        teile = urlsplit(self._adresse)
        pfad = teile.path or "/"
        if teile.query:
            return f"{pfad}?{teile.query}"
        return pfad

    def _posten(self, nutzlast: bytes) -> bytes:
        meldung: str | None = None
        status = 0
        roh = b""
        verbindung: http.client.HTTPConnection | None = None
        try:
            verbindung = self._verbinden()
            verbindung.request(
                "POST",
                self._pfad(),
                body=nutzlast,
                headers={
                    "Authorization": "Bearer " + self._schluessel,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "mini-ki",
                },
            )
            antwort = verbindung.getresponse()
            status = antwort.status
            roh = antwort.read()
        except Exception as fehler:
            meldung = self._schwaerzen(f"Einbettung nicht erreichbar: {fehler}")
        finally:
            if verbindung is not None:
                try:
                    verbindung.close()
                except Exception:
                    pass
        if meldung is not None:
            raise EinbettungApiFehler(meldung)
        if status < 200 or status >= 300:
            text = self._http_text(status, roh)
            raise EinbettungApiFehler(text)
        return roh

    def _http_text(self, status: int, roh: bytes) -> str:
        hinweis = self._fehlertext(roh)
        if hinweis:
            text = f"Einbettung fehlgeschlagen (HTTP {status}): {hinweis}"
        else:
            text = f"Einbettung fehlgeschlagen (HTTP {status})."
        return self._schwaerzen(text)

    def _fehlertext(self, roh: bytes) -> str:
        try:
            ladung = json.loads(roh)
        except json.JSONDecodeError:
            return ""
        if not isinstance(ladung, dict):
            return ""
        fehler = ladung.get("error")
        meldung: object = ""
        if isinstance(fehler, dict):
            meldung = fehler.get("message", "")
        elif isinstance(fehler, str):
            meldung = fehler
        if not isinstance(meldung, str) or meldung == "":
            oben = ladung.get("message")
            meldung = oben if isinstance(oben, str) else ""
        if not isinstance(meldung, str):
            return ""
        gereinigt = self._schwaerzen(meldung)
        gereinigt = " ".join(gereinigt.split())
        if len(gereinigt) > 300:
            return gereinigt[:300] + "…"
        return gereinigt

    def _auswerten(self, roh: bytes, anzahl: int) -> list[list[float]]:
        try:
            ladung = json.loads(roh)
        except json.JSONDecodeError:
            raise ValueError("Einbettung lieferte kein JSON.") from None
        if not isinstance(ladung, dict):
            raise ValueError("Einbettung lieferte kein JSON-Objekt.")
        daten = ladung.get("data")
        if not isinstance(daten, list) or len(daten) != anzahl:
            raise ValueError("Einbettung lieferte nicht einen Vektor pro Text.")
        paare = [self._eintrag_lesen(eintrag) for eintrag in daten]
        paare.sort(key=lambda paar: paar[0])
        indizes = [index for index, _vektor in paare]
        if indizes != list(range(anzahl)):
            raise ValueError("Einbettung lieferte keine vollständige Indexfolge.")
        return [vektor for _index, vektor in paare]

    def _eintrag_lesen(self, eintrag: object) -> tuple[int, list[float]]:
        if not isinstance(eintrag, dict):
            raise ValueError("Einbettung lieferte einen ungültigen Eintrag.")
        index = eintrag.get("index")
        if isinstance(index, bool) or not isinstance(index, int):
            raise ValueError("Einbettung lieferte einen ungültigen Index.")
        roh = eintrag.get("embedding")
        if not isinstance(roh, list):
            raise ValueError("Einbettung lieferte keinen Vektor.")
        zahlen: list[float] = []
        for wert in roh:
            if isinstance(wert, bool) or not isinstance(wert, (int, float)):
                raise ValueError("Einbettung lieferte keine Zahlen.")
            zahl = float(wert)
            if not math.isfinite(zahl):
                raise ValueError("Einbettung lieferte keine endliche Zahl.")
            zahlen.append(zahl)
        if len(zahlen) != self.breite:
            raise ValueError(
                f"Vektor hat Breite {len(zahlen)}, erwartet {self.breite}."
            )
        return index, zahlen
