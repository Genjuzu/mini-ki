"""Sprachmodell-Helfer mit einem eingesetzten Fake, ohne Anbieter."""

import json

import pytest

from mini_ki import MiniKI
from mini_ki.sprachmodell import (
    SprachmodellFehler,
    formulierungen,
    formulierungen_lesen,
    neu,
    verweis_umschreiben,
)

FRAGE = "Wie erreiche ich Avatari?"
ALT = "Die Kontaktdaten stehen auf der Webseite von Avatari."
NEU = "Avatari erreichen Sie über die Webseite, dort stehen die Kontaktdaten."
ANDERE = "Wo finde ich den Kontakt von Avatari?"
E0 = [1.0, 0.0, 0.0, 0.0]
E1 = [0.0, 1.0, 0.0, 0.0]
E2 = [0.0, 0.0, 1.0, 0.0]


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


class _Einbettung:
    def __init__(self, vektoren: dict[str, list[float]]) -> None:
        self.modell = "test-modell"
        self.breite = 4
        self._vektoren = vektoren
        self.aufrufe: list[list[str]] = []

    def vektoren(self, texte: list[str]) -> list[list[float]]:
        self.aufrufe.append(list(texte))
        return [list(self._vektoren[text]) for text in texte]


def test_json_im_codezaun_wird_gelesen():
    zaun = """Einleitung
```json
{"kanonisch": "Wetter heute", "formen": ["Wie wird das Wetter?", "Wetter heute"]}
Danach egal.
```
"""
    assert formulierungen_lesen(zaun) == [
        "Wetter heute",
        "Wie wird das Wetter?",
    ]
    assert formulierungen_lesen(
        '{"kanonisch": "Nur diese", "formen": []}'
    ) == ["Nur diese"]
    ohne_sprache = '```\n{"kanonisch": "Ohne Sprache", "formen": ["Zweite"]}\n```'
    assert formulierungen_lesen(ohne_sprache) == ["Ohne Sprache", "Zweite"]
    geklebt = '```json{"kanonisch": "Geklebt", "formen": []}```'
    assert formulierungen_lesen(geklebt) == ["Geklebt"]


def test_dubletten_fallen_weg_und_hoechstens_acht():
    formen = [f"Formulierung {i}" for i in range(1, 12)]
    roh = json.dumps(
        {
            "kanonisch": "Formulierung 0",
            "formen": ["formulierung 0", *formen, "FORMULIERUNG 3"],
        }
    )
    liste = formulierungen_lesen("```json\n" + roh + "\n```")
    assert liste == [f"Formulierung {i}" for i in range(8)]
    assert formulierungen_lesen(
        json.dumps(
            {"kanonisch": "Alpha   Frage", "formen": ["alpha frage", " "]}
        )
    ) == ["Alpha Frage"]
    assert formulierungen_lesen(
        json.dumps({"kanonisch": "Die Straße", "formen": ["die strasse"]})
    ) == ["Die Straße"]
    assert formulierungen_lesen(
        json.dumps({"kanonisch": "A", "formen": [None, 3, {"x": 1}, "B"]})
    ) == ["A", "B"]


def test_gesperrte_texte_fallen_aus_den_formulierungen():
    assert formulierungen_lesen(
        json.dumps(
            {
                "kanonisch": "ada@example.com",
                "formen": [
                    "Wie erreiche ich Avatari?",
                    "+49 151 23456789",
                    "DE89370400440532013000",
                ],
            }
        )
    ) == ["Wie erreiche ich Avatari?"]


def test_kaputtes_json_ergibt_leere_liste():
    assert formulierungen_lesen("```json\n{nein\n```") == []
    assert formulierungen_lesen("kein json") == []
    assert formulierungen_lesen("") == []
    assert formulierungen_lesen('{"formen": "text"}') == []
    assert formulierungen_lesen("[]") == []
    assert formulierungen_lesen("{nein}") == []


