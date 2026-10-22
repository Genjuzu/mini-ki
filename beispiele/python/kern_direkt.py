"""Kern direkt, so wie der Live-Avatar ihn später nutzt.

Läuft gegen die Fake-Einbettung: kein Modell, kein Netz, keine Gewichte.
Aufruf vom Repository aus: `python3 beispiele/python/kern_direkt.py`
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_WURZEL = Path(__file__).resolve().parents[2]
_QUELLE = _WURZEL / "src"
if _QUELLE.is_dir():
    sys.path.insert(0, str(_QUELLE))

from mini_ki import MiniKI  # noqa: E402

from fake_einbettung import FakeEinbettung  # noqa: E402
from texte import (  # noqa: E402
    ANDERE,
    ANTWORT,
    BUERO,
    BUERO_ANTWORT,
    FRAGE,
    UMSCHRIEBEN,
)

AUDIO = b"OggS" + b"\x00mini-ki-beispiel-audio"


def _pruefen(bedingung: bool, text: str) -> None:
    if not bedingung:
        raise SystemExit(text)


def _punkt(links: list[float], rechts: list[float]) -> float:
    return sum(x * y for x, y in zip(links, rechts))


def main() -> None:
    einbettung = FakeEinbettung()
    kontakt = einbettung.vektoren([FRAGE])[0]
    nah = _punkt(kontakt, einbettung.vektoren([ANDERE])[0])
    _pruefen(0.80 <= nah < 0.93, "Die Formulierung liegt nicht zwischen den Schwellen.")
    fremd = einbettung.vektoren([BUERO])[0]
    _pruefen(abs(_punkt(kontakt, fremd)) < 0.5, "Fremde Frage liegt zu nah am Kontakt-Vektor.")

    with tempfile.TemporaryDirectory(prefix="mini-ki-kern-") as ordner:
        kern = MiniKI(Path(ordner) / "mini-ki.sqlite", einbettung)
        _pruefen(kern.finden(FRAGE) is None, "Vor dem Merken darf nichts treffen.")
        _pruefen(
            kern.merken("Bitte an ada@example.com schreiben.", ANTWORT) is None,
            "Eine E-Mail darf nicht in den Speicher.",
        )

        kennung = kern.merken(FRAGE, ANTWORT)
        _pruefen(bool(kennung), "Die Frage wurde nicht gemerkt.")
        _pruefen(kern.finden(FRAGE) is None, "Ohne Daumen hoch bleibt der Eintrag stumm.")
        _pruefen(kern.bewerten(kennung, "gut"), "Daumen hoch wurde nicht gespeichert.")

        genau = kern.finden(FRAGE)
        _pruefen(genau is not None and genau["id"] == kennung, "Die gemerkte Frage trifft nicht.")
        _pruefen(genau["aehnlichkeit"] == 1.0, "Dieselbe Frage muss Ähnlichkeit 1 haben.")
        treffer = kern.finden(ANDERE)
        _pruefen(treffer is not None and treffer["id"] == kennung, "Die andere Formulierung trifft nicht.")
        _pruefen(treffer["antwort"] == ANTWORT, "Die gespeicherte Antwort fehlt.")
        _pruefen(0.80 <= treffer["aehnlichkeit"] < 0.93, "Die Formulierung liegt nicht zwischen den Schwellen.")

        _pruefen(kern.anhang_setzen(kennung, "audio", AUDIO), "Das Audio wurde nicht gespeichert.")
        mit_audio = kern.finden(FRAGE)
        _pruefen(mit_audio is not None and mit_audio.get("anhaenge"), "Der Treffer nennt das Audio nicht.")
        anhang = mit_audio["anhaenge"][0]
        _pruefen(anhang["art"] == "audio", "Die Anhang-Art ist nicht audio.")
        _pruefen(anhang["medientyp"] == "audio/ogg; codecs=opus", "Der Medientyp ist nicht Opus.")
        _pruefen(anhang["groesse"] == len(AUDIO), "Die Größe des Audios stimmt nicht.")
        _pruefen("daten" not in anhang, "Der Treffer darf die Bytes nicht mitliefern.")
        _pruefen(kern.anhang_lesen(kennung, "audio") == AUDIO, "Das Audio lässt sich nicht lesen.")

        _pruefen(kern.umschreiben(kennung, UMSCHRIEBEN), "Der Text wurde nicht umgeschrieben.")
        _pruefen(kern.anhang_lesen(kennung, "audio") is None, "Nach der Textänderung muss das Audio weg sein.")
        neu = kern.finden(FRAGE)
        _pruefen(neu is not None and neu["antwort"] == UMSCHRIEBEN, "Der neue Text fehlt im Treffer.")
        _pruefen("anhaenge" not in neu, "Der Treffer nennt ein verfallenes Audio.")

        _pruefen(kern.trennen(ANDERE, kennung), "Die Formulierung wurde nicht getrennt.")
        _pruefen(kern.finden(ANDERE) is None, "Die getrennte Formulierung trifft noch.")
        bleibt = kern.finden(FRAGE)
        _pruefen(bleibt is not None and bleibt["id"] == kennung, "Die ursprüngliche Frage muss gut bleiben.")

        andere = kern.merken(BUERO, BUERO_ANTWORT)
        _pruefen(bool(andere), "Die Büro-Frage wurde nicht gemerkt.")
        _pruefen(kern.bewerten(andere, "schlecht"), "Daumen runter auf die neue Antwort scheiterte.")
        _pruefen(kern.finden(BUERO) is None, "Eine schlechte Antwort darf nicht zurückkommen.")
        bleibt_gut = kern.finden(FRAGE)
        _pruefen(
            bleibt_gut is not None and bleibt_gut["id"] == kennung,
            "Der gute Eintrag darf durch die zweite Frage nicht kippen.",
        )

        _pruefen(kern.vergessen(kennung), "Der Eintrag wurde nicht vergessen.")
        _pruefen(kern.finden(FRAGE) is None, "Nach dem Vergessen liegt die Antwort noch da.")
        _pruefen(kern.anhang_lesen(kennung, "audio") is None, "Nach dem Vergessen liegt das Audio noch da.")

    print("Kern direkt: Treffer, Audio, Daumen runter und Vergessen sind durchgelaufen.")


if __name__ == "__main__":
    main()
