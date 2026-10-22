"""Gute Treffer bleiben sichtbar, wenn nähere unbewertete Zeilen das Fenster füllen."""

import json
import math
import urllib.request

from mini_ki import MiniKI
from mini_ki.api import Api, dienen

NAH = [1.0, 0.0, 0.0, 0.0]
FERN = [0.0, 1.0, 0.0, 0.0]
GUT_ANTWORT = "Die gute Antwort."


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


def richtung(kosinus: float) -> list[float]:
    rest = math.sqrt(1.0 - kosinus * kosinus)
    return [kosinus, rest, 0.0, 0.0]


def _kern(tmp_path, name: str, vektoren: dict[str, list[float]]) -> MiniKI:
    return MiniKI(tmp_path / name, FesteEinbettung(vektoren))


def _post(url: str, daten: dict) -> tuple[int, dict]:
    inhalt = json.dumps(daten, ensure_ascii=False).encode("utf-8")
    anfrage = urllib.request.Request(url, data=inhalt, method="POST")
    anfrage.add_header("Content-Type", "application/json")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(anfrage, timeout=5) as antwort:
        koerper = json.loads(antwort.read().decode("utf-8"))
        return antwort.getcode(), koerper


def test_finden_liefert_guten_treffer_hinter_unbewerteten(tmp_path):
    """Zehn sehr nahe unbewertete Einträge, ein guter ab 0,80."""
    grenze = richtung(0.80)
    vektoren = {"suche": NAH, "grenze": grenze}
    for i in range(10):
        vektoren[f"offen {i}"] = NAH
    kern = _kern(tmp_path, "unbewertet.sqlite", vektoren)
    for i in range(10):
        kennung = kern.merken(f"offen {i}", f"Antwort offen {i}.")
        assert kennung is not None
        assert kern.laden(kennung)["bewertung"] is None
    gut = kern.merken("grenze", GUT_ANTWORT)
    assert kern.finden("suche") is None
    assert kern.bewerten(gut, "gut") is True
    treffer = kern.finden("suche")
    assert treffer is not None
    assert treffer["id"] == gut
    assert treffer["antwort"] == GUT_ANTWORT
    assert treffer["aehnlichkeit"] == 0.8


def test_finden_liefert_guten_treffer_hinter_schlechten(tmp_path):
    """Zehn sehr nahe schlechte Einträge verdecken den guten nicht."""
    grenze = richtung(0.80)
    vektoren = {"suche": NAH, "grenze": grenze}
    for i in range(10):
        vektoren[f"schlecht {i}"] = NAH
    kern = _kern(tmp_path, "schlecht.sqlite", vektoren)
    for i in range(10):
        assert kern.merken(
            f"schlecht {i}",
            f"Antwort schlecht {i}.",
            bewertung="schlecht",
        )
    gut = kern.merken("grenze", GUT_ANTWORT, bewertung="gut")
    treffer = kern.finden("suche")
    assert treffer is not None
    assert treffer["id"] == gut
    assert treffer["aehnlichkeit"] == 0.8


def test_finden_liefert_gute_formulierung_hinter_unbewerteten(tmp_path):
    """Dieselbe Verdrängung in `frage_vec`, nicht nur im Altfall."""
    grenze = richtung(0.80)
    vektoren = {
        "suche": NAH,
        "gut-start": FERN,
        "gut-form": grenze,
    }
    for i in range(10):
        vektoren[f"offen {i}"] = FERN
        vektoren[f"form {i}"] = NAH
    kern = _kern(tmp_path, "form.sqlite", vektoren)
    for i in range(10):
        kennung = kern.merken(f"offen {i}", f"Antwort offen {i}.")
        assert kern.formen(kennung, [f"form {i}"]) == 1
    gut = kern.merken("gut-start", GUT_ANTWORT, bewertung="gut")
    assert kern.formen(gut, ["gut-form"]) == 1
    treffer = kern.finden("suche")
    assert treffer is not None
    assert treffer["id"] == gut
    assert treffer["antwort"] == GUT_ANTWORT
    assert treffer["aehnlichkeit"] == 0.8


def test_dienst_findet_guten_treffer_hinter_unbewerteten(tmp_path):
    """Dieselbe Suche über die lokale HTTP-API."""
    grenze = richtung(0.80)
    vektoren = {"suche": NAH, "grenze": grenze}
    for i in range(10):
        vektoren[f"offen {i}"] = NAH
    kern = _kern(tmp_path, "dienst.sqlite", vektoren)
    api = Api(kern)
    with dienen(api) as dienst:
        basis = dienst.basis
        for i in range(10):
            status, daten = _post(
                basis + "/v1/eintraege",
                {"frage": f"offen {i}", "antwort": f"Antwort offen {i}."},
            )
            assert status == 201
            assert daten["id"]
        status, angelegt = _post(
            basis + "/v1/eintraege",
            {"frage": "grenze", "antwort": GUT_ANTWORT, "bewertung": "gut"},
        )
        assert status == 201
        status, treffer = _post(
            basis + "/v1/anfragen",
            {"text": "suche", "nur_suchen": True},
        )
    assert status == 200
    assert treffer["id"] == angelegt["id"]
    assert treffer["herkunft"] == "speicher"
    assert treffer["text"] == GUT_ANTWORT
    assert treffer["aehnlichkeit"] == 0.8
