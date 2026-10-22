"""Anhänge pro Eintrag. Bytes liegen neben der SQLite-Datei, nicht darin."""

import hashlib
import os
import sqlite3
from pathlib import Path

from mini_ki import MiniKI

FRAGE = "Wie spät ist es?"
ANDERE = "Wie spät ist es in Berlin?"
ANTWORT = "Es ist drei Uhr am späteren Nachmittag."
NEU = "Es ist vier Uhr am späteren Nachmittag."
AUDIO = b"OggS" + b"\x00mini-ki-opus-test\xff" * 40
AUDIO_NEU = b"OggS" + b"\x00mini-ki-opus-neu\xff" * 40
MARKER = b"MINI-KI-AUSBRUCH-9f3c1a" * 30
VEKTOR = [1.0, 0.0, 0.0, 0.0]
ANDERS = [0.0, 1.0, 0.0, 0.0]

ANGRIFFE = [
    "../",
    "..",
    ".",
    "  ../  ",
    "../audio",
    "..\\audio",
    "audio/../../geheim",
    "/etc/passwd",
    "a/b",
    "a\\b",
    "audio\x00",
    "audio\n",
    "",
    " ",
    "....",
    "..%2f..%2f",
    "foo/../../../tmp/pwn",
    "\u2215..\u2215",
    "audio/..",
    "./audio",
    "anhang/audio",
    "a" * 70,
]


class FesteEinbettung:
    """Wörterbuch Text → Vektor. Breite folgt aus den Vektoren."""

    def __init__(self, vektoren: dict[str, list[float]]) -> None:
        breiten = {len(vektor) for vektor in vektoren.values()}
        if len(breiten) != 1:
            raise ValueError("Alle Vektoren brauchen dieselbe Breite.")
        self.modell = "test-modell"
        self.breite = breiten.pop()
        self._vektoren = dict(vektoren)

    def vektoren(self, texte: list[str]) -> list[list[float]]:
        fehlend = [text for text in texte if text not in self._vektoren]
        if fehlend:
            raise KeyError(fehlend[0])
        return [list(self._vektoren[text]) for text in texte]


def oeffnen(pfad: Path, *fragen: str) -> MiniKI:
    vektoren = {frage: VEKTOR for frage in fragen}
    if ANDERE in vektoren:
        vektoren[ANDERE] = ANDERS
    return MiniKI(pfad, FesteEinbettung(vektoren))