def test_verweis_wird_umgeschrieben():
    modell = _Modell('"Wie erreiche ich Avatari?"')
    ergebnis = verweis_umschreiben(
        modell,
        "Ja, ich möchte mehr darüber erfahren",
        "Gast: Wie erreiche ich Avatari?\nAntwort: Über die Webseite.",
    )
    assert ergebnis == FRAGE
    assert len(modell.aufrufe) == 1
    system, nutzer = modell.aufrufe[0]
    assert "allein stehenden Frage" in system
    assert "darüber" in nutzer
    assert "Webseite" in nutzer

    erste_zeile = _Modell("Wie erreiche ich Avatari?\nUnd noch ein Satz.")
    assert verweis_umschreiben(erste_zeile, "Ja") == FRAGE
    assert "Ja" in erste_zeile.aufrufe[0][1]


def test_volle_frage_bleibt():
    modell = _Modell(FRAGE)
    frage = "Ist Avatari DSGVO-konform?"
    assert verweis_umschreiben(modell, frage, "Gast: vorher") == frage
    assert modell.aufrufe == []
    lang = "Ja " + " ".join(["wort"] * 20)
    assert verweis_umschreiben(modell, lang) == lang
    assert modell.aufrufe == []


def test_modellfehler_ergibt_die_originalfrage():
    frage = "Ja, dazu"
    assert verweis_umschreiben(_Modell(RuntimeError("netz")), frage) == frage
    assert verweis_umschreiben(_Modell("   "), frage) == frage
    assert verweis_umschreiben(_Modell("ada@example.com"), frage) == frage
    assert verweis_umschreiben(_Modell('{"kanonisch": "x"}'), frage) == frage
    assert verweis_umschreiben(_Modell(None), frage) == frage


def test_formulierungen_werden_erzeugt():
    zaun = """```json
{"kanonisch": "Wie erreiche ich Avatari?", "formen": ["Wo finde ich den Kontakt?", "wie erreiche ich avatari?"]}
```"""
    modell = _Modell(zaun)
    liste = formulierungen(
        modell,
        FRAGE,
        ALT,
        "Verlauf steht hier.",
    )
    assert liste == [FRAGE, "Wo finde ich den Kontakt?"]
    system, nutzer = modell.aufrufe[0]
    assert "kanonisch" in system
    assert "Verlauf steht hier." in nutzer
    assert ALT in nutzer
    assert FRAGE in nutzer

    verweis = formulierungen(
        _Modell(
            json.dumps(
                {
                    "kanonisch": FRAGE,
                    "formen": ["Kontakt"],
                }
            )
        ),
        "Ja, dazu",
        ALT,
    )
    assert verweis[0] == FRAGE
    assert "Ja, dazu" not in verweis

    nur_frage = formulierungen(
        _Modell('{"kanonisch": "", "formen": []}'),
        FRAGE,
        ALT,
    )
    assert nur_frage == [FRAGE]


def test_formulierungen_bei_fehler_leer():
    assert formulierungen(_Modell(RuntimeError("weg")), FRAGE, ALT) == []
    assert formulierungen(_Modell("```json\n{nein\n```"), FRAGE, ALT) == []
    leer = _Modell("egal")
    assert formulierungen(leer, "", "   ") == []
    assert formulierungen(leer, "", "") == []
    assert leer.aufrufe == []


def test_vorangestellte_frage_zaehlt_ins_limit():
    formen = [f"Form {i}" for i in range(8)]
    roh = json.dumps({"kanonisch": formen[0], "formen": formen[1:]})
    liste = formulierungen(_Modell(roh), "Gesagte Frage extra", ALT)
    assert liste[0] == "Gesagte Frage extra"
    assert len(liste) == 8
    assert formen[-1] not in liste


