"""Daumen runter: neue Antwort wird schlecht, Cache-Treffer nur für diese Anfrage."""

import json
import math
import re
import sqlite3
import urllib.error
import urllib.request

import pytest
import sqlite_vec

from mini_ki import MiniKI
from mini_ki.api import Api, dienen

FRAGE_A = "Wo ist das Büro?"
FRAGE_B = "Wie komme ich zum Büro?"
FRAGE_C = "Welcher Weg führt zum Büro?"
FRAGE_D = "Wo finde ich das Büro?"
ANTWORT = "Das Büro ist im ersten Stock."
NEU = "Die neue Antwort nennt den ersten Stock nicht."
ZEIT = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


class FesteEinbettung:
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


def richtung(kosinus: float, achse: int) -> list[float]:
    rest = math.sqrt(1.0 - kosinus * kosinus)
    vektor = [0.0, 0.0, 0.0, 0.0]
    vektor[0] = kosinus
    vektor[achse] = rest
    return vektor


def punkt(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


E0 = [1.0, 0.0, 0.0, 0.0]
NAH_B = richtung(0.85, 1)
NAH_C = richtung(0.85, 2)
NAH_D = richtung(0.85, 3)


def vektoren() -> dict[str, list[float]]:
    return {
        FRAGE_A: E0,
        FRAGE_B: NAH_B,
        FRAGE_C: NAH_C,
        FRAGE_D: NAH_D,
    }


def kern(tmp_path, name: str = "ablehnen.sqlite", **kwargs) -> MiniKI:
    return MiniKI(tmp_path / name, FesteEinbettung(vektoren()), **kwargs)


def pruef_spalte(pfad, eintrag_id: str) -> int:
    with sqlite3.connect(pfad) as conn:
        row = conn.execute(
            "SELECT pruefung, bewertung FROM eintrag WHERE id = ?",
            (eintrag_id,),
        ).fetchone()
    assert row is not None
    return int(row[0])


@pytest.mark.parametrize("herkunft", ["ki", "neu", "fehltreffer"])
def test_neue_antwort_wird_schlecht_und_nie_gefunden(tmp_path, herkunft):
    speicher = kern(tmp_path, f"{herkunft}.sqlite")
    kennung = speicher.merken(FRAGE_A, NEU)
    assert kennung is not None
    assert speicher.finden(FRAGE_A) is None
    ergebnis = speicher.ablehnen(kennung, FRAGE_A, herkunft)
    assert ergebnis is not None
    assert ergebnis["neu_generieren"] is True
    assert ergebnis["id"] == kennung
    assert ergebnis["frage"] == FRAGE_A
    assert ergebnis["herkunft"] == herkunft
    assert ergebnis["pruefung"] is False
    assert speicher.laden(kennung)["bewertung"] == "schlecht"
    assert speicher.finden(FRAGE_A) is None
    assert speicher.ablehnungen() == []
    gut = speicher.merken(FRAGE_B, ANTWORT, bewertung="gut")
    treffer = speicher.finden(FRAGE_A)
    assert treffer is not None
    assert treffer["id"] == gut
    assert treffer["id"] != kennung


def test_cache_treffer_gilt_nur_fuer_diese_anfrage(tmp_path):
    assert punkt(E0, NAH_B) == pytest.approx(0.85)
    assert punkt(E0, NAH_B) < 0.93
    speicher = kern(tmp_path)
    kennung = speicher.merken(FRAGE_A, ANTWORT, bewertung="gut", id="buero")
    assert kennung == "buero"
    assert speicher.finden(FRAGE_B)["id"] == kennung
    ergebnis = speicher.ablehnen(kennung, FRAGE_B, "speicher")
    assert ergebnis == {
        "neu_generieren": True,
        "id": kennung,
        "frage": FRAGE_B,
        "herkunft": "speicher",
        "pruefung": False,
    }
    assert speicher.finden(FRAGE_B) is None
    bleibt = speicher.finden(FRAGE_A)
    assert bleibt is not None
    assert bleibt["id"] == kennung
    assert bleibt["antwort"] == ANTWORT
    assert speicher.laden(kennung)["bewertung"] == "gut"
    assert pruef_spalte(tmp_path / "ablehnen.sqlite", kennung) == 0
    luecken = speicher.ablehnungen()
    assert len(luecken) == 1
    assert luecken[0]["frage"] == FRAGE_B
    assert luecken[0]["eintrag"] == kennung
    assert ZEIT.fullmatch(luecken[0]["zeit"])
    assert luecken[0]["pruefung"] is False
    assert speicher.ablehnungen(kennung) == luecken
    assert speicher.ablehnungen("andere-id") == []


def test_luecken_bleiben_nach_erneutem_oeffnen_und_verschwinden_mit_dem_eintrag(tmp_path):
    pfad = tmp_path / "dauer.sqlite"
    speicher = MiniKI(pfad, FesteEinbettung(vektoren()))
    kennung = speicher.merken(FRAGE_A, ANTWORT, bewertung="gut")
    assert speicher.ablehnen(kennung, "  " + FRAGE_B + "  ", "speicher")["frage"] == FRAGE_B
    del speicher
    neu = MiniKI(pfad, FesteEinbettung(vektoren()))
    assert neu.finden(FRAGE_A)["id"] == kennung
    assert neu.finden(FRAGE_B) is None
    assert neu.laden(kennung)["bewertung"] == "gut"
    assert neu.ablehnungen(kennung)[0]["frage"] == FRAGE_B
    assert neu.vergessen(kennung) is True
    assert neu.ablehnungen() == []
    assert neu.finden(FRAGE_A) is None


def test_drei_ablehnungen_markieren_zur_pruefung(tmp_path):
    assert punkt(NAH_B, NAH_C) == pytest.approx(0.85 * 0.85)
    assert punkt(NAH_B, NAH_C) < 0.93
    speicher = kern(tmp_path, "pruefung.sqlite")
    kennung = speicher.merken(FRAGE_A, ANTWORT, bewertung="gut")
    fragen = (FRAGE_B, FRAGE_C, FRAGE_D)
    for frage in fragen[:2]:
        assert speicher.finden(frage)["id"] == kennung
        ergebnis = speicher.ablehnen(kennung, frage, "speicher")
        assert ergebnis["pruefung"] is False
        assert ergebnis["neu_generieren"] is True
        assert speicher.finden(frage) is None
    assert pruef_spalte(tmp_path / "pruefung.sqlite", kennung) == 0
    assert speicher.finden(FRAGE_D)["id"] == kennung
    dritte = speicher.ablehnen(kennung, FRAGE_D, "speicher")
    assert dritte["pruefung"] is True
    assert speicher.laden(kennung)["bewertung"] == "gut"
    assert speicher.finden(FRAGE_A)["id"] == kennung
    assert speicher.finden(FRAGE_D) is None
    assert pruef_spalte(tmp_path / "pruefung.sqlite", kennung) == 1
    luecken = speicher.ablehnungen(kennung)
    assert [zeile["frage"] for zeile in luecken] == list(fragen)
    assert all(zeile["pruefung"] is True for zeile in luecken)
    assert luecken[0]["zeit"] <= luecken[1]["zeit"] <= luecken[2]["zeit"]
    assert speicher.laden(kennung) is not None


def test_ablehnung_schwelle_ist_einstellung(tmp_path):
    speicher = kern(tmp_path, "eins.sqlite", ablehnung_schwelle=1)
    kennung = speicher.merken(FRAGE_A, ANTWORT, bewertung="gut")
    assert speicher.ablehnen(kennung, FRAGE_B, "speicher")["pruefung"] is True
    assert speicher.laden(kennung)["bewertung"] == "gut"
    assert speicher.finden(FRAGE_A)["id"] == kennung
    assert speicher.finden(FRAGE_B) is None
    with pytest.raises(ValueError):
        kern(tmp_path, "null.sqlite", ablehnung_schwelle=0)
    with pytest.raises(ValueError):
        kern(tmp_path, "wahr.sqlite", ablehnung_schwelle=True)


def test_ungueltige_ablehnung_aendert_nichts(tmp_path):
    speicher = kern(tmp_path)
    kennung = speicher.merken(FRAGE_A, ANTWORT, bewertung="gut")
    assert speicher.ablehnen("", FRAGE_B, "ki") is None
    assert speicher.ablehnen("fehlt", FRAGE_B, "ki") is None
    assert speicher.ablehnen(kennung, FRAGE_B, "woanders") is None
    assert speicher.ablehnen(kennung, FRAGE_B, "") is None
    assert speicher.ablehnen(kennung, FRAGE_B, None) is None
    assert speicher.ablehnen(kennung, "", "speicher") is None
    assert speicher.ablehnen(kennung, "   ", "speicher") is None
    assert speicher.ablehnen(kennung, "ada@example.com", "speicher") is None
    assert speicher.ablehnen("fehlt", FRAGE_B, "speicher") is None
    assert speicher.ablehnungen("") == []
    assert speicher.laden(kennung)["bewertung"] == "gut"
    assert speicher.ablehnungen() == []
    assert speicher.finden(FRAGE_B)["id"] == kennung
    assert speicher.finden(FRAGE_A)["id"] == kennung


def test_alter_speicher_bekommt_pruefung_und_ablehnung(tmp_path):
    """Datei aus dem Stand vor der Tabelle `ablehnung`."""
    pfad = tmp_path / "alt.sqlite"
    with sqlite3.connect(pfad) as conn:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute(
            """
            CREATE TABLE meta (
                schluessel TEXT PRIMARY KEY,
                wert TEXT NOT NULL
            )
            """
        )
        conn.executemany(
            "INSERT INTO meta (schluessel, wert) VALUES (?, ?)",
            (("modell", "test-modell"), ("breite", "4"), ("schema", "1")),
        )
        conn.execute(
            """
            CREATE TABLE eintrag (
                id TEXT PRIMARY KEY,
                frage TEXT NOT NULL,
                antwort TEXT NOT NULL,
                bewertung TEXT,
                art TEXT DEFAULT 'antwort',
                erstellt TEXT DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            INSERT INTO eintrag (id, frage, antwort, bewertung)
            VALUES ('alt-id', ?, ?, 'gut')
            """,
            (FRAGE_A, ANTWORT),
        )
        conn.execute(
            """
            CREATE VIRTUAL TABLE eintrag_vec USING vec0(
                eintrag_id TEXT PRIMARY KEY,
                embedding float[4] distance_metric=cosine
            )
            """
        )
        conn.execute(
            "INSERT INTO eintrag_vec (eintrag_id, embedding) VALUES (?, ?)",
            ("alt-id", sqlite_vec.serialize_float32(E0)),
        )
    speicher = MiniKI(pfad, FesteEinbettung(vektoren()), ablehnung_schwelle=1)
    assert speicher.finden(FRAGE_A)["id"] == "alt-id"
    assert speicher.ablehnen("alt-id", FRAGE_B, "speicher")["pruefung"] is True
    assert speicher.laden("alt-id")["bewertung"] == "gut"
    assert speicher.finden(FRAGE_A)["id"] == "alt-id"
    assert speicher.finden(FRAGE_B) is None
    with sqlite3.connect(pfad) as conn:
        spalten = {row[1] for row in conn.execute("PRAGMA table_info(eintrag)")}
        assert "pruefung" in spalten
        tabellen = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "ablehnung" in tabellen


def _holen(url: str, methode: str, daten=None):
    inhalt = None
    anfrage = urllib.request.Request(url, method=methode)
    if daten is not None:
        inhalt = json.dumps(daten, ensure_ascii=False).encode("utf-8")
        anfrage.data = inhalt
        anfrage.add_header("Content-Type", "application/json")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        antwort = opener.open(anfrage, timeout=5)
    except urllib.error.HTTPError as fehler:
        antwort = fehler
    try:
        roh = antwort.read()
        koepfe = {name: wert for name, wert in antwort.headers.items()}
        typ = ""
        for name, wert in koepfe.items():
            if name.lower() == "content-type":
                typ = wert
        koerper = json.loads(roh.decode("utf-8")) if "application/json" in typ and roh else roh
        return antwort.getcode(), koerper
    finally:
        antwort.close()


def test_dienst_bietet_nach_daumen_runter_eine_neue_antwort(tmp_path):
    """Loopback: Cache-Ablehnung, dann neue KI-Antwort, dann Daumen runter darauf."""
    texte = [
        "Erste Antwort der KI zum Büro.",
        "Zweite Antwort der KI zum Büro.",
    ]

    def ki(frage: str) -> str:
        assert frage == FRAGE_B
        return texte.pop(0)

    speicher = kern(tmp_path, "dienst.sqlite")
    api = Api(speicher, ki=ki)
    with dienen(api) as dienst:
        assert dienst.host == "127.0.0.1"
        basis = dienst.basis
        status, angelegt = _holen(
            basis + "/v1/eintraege",
            "POST",
            {"frage": FRAGE_A, "antwort": ANTWORT, "bewertung": "gut"},
        )
        assert status == 201
        kennung = angelegt["id"]

        status, treffer = _holen(basis + "/v1/anfragen", "POST", {"text": FRAGE_B})
        assert status == 200
        assert treffer["herkunft"] == "speicher"
        assert treffer["id"] == kennung

        status, daumen = _holen(
            f"{basis}/v1/anfragen/{kennung}/bewertung",
            "POST",
            {"bewertung": "schlecht"},
        )
        assert status == 200
        assert daumen == {"ok": True}

        status, neu = _holen(basis + "/v1/anfragen", "POST", {"text": FRAGE_B})
        assert status == 200
        assert neu["herkunft"] == "ki"
        assert neu["text"] == "Erste Antwort der KI zum Büro."
        assert neu["id"] != kennung

        status, bleibt = _holen(basis + "/v1/anfragen", "POST", {"text": FRAGE_A})
        assert bleibt["herkunft"] == "speicher"
        assert bleibt["id"] == kennung
        assert bleibt["text"] == ANTWORT

        status, runter = _holen(
            f"{basis}/v1/anfragen/{neu['id']}/bewertung",
            "POST",
            {"bewertung": "schlecht"},
        )
        assert status == 200
        assert runter == {"ok": True}

        status, nochmal = _holen(basis + "/v1/anfragen", "POST", {"text": FRAGE_B})
        assert nochmal["herkunft"] == "ki"
        assert nochmal["text"] == "Zweite Antwort der KI zum Büro."
        assert nochmal["id"] not in {kennung, neu["id"]}

    assert speicher.laden(kennung)["bewertung"] == "gut"
    assert speicher.laden(neu["id"])["bewertung"] == "schlecht"
    assert speicher.finden(FRAGE_A)["id"] == kennung
    assert speicher.finden(FRAGE_B) is None
    luecken = speicher.ablehnungen()
    assert luecken == [
        {
            "frage": FRAGE_B,
            "eintrag": kennung,
            "zeit": luecken[0]["zeit"],
            "pruefung": False,
        }
    ]
    assert ZEIT.fullmatch(luecken[0]["zeit"])