def pruefsumme(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def dateibaum(wurzel: Path) -> set[str]:
    gefunden: set[str] = set()
    for verzeichnis, dirs, dateien in os.walk(wurzel):
        for name in dirs + dateien:
            gefunden.add(str(Path(verzeichnis, name).relative_to(wurzel)))
    return gefunden


def test_audio_setzen_finden_lesen_umschreiben_vergessen(tmp_path):
    pfad = tmp_path / "mandant" / "mini-ki.sqlite"
    kern = oeffnen(pfad, FRAGE)
    kennung = kern.merken(FRAGE, ANTWORT, bewertung="gut")
    assert kennung
    leer = kern.finden(FRAGE)
    assert leer is not None
    assert leer.get("anhaenge", []) == []

    assert kern.anhang_setzen(kennung, "audio", AUDIO) is True
    datei = pfad.parent / "anhaenge" / kennung / "audio"
    assert datei.is_file()
    assert datei.read_bytes() == AUDIO
    assert datei.resolve().is_relative_to(pfad.resolve().parent)

    treffer = kern.finden(FRAGE)
    assert treffer is not None
    assert treffer["id"] == kennung
    assert treffer["antwort"] == ANTWORT
    assert treffer["aehnlichkeit"] == 1.0
    gespeichert = kern.laden(kennung)["antwort"]
    erwartet = pruefsumme(gespeichert)
    assert treffer["anhaenge"] == [
        {
            "art": "audio",
            "medientyp": "audio/ogg; codecs=opus",
            "groesse": len(AUDIO),
            "pruefsumme": erwartet,
        }
    ]
    assert erwartet != hashlib.sha256(AUDIO).hexdigest()
    assert kern.anhang_lesen(kennung, "audio") == AUDIO

    with sqlite3.connect(pfad) as conn:
        spalten = [row[1] for row in conn.execute("PRAGMA table_info(anhang)")]
    assert spalten == ["eintrag_id", "art", "medientyp", "groesse", "pruefsumme"]
    roh = pfad.read_bytes()
    for endung in ("-wal", "-shm"):
        extra = Path(str(pfad) + endung)
        if extra.is_file():
            roh += extra.read_bytes()
    assert AUDIO not in roh

    assert kern.umschreiben(kennung, NEU) is True
    assert kern.laden(kennung)["antwort"] == NEU
    assert not datei.exists()
    assert kern.anhang_lesen(kennung, "audio") is None
    danach = kern.finden(FRAGE)
    assert danach is not None
    assert danach["antwort"] == NEU
    assert danach.get("anhaenge", []) == []

    assert kern.anhang_setzen(kennung, "audio", AUDIO_NEU) is True
    assert kern.anhang_lesen(kennung, "audio") == AUDIO_NEU
    assert datei.read_bytes() == AUDIO_NEU
    neu_treffer = kern.finden(FRAGE)
    assert neu_treffer["anhaenge"][0]["pruefsumme"] == pruefsumme(NEU)
    assert neu_treffer["anhaenge"][0]["groesse"] == len(AUDIO_NEU)

    assert kern.vergessen(kennung) is True
    assert not datei.exists()
    assert kern.anhang_lesen(kennung, "audio") is None
    assert kern.laden(kennung) is None
    assert kern.finden(FRAGE) is None
    rest = [
        eintrag
        for eintrag in (pfad.parent / "anhaenge").rglob("*")
        if eintrag.is_file()
    ]
    assert rest == []
    with sqlite3.connect(pfad) as conn:
        assert conn.execute("SELECT COUNT(*) FROM anhang").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM eintrag").fetchone()[0] == 0


def test_anhang_ueberlebt_erneutes_oeffnen(tmp_path):
    pfad = tmp_path / "mandant" / "mini-ki.sqlite"
    kern = oeffnen(pfad, FRAGE)
    kennung = kern.merken(FRAGE, ANTWORT, bewertung="gut")
    assert kern.anhang_setzen(kennung, "audio", AUDIO) is True
    del kern

    neu = oeffnen(pfad, FRAGE)
    treffer = neu.finden(FRAGE)
    assert treffer is not None
    assert treffer["anhaenge"][0]["medientyp"] == "audio/ogg; codecs=opus"
    assert treffer["anhaenge"][0]["pruefsumme"] == pruefsumme(ANTWORT)
    assert neu.anhang_lesen(kennung, "audio") == AUDIO
    datei = pfad.parent / "anhaenge" / kennung / "audio"
    assert datei.read_bytes() == AUDIO

    assert neu.umschreiben(kennung, NEU) is True
    assert not datei.exists()
    assert neu.anhang_lesen(kennung, "audio") is None
    assert neu.finden(FRAGE).get("anhaenge", []) == []


def test_art_pfad_ausbruch_wird_abgewiesen(tmp_path):
    basis = tmp_path / "daten"
    pfad = basis / "mini-ki.sqlite"
    kern = oeffnen(pfad, FRAGE, ANDERE)
    kennung = kern.merken(FRAGE, ANTWORT, bewertung="gut")
    boese = kern.merken(ANDERE, "Text bleibt, die Datei nicht.", id="../boese")
    assert boese == "../boese"
    vorher = dateibaum(tmp_path)

    for art in ANGRIFFE:
        assert kern.anhang_setzen(kennung, art, MARKER) is False
        assert kern.anhang_lesen(kennung, art) is None
    assert kern.anhang_setzen(kennung, b"../", MARKER) is False
    assert kern.anhang_setzen(boese, "audio", MARKER) is False
    assert kern.anhang_setzen(kennung, "audio", "kein-bytes") is False
    assert kern.anhang_setzen("fehlt-id-123", "audio", MARKER) is False
    assert kern.anhang_lesen(boese, "audio") is None

    assert dateibaum(tmp_path) - vorher == set()
    for verzeichnis, _dirs, dateien in os.walk(tmp_path):
        for name in dateien:
            assert MARKER not in Path(verzeichnis, name).read_bytes()
    assert not (basis / "anhaenge").exists()

    assert kern.anhang_setzen(kennung, "audio", AUDIO) is True
    assert kern.anhang_setzen(boese, "audio", AUDIO) is False
    fund = []
    for verzeichnis, _dirs, dateien in os.walk(tmp_path):
        for name in dateien:
            datei = Path(verzeichnis, name)
            if AUDIO in datei.read_bytes():
                fund.append(datei)
    assert fund == [basis / "anhaenge" / kennung / "audio"]


def test_umschreiben_ohne_erfolg_behaelt_audio(tmp_path):
    pfad = tmp_path / "stift.sqlite"
    kern = oeffnen(pfad, FRAGE)
    kennung = kern.merken(FRAGE, ANTWORT, bewertung="gut")
    assert kern.anhang_setzen(kennung, "audio", AUDIO) is True
    datei = pfad.parent / "anhaenge" / kennung / "audio"

    assert kern.umschreiben(kennung, "   ") is False
    assert kern.umschreiben(kennung, "Bitte an ada@example.com schreiben.") is False
    assert datei.read_bytes() == AUDIO
    assert kern.anhang_lesen(kennung, "audio") == AUDIO

    assert kern.bewerten(kennung, "schlecht") is True
    assert kern.umschreiben(kennung, NEU) is False
    assert kern.laden(kennung)["antwort"] == ANTWORT
    assert datei.read_bytes() == AUDIO
    assert kern.anhang_lesen(kennung, "audio") == AUDIO
    assert kern.finden(FRAGE) is None


def test_formulierung_liefert_den_anhang(tmp_path):
    pfad = tmp_path / "formen.sqlite"
    vektoren = {
        "Startfrage": VEKTOR,
        "Andere Formulierung": ANDERS,
    }
    kern = MiniKI(pfad, FesteEinbettung(vektoren))
    kennung = kern.merken(
        "Startfrage",
        "Die Antwort bleibt gleich laut.",
        bewertung="gut",
    )
    assert kern.anhang_setzen(kennung, "audio", AUDIO) is True
    assert kern.formen(kennung, ["Andere Formulierung"]) == 1

    treffer = kern.finden("Andere Formulierung")
    assert treffer is not None
    assert treffer["id"] == kennung
    assert treffer["anhaenge"][0]["art"] == "audio"
    assert kern.anhang_lesen(kennung, "audio") == AUDIO
    assert kern.finden("Startfrage") is None

    assert kern.umschreiben(kennung, "Ein neuer Satz ohne Ton.") is True
    assert kern.anhang_lesen(kennung, "audio") is None
    assert kern.finden("Andere Formulierung").get("anhaenge", []) == []


def test_anhang_ersetzen_und_zweite_art(tmp_path):
    pfad = tmp_path / "zwei.sqlite"
    kern = oeffnen(pfad, FRAGE, ANDERE)
    kennung = kern.merken(FRAGE, ANTWORT, bewertung="gut")
    nachbar = kern.merken(ANDERE, "Die andere Antwort bleibt stehen.", bewertung="gut")
    assert kern.anhang_setzen(kennung, "audio", b"eins") is True
    assert kern.anhang_setzen(kennung, "audio", bytearray(b"zwei")) is True
    assert kern.anhang_lesen(kennung, "audio") == b"zwei"
    assert kern.anhang_setzen(kennung, "notiz", b"hello") is True
    assert kern.anhang_setzen(nachbar, "audio", b"bleibt") is True

    anhaenge = kern.finden(FRAGE)["anhaenge"]
    assert [eintrag["art"] for eintrag in anhaenge] == ["audio", "notiz"]
    assert anhaenge[0]["groesse"] == 4
    assert anhaenge[0]["medientyp"] == "audio/ogg; codecs=opus"
    assert anhaenge[1]["medientyp"] == "application/octet-stream"
    assert anhaenge[1]["groesse"] == 5
    assert kern.anhang_lesen(kennung, "notiz") == b"hello"

    assert kern.vergessen(kennung) is True
    assert kern.anhang_lesen(kennung, "audio") is None
    assert kern.anhang_lesen(kennung, "notiz") is None
    assert not (pfad.parent / "anhaenge" / kennung).exists()
    assert kern.anhang_lesen(nachbar, "audio") == b"bleibt"
    assert (pfad.parent / "anhaenge" / nachbar / "audio").read_bytes() == b"bleibt"