def test_neu_mit_zusatz():
    modell = _Modell("Kurze neue Antwort.")
    text = neu(modell, FRAGE, ALT, "Bitte kürzer.")
    assert text == "Kurze neue Antwort."
    system, nutzer = modell.aufrufe[0]
    assert "Wortlaut" in system
    assert "Bitte kürzer." in nutzer
    assert "Zusatz:" in nutzer
    assert ALT in nutzer
    assert FRAGE in nutzer

    ohne = _Modell("Andere Fassung der Antwort.")
    assert neu(ohne, FRAGE, ALT) == "Andere Fassung der Antwort."
    assert "Zusatz:" not in ohne.aufrufe[0][1]


def test_neu_fehler_und_leere_antwort():
    with pytest.raises(SprachmodellFehler) as gefangen:
        neu(_Modell(RuntimeError("geheimer-hinweis")), FRAGE, ALT)
    assert "geheimer-hinweis" not in str(gefangen.value)
    with pytest.raises(SprachmodellFehler):
        neu(_Modell("Schreib an ada@example.com"), FRAGE, ALT)
    with pytest.raises(SprachmodellFehler):
        neu(_Modell("   "), FRAGE, ALT)
    modell = _Modell("x")
    with pytest.raises(ValueError):
        neu(modell, FRAGE, "   ")
    assert modell.aufrufe == []


def test_verweis_formen_und_neu_am_speicher(tmp_path):
    """Verweis suchen, Formulierungen ablegen, Antwort neu schreiben."""
    einbettung = _Einbettung(
        {
            FRAGE: E0,
            ANDERE: E1,
            "Ja, dazu": E2,
            "Ist Avatari DSGVO-konform?": E2,
        }
    )

    gesehen: list[str] = []

    def modell(system: str, nutzer: str) -> str:
        gesehen.append(nutzer)
        if "Neue Äußerung" in nutzer:
            assert "Ja, dazu" in nutzer
            assert "Webseite" in nutzer
            return FRAGE
        if "Gesagte Frage" in nutzer:
            return (
                "```json\n"
                + json.dumps(
                    {
                        "kanonisch": FRAGE,
                        "formen": [ANDERE, "wie erreiche ich avatari?"],
                    }
                )
                + "\n```"
            )
        if "Bisherige Antwort" in nutzer:
            assert "Bitte kürzer." in nutzer
            return NEU
        raise AssertionError(nutzer)

    kern = MiniKI(tmp_path / "mini-ki.sqlite", einbettung)
    kennung = kern.merken(FRAGE, ALT, bewertung="gut")
    assert kennung
    audio = b"OggS-platzhalter"
    assert kern.anhang_setzen(kennung, "audio", audio) is True

    verlauf = "Gast: Wie erreiche ich Avatari?\nAntwort: " + ALT
    allein = verweis_umschreiben(modell, "Ja, dazu", verlauf)
    assert allein == FRAGE
    treffer = kern.finden(allein)
    assert treffer is not None
    assert treffer["id"] == kennung
    assert treffer["antwort"] == ALT
    assert treffer["anhaenge"][0]["art"] == "audio"

    voll = "Ist Avatari DSGVO-konform?"
    vorher_aufrufe = len(gesehen)
    assert verweis_umschreiben(modell, voll, verlauf) == voll
    assert len(gesehen) == vorher_aufrufe

    liste = formulierungen(modell, FRAGE, ALT, verlauf)
    assert liste == [FRAGE, ANDERE]
    assert kern.formen(kennung, liste) == 2
    assert kern.finden(ANDERE)["id"] == kennung
    assert kern.laden(kennung)["frage"] == FRAGE

    vorher = len(einbettung.aufrufe)
    text = neu(modell, FRAGE, ALT, "Bitte kürzer.")
    assert text == NEU
    assert len(einbettung.aufrufe) == vorher
    assert kern.umschreiben(kennung, text) is True
    assert len(einbettung.aufrufe) == vorher
    assert kern.anhang_lesen(kennung, "audio") is None
    danach = kern.finden(FRAGE)
    assert danach is not None
    assert danach["antwort"] == NEU
    assert danach["id"] == kennung
    assert "anhaenge" not in danach
    assert kern.laden(kennung)["bewertung"] == "gut"
