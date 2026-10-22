"""Kern. Ein Objekt pro Speicher, Schwellen und Einbettung kommen von außen."""

from __future__ import annotations

import threading
import uuid
from pathlib import Path

from .audio import STANDARD_BITRATE, AudioFehler, bitrate_pruefen, nach_opus, nach_pcm
from .audio import OPUS_MEDIENTYP as _AUDIO_MEDIENTYP
from .einbettung import Einbettung
from .speicher_sqlite import SqliteSpeicher
from .sperre import gesperrt

_DATEI_MEDIENTYP = "application/octet-stream"


def _norm(text: str) -> str:
    return " ".join((text or "").split()).casefold()


def _feld(wert: object) -> str:
    """Nur gewöhnliche Leerzeichen am Rand. Zeilenumbrüche bleiben und scheitern später."""
    if not isinstance(wert, str):
        return ""
    return wert.strip(" ")


class MiniKI:
    """Antwortspeicher. Gut wird wiederverwendet, schlecht nur gelesen."""

    def __init__(
        self,
        pfad: str | Path,
        einbettung: Einbettung,
        *,
        schwelle: float = 0.80,
        gegen_schwelle: float = 0.93,
        gleich_schwelle: float = 0.65,
        audio_bitrate: int = STANDARD_BITRATE,
    ) -> None:
        self._einbettung = einbettung
        self._schwelle = schwelle
        self._gegen_schwelle = gegen_schwelle
        self._gleich_schwelle = gleich_schwelle
        self._audio_bitrate = bitrate_pruefen(audio_bitrate)
        self._lock = threading.Lock()
        self._speicher = SqliteSpeicher(
            pfad,
            einbettung.modell,
            einbettung.breite,
            self._lock,
        )
        self._speicher.bereitstellen()

    def finden(self, frage: str) -> dict | None:
        """Nur `gut`. Erster Treffer ab der Schwelle. Anhänge stehen dabei, wenn welche da sind."""
        frage = (frage or "").strip()
        if not frage or gesperrt(frage):
            return None
        vektor = self._vektoren([frage])[0]
        gegen, kandidaten = self._speicher.nahe(vektor)
        ueberspringen = self._gesperrte(gegen)
        for eintrag_id, antwort, abstand in kandidaten:
            if eintrag_id in ueberspringen:
                continue
            aehnlichkeit = 1.0 - abstand
            if aehnlichkeit < self._schwelle:
                break
            ergebnis = {
                "id": eintrag_id,
                "antwort": antwort,
                "aehnlichkeit": round(aehnlichkeit, 3),
            }
            anhaenge = self._speicher.anhaenge_lesen(eintrag_id)
            if anhaenge:
                ergebnis["anhaenge"] = anhaenge
            return ergebnis
        return None

    def merken(
        self,
        frage: str,
        antwort: str,
        bewertung: str | None = None,
        id: str | None = None,
    ) -> str | None:
        """Neue Zeile. Der Vektor gehört zur Frage."""
        frage = (frage or "").strip()
        antwort = (antwort or "").strip()
        if bewertung not in (None, "gut", "schlecht"):
            return None
        if not frage or not antwort or gesperrt(frage) or gesperrt(antwort):
            return None
        eintrag_id = (id or "").strip() or uuid.uuid4().hex
        vektor = self._vektoren([frage])[0]
        self._speicher.einfuegen(eintrag_id, frage, antwort, bewertung, vektor)
        return eintrag_id

    def bewerten(self, id: str, bewertung: str) -> bool:
        if bewertung not in ("gut", "schlecht"):
            return False
        eintrag_id = (id or "").strip()
        if not eintrag_id:
            return False
        return self._speicher.bewertung_setzen(eintrag_id, bewertung)

    def umschreiben(self, id: str, antwort: str) -> bool:
        """Neuer Text. Der Vektor bleibt, Anhänge fallen weg. `schlecht` bleibt stehen."""
        eintrag_id = (id or "").strip()
        antwort = (antwort or "").strip()
        if not eintrag_id or not antwort or gesperrt(antwort):
            return False
        return self._speicher.antwort_setzen(eintrag_id, antwort)

    def laden(self, id: str) -> dict | None:
        eintrag_id = (id or "").strip()
        if not eintrag_id:
            return None
        return self._speicher.lesen(eintrag_id)

    def vergessen(self, id: str) -> bool:
        """Eintrag, Formulierungen, Vektoren und Anhänge weg."""
        eintrag_id = (id or "").strip()
        if not eintrag_id:
            return False
        return self._speicher.loeschen(eintrag_id)

    def anhang_setzen(
        self,
        id: str,
        art: str,
        daten: bytes,
        medientyp: str | None = None,
    ) -> bool:
        """Bytes zum Eintrag. `audio` liegt als Opus (Ogg) neben der Datenbank.

        PCM (`audio/L16; rate=24000; channels=1`) und WAV werden mit der
        gesetzten Bitrate umgewandelt. Opus wird geprüft und unverändert
        abgelegt. Ohne Medientyp bleiben die Bytes, wie sie kamen.
        """
        eintrag_id = _feld(id)
        art_text = _feld(art)
        if isinstance(daten, bytearray):
            daten = bytes(daten)
        if not eintrag_id or not art_text or not isinstance(daten, bytes):
            return False
        if medientyp is not None and not isinstance(medientyp, str):
            return False
        if art_text == "audio":
            daten = nach_opus(daten, medientyp, bitrate=self._audio_bitrate)
            gespeichert = _AUDIO_MEDIENTYP
        else:
            gespeichert = _DATEI_MEDIENTYP
        return self._speicher.anhang_setzen(eintrag_id, art_text, daten, gespeichert)

    def anhang_lesen(
        self,
        id: str,
        art: str,
        *,
        format: str | None = None,
    ) -> bytes | None:
        """Bytes des Anhangs, oder nichts wenn er fehlt oder die Art aus dem Ordner ausbricht.

        `format="pcm"` wandelt gespeichertes Audio nach 24 kHz mono zurück.
        """
        eintrag_id = _feld(id)
        art_text = _feld(art)
        if not eintrag_id or not art_text:
            return None
        ziel = (format or "").strip().lower()
        if ziel not in ("", "pcm", "opus", "ogg"):
            raise AudioFehler("Das Format ist unbekannt.")
        daten = self._speicher.anhang_lesen(eintrag_id, art_text)
        if daten is None or ziel in ("", "opus", "ogg"):
            return daten
        if art_text != "audio":
            raise AudioFehler("Nur Audio lässt sich nach PCM wandeln.")
        return nach_pcm(daten)

    def trennen(self, frage: str, id: str) -> bool:
        """Diese Frage soll diese Antwort nicht mehr treffen."""
        frage = (frage or "").strip()
        eintrag_id = (id or "").strip()
        if not frage or not eintrag_id or gesperrt(frage):
            return False
        vektor = self._vektoren([frage])[0]
        self._speicher.gegen_merken(eintrag_id, frage, vektor)
        return True

    def gesperrte_ids(self, frage: str) -> set[str]:
        frage = (frage or "").strip()
        if not frage or gesperrt(frage):
            return set()
        vektor = self._vektoren([frage])[0]
        gegen, _kandidaten = self._speicher.nahe(vektor)
        return self._gesperrte(gegen)

    def formen(self, id: str, fragen: list[str]) -> int:
        """Mehrere Formulierungen zu einer Antwort. Jede bekommt einen eigenen Vektor."""
        eintrag_id = (id or "").strip()
        gesehen: set[str] = set()
        sauber: list[str] = []
        for eintrag in fragen:
            text = " ".join((eintrag or "").split())
            schluessel = text.casefold()
            if not text or schluessel in gesehen or gesperrt(text):
                continue
            gesehen.add(schluessel)
            sauber.append(text)
        if not eintrag_id or not sauber:
            return 0
        vektoren = self._vektoren(sauber)
        return self._speicher.formulierungen_ersetzen(eintrag_id, sauber, vektoren)

    def gleiche_antwort(
        self,
        antwort: str,
        ueberspringen: set[str] | None = None,
    ) -> str | None:
        """Dieselbe gespeicherte Antwort, auch wenn die Frage anders ankam."""
        ziel = (antwort or "").strip()
        gefaltet = _norm(ziel)
        if len(gefaltet) < 40 or gesperrt(ziel):
            return None
        woerter = set(gefaltet.split())
        auslassen = ueberspringen or set()
        beste_id = None
        beste = 0.0
        for eintrag_id, text in self._speicher.gute_antworten():
            if eintrag_id in auslassen:
                continue
            gespeichert = _norm(text or "")
            if not gespeichert:
                continue
            if gespeichert == gefaltet:
                return eintrag_id
            andere = set(gespeichert.split())
            if not andere:
                continue
            wert = len(woerter & andere) / len(woerter | andere)
            if wert > beste:
                beste = wert
                beste_id = eintrag_id
        if beste >= self._gleich_schwelle:
            return beste_id
        return None

    def _gesperrte(self, gegen: list[tuple[str, float]]) -> set[str]:
        return {
            eintrag_id
            for eintrag_id, abstand in gegen
            if 1.0 - abstand >= self._gegen_schwelle
        }

    def _vektoren(self, texte: list[str]) -> list[list[float]]:
        if not texte:
            return []
        roh = self._einbettung.vektoren(list(texte))
        if len(roh) != len(texte):
            raise ValueError("Einbettung lieferte nicht einen Vektor pro Text.")
        breite = self._speicher.breite
        fertig: list[list[float]] = []
        for vektor in roh:
            zahlen = [float(wert) for wert in vektor]
            if len(zahlen) != breite:
                raise ValueError("Vektor hat nicht die Breite der Einbettung.")
            fertig.append(zahlen)
        return fertig
