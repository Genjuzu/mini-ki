import math
import sqlite3

import pytest
import sqlite_vec

from mini_ki import MiniKI, ModellPasstNicht

E0 = [1.0, 0.0, 0.0, 0.0]
E1 = [0.0, 1.0, 0.0, 0.0]
E2 = [0.0, 0.0, 1.0, 0.0]
E3 = [0.0, 0.0, 0.0, 1.0]


class FesteEinbettung:
    """Wörterbuch Text → Vektor. Breite folgt aus den Vektoren."""

    def __init__(
        self,
        vektoren: dict[str, list[float]],
        modell: str = "test-modell",
    ) -> None:
        breiten = {len(vektor) for vektor in vektoren.values()}
        if len(breiten) != 1:
            raise ValueError("Alle Vektoren brauchen dieselbe Breite.")
        self.modell = modell
        self.breite = breiten.pop()
        self._vektoren = dict(vektoren)
        self.aufrufe: list[list[str]] = []

    def vektoren(self, texte: list[str]) -> list[list[float]]:
        self.aufrufe.append(list(texte))
        fehlend = [text for text in texte if text not in self._vektoren]
        if fehlend:
            raise KeyError(fehlend[0])
        return [list(self._vektoren[text]) for text in texte]


class AndereEinbettung:
    def __init__(self, modell: str, breite: int) -> None:
        self.modell = modell
        self.breite = breite

    def vektoren(self, texte: list[str]) -> list[list[float]]:
        raise AssertionError(texte)


def richtung(kosinus: float) -> list[float]:
    rest = math.sqrt(1.0 - kosinus * kosinus)
    return [kosinus, rest, 0.0, 0.0]


def nahe_an(basis_kosinus: float, abstand_kosinus: float) -> list[float]:
    theta = math.acos(basis_kosinus)
    delta = math.acos(abstand_kosinus)
    phi = theta - delta
    return [math.cos(phi), math.sin(phi), 0.0, 0.0]


def punkt(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def verbinden(pfad):
    conn = sqlite3.connect(pfad)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def test_nur_gut_wird_gefunden(tmp_path):
    vektoren = {
        "frage gut": E0,
        "frage offen": E0,
        "frage schlecht": E0,
        "suche": E0,
    }
    kern = MiniKI(tmp_path / "gut.sqlite", FesteEinbettung(vektoren))
    assert kern.finden("suche") is None
    offen = kern.merken("frage offen", "Antwort offen")
    schlecht = kern.merken("frage schlecht", "Antwort schlecht")
    gut = kern.merken("frage gut", "Antwort gut", id="gut-id")
    assert offen is not None
    assert schlecht is not None
    assert gut == "gut-id"
    assert kern.bewerten(schlecht, "schlecht") is True
    assert kern.bewerten("fehlt", "gut") is False
    assert kern.bewerten(gut, "mittel") is False
    assert kern.finden("suche") is None
    assert kern.bewerten(gut, "gut") is True
    treffer = kern.finden("suche")
    assert treffer is not None
    assert set(treffer) == {"id", "antwort", "aehnlichkeit"}
    assert treffer["id"] == "gut-id"
    assert treffer["antwort"] == "Antwort gut"
    assert treffer["aehnlichkeit"] == 1.0
    assert kern.laden(offen)["bewertung"] is None
    assert kern.laden(schlecht)["bewertung"] == "schlecht"


def test_schwelle_achtzig(tmp_path):
    vektoren = {
        "frage": E0,
        "gleich": E0,
        "grenze": richtung(0.80),
        "darunter": richtung(0.79),
    }
    pfad = tmp_path / "schwelle.sqlite"
    einbettung = FesteEinbettung(vektoren)
    kern = MiniKI(pfad, einbettung)
    kennung = kern.merken("frage", "Antwort zur Schwelle.", bewertung="gut")
    assert kern.finden("gleich")["aehnlichkeit"] == 1.0
    grenze = kern.finden("grenze")
    assert grenze is not None
    assert grenze["id"] == kennung
    assert grenze["aehnlichkeit"] == 0.8
    assert kern.finden("darunter") is None
    eng = MiniKI(pfad, einbettung, schwelle=0.90)
    assert eng.finden("grenze") is None
    assert eng.finden("gleich")["id"] == kennung


def test_gegenbeispiel_sperrt_nur_die_nahe_frage(tmp_path):
    original_vektor = E0
    gegen_vektor = richtung(0.85)
    nahe_vektor = nahe_an(0.85, 0.95)
    assert punkt(original_vektor, gegen_vektor) == pytest.approx(0.85)
    assert punkt(nahe_vektor, gegen_vektor) == pytest.approx(0.95)
    assert punkt(nahe_vektor, original_vektor) >= 0.80
    vektoren = {
        "original": original_vektor,
        "gegen": gegen_vektor,
        "nahe": nahe_vektor,
    }
    kern = MiniKI(tmp_path / "gegen.sqlite", FesteEinbettung(vektoren))
    kennung = kern.merken("original", "Die passende Antwort.", id="original-id")
    assert kennung == "original-id"
    kern.bewerten(kennung, "gut")
    assert kern.finden("nahe")["id"] == kennung
    assert kern.finden("gegen")["id"] == kennung
    assert kern.gesperrte_ids("") == set()
    assert kern.gesperrte_ids("ada@example.com") == set()
    assert kern.trennen("", kennung) is False
    assert kern.trennen("ada@example.com", kennung) is False
    assert kern.trennen("gegen", kennung) is True
    assert kern.gesperrte_ids("nahe") == {kennung}
    assert kern.gesperrte_ids("gegen") == {kennung}
    assert kern.gesperrte_ids("original") == set()
    assert kern.finden("nahe") is None
    assert kern.finden("gegen") is None
    treffer = kern.finden("original")
    assert treffer is not None
    assert treffer["id"] == kennung
    assert treffer["aehnlichkeit"] == 1.0


def test_gesperrter_treffer_gibt_den_naechsten_frei(tmp_path):
    vektoren = {
        "haupt": E0,
        "zweit": richtung(0.85),
    }
    kern = MiniKI(tmp_path / "naechster.sqlite", FesteEinbettung(vektoren))
    haupt = kern.merken("haupt", "Antwort eins.", bewertung="gut")
    zweit = kern.merken("zweit", "Antwort zwei.", bewertung="gut")
    assert kern.finden("haupt")["id"] == haupt
    assert kern.trennen("haupt", haupt) is True
    treffer = kern.finden("haupt")
    assert treffer is not None
    assert treffer["id"] == zweit
    assert treffer["antwort"] == "Antwort zwei."


def test_umschreiben_auf_schlecht_bleibt(tmp_path):
    kern = MiniKI(tmp_path / "stift.sqlite", FesteEinbettung({"Frage": E0}))
    kennung = kern.merken("Frage", "Erste Fassung der Antwort.")
    assert kern.umschreiben(kennung, "   ") is False
    assert kern.umschreiben(kennung, "Zweite Fassung der Antwort.") is True
    assert kern.laden(kennung)["antwort"] == "Zweite Fassung der Antwort."
    assert kern.laden(kennung)["bewertung"] is None
    assert kern.bewerten(kennung, "gut") is True
    assert kern.umschreiben(kennung, "Dritte Fassung der Antwort.") is True
    treffer = kern.finden("Frage")
    assert treffer["antwort"] == "Dritte Fassung der Antwort."
    assert treffer["aehnlichkeit"] == 1.0
    assert kern.umschreiben(kennung, "Bitte an ada@example.com schreiben.") is False
    assert kern.laden(kennung)["antwort"] == "Dritte Fassung der Antwort."
    assert kern.bewerten(kennung, "schlecht") is True
    assert kern.umschreiben(kennung, "Vierte Fassung der Antwort.") is False
    assert kern.laden(kennung)["antwort"] == "Dritte Fassung der Antwort."
    assert kern.laden(kennung)["bewertung"] == "schlecht"
    assert kern.finden("Frage") is None
    assert kern.laden("") is None
    assert kern.laden("fehlt") is None


def test_formen_entfernt_dubletten_und_gesperrtes(tmp_path):
    vektoren = {
        "Startfrage": E0,
        "Nebenfrage": E3,
        "Alpha Frage": E1,
        "Andere Formulierung": E2,
    }
    einbettung = FesteEinbettung(vektoren)
    kern = MiniKI(tmp_path / "formen.sqlite", einbettung)
    haupt = kern.merken(
        "Startfrage",
        "Die lange Antwort zum Frühstück.",
        bewertung="gut",
    )
    neben = kern.merken(
        "Nebenfrage",
        "Eine andere Antwort zum Pool.",
        bewertung="gut",
    )
    assert kern.finden("Startfrage")["id"] == haupt
    assert kern.formen("fehlt", ["Alpha Frage"]) == 0
    vorher = len(einbettung.aufrufe)
    anzahl = kern.formen(
        haupt,
        [
            "Alpha Frage",
            "alpha frage",
            "Alpha   Frage",
            "Andere Formulierung",
            "nutzer@example.com",
            "+49 151 23456789",
            "DE89370400440532013000",
            "",
            "   ",
        ],
    )
    assert anzahl == 2
    assert einbettung.aufrufe[vorher:] == [["Alpha Frage", "Andere Formulierung"]]
    assert kern.laden(haupt)["frage"] == "Alpha Frage"
    assert kern.finden("Startfrage") is None
    assert kern.finden("Alpha Frage")["id"] == haupt
    assert kern.finden("Andere Formulierung")["id"] == haupt
    assert kern.finden("Nebenfrage")["id"] == neben
    assert kern.formen(haupt, ["noch@eine.de"]) == 0
    assert kern.finden("Alpha Frage")["id"] == haupt


def test_vergessen_loescht_formulierungen_und_vektoren(tmp_path):
    vektoren = {
        "Startfrage": E0,
        "Nebenfrage": E3,
        "Alpha Frage": E1,
        "Andere Formulierung": E2,
    }
    pfad = tmp_path / "weg.sqlite"
    kern = MiniKI(pfad, FesteEinbettung(vektoren))
    haupt = kern.merken("Startfrage", "Antwort zum Löschen.", bewertung="gut")
    neben = kern.merken("Nebenfrage", "Antwort bleibt.", bewertung="gut")
    assert (
        kern.formen(haupt, ["Alpha Frage", "alpha frage", "Andere Formulierung"]) == 2
    )
    assert kern.finden("Alpha Frage")["id"] == haupt
    assert kern.vergessen("") is False
    assert kern.vergessen(haupt) is True
    assert kern.laden(haupt) is None
    assert kern.finden("Alpha Frage") is None
    assert kern.finden("Andere Formulierung") is None
    assert kern.finden("Startfrage") is None
    assert kern.finden("Nebenfrage")["id"] == neben
    assert kern.vergessen(haupt) is False
    conn = verbinden(pfad)
    try:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM frage WHERE eintrag_id = ?",
                (haupt,),
            ).fetchone()[0]
            == 0
        )
        assert conn.execute("SELECT COUNT(*) FROM frage_vec").fetchone()[0] == 0
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM eintrag_vec WHERE eintrag_id = ?",
                (haupt,),
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM eintrag_vec WHERE eintrag_id = ?",
                (neben,),
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM eintrag WHERE id = ?", (haupt,)).fetchone()[
                0
            ]
            == 0
        )
    finally:
        conn.close()


def test_gleiche_antwort(tmp_path):
    gemeinsam = [f"wort{i:02d}" for i in range(13)]
    nur_a = [f"alpha{i}" for i in range(4)]
    nur_b = [f"beta{i}" for i in range(3)]
    antwort_a = " ".join(gemeinsam + nur_a)
    antwort_b = " ".join(gemeinsam + nur_b)
    assert len(antwort_a) >= 40
    assert len(antwort_b) >= 40
    woerter_a = set(antwort_a.split())
    woerter_b = set(antwort_b.split())
    assert len(woerter_a & woerter_b) / len(woerter_a | woerter_b) == pytest.approx(0.65)

    unten = [f"feld{i:02d}" for i in range(12)]
    nur_c = [f"gamma{i}" for i in range(5)]
    nur_d = [f"delta{i}" for i in range(5)]
    antwort_c = " ".join(unten + nur_c)
    antwort_d = " ".join(unten + nur_d)
    assert len(antwort_d) >= 40
    woerter_c = set(antwort_c.split())
    woerter_d = set(antwort_d.split())
    unter = len(woerter_c & woerter_d) / len(woerter_c | woerter_d)
    assert unter < 0.65

    kurz = "Kurze Antwort ohne Treffer heute."
    assert len(" ".join(kurz.split()).casefold()) < 40

    vektoren = {
        "frage offen": E0,
        "frage schlecht": E1,
        "frage a": E2,
        "frage b": E3,
        "frage kurz": E0,
        "frage c": E1,
    }
    pfad = tmp_path / "gleich.sqlite"
    einbettung = FesteEinbettung(vektoren)
    kern = MiniKI(pfad, einbettung)
    kern.merken("frage offen", antwort_a)
    schlecht = kern.merken("frage schlecht", antwort_a)
    kern.bewerten(schlecht, "schlecht")
    assert kern.gleiche_antwort(antwort_a) is None

    id_a = kern.merken("frage a", antwort_a)
    kern.bewerten(id_a, "gut")
    assert kern.gleiche_antwort(antwort_a) == id_a
    assert kern.gleiche_antwort(antwort_a.swapcase()) == id_a
    assert kern.gleiche_antwort("  " + antwort_a.replace(" ", "   ")) == id_a

    id_b = kern.merken("frage b", antwort_b)
    kern.bewerten(id_b, "gut")
    assert kern.gleiche_antwort(antwort_a, ueberspringen={id_a}) == id_b
    assert kern.gleiche_antwort(antwort_a, ueberspringen={id_a, id_b}) is None

    id_kurz = kern.merken("frage kurz", kurz)
    kern.bewerten(id_kurz, "gut")
    assert kern.gleiche_antwort(kurz) is None

    kern.merken("frage c", antwort_c, bewertung="gut")
    assert kern.gleiche_antwort(antwort_d) is None

    mit_mail = antwort_a + " ada@example.com"
    assert len(mit_mail) >= 40
    assert kern.gleiche_antwort(mit_mail) is None

    eng = MiniKI(pfad, einbettung, gleich_schwelle=0.99)
    assert eng.gleiche_antwort(antwort_a) == id_a
    assert eng.gleiche_antwort(antwort_a, ueberspringen={id_a}) is None


def test_sperre_blockiert_merken(tmp_path):
    pfad = tmp_path / "sperre.sqlite"
    einbettung = FesteEinbettung({"Wie erreiche ich Avatari?": E0})
    kern = MiniKI(pfad, einbettung)
    assert kern.finden("ada@example.com") is None
    assert (
        kern.merken("Wie erreiche ich Avatari?", "+49 151 23456789") is None
    )
    assert (
        kern.merken("Mail an ada@example.com", "Steht im Impressum der Seite.")
        is None
    )
    assert (
        kern.merken("Wie ist die IBAN?", "DE89370400440532013000") is None
    )
    assert (
        kern.merken(
            "Wie erreiche ich Avatari?",
            "Die Kontaktdaten stehen auf der Webseite.",
            bewertung="mittel",
        )
        is None
    )
    with sqlite3.connect(pfad) as conn:
        assert conn.execute("SELECT COUNT(*) FROM eintrag").fetchone()[0] == 0
    kennung = kern.merken(
        "Wie erreiche ich Avatari?",
        "Die Kontaktdaten stehen auf der Webseite.",
    )
    assert kennung is not None
    assert einbettung.aufrufe == [["Wie erreiche ich Avatari?"]]
    with sqlite3.connect(pfad) as conn:
        assert conn.execute("SELECT COUNT(*) FROM eintrag").fetchone()[0] == 1


def test_modell_oder_breite_passt_nicht(tmp_path):
    pfad = tmp_path / "meta.sqlite"
    einbettung = FesteEinbettung({"Frage": E0}, modell="test-modell")
    kern = MiniKI(pfad, einbettung)
    kennung = kern.merken("Frage", "Antwort bleibt.", bewertung="gut")
    with pytest.raises(ModellPasstNicht):
        MiniKI(pfad, AndereEinbettung("anderes-modell", 4))
    with pytest.raises(ModellPasstNicht):
        MiniKI(pfad, AndereEinbettung("test-modell", 8))
    neu = MiniKI(pfad, einbettung)
    assert neu.laden(kennung)["antwort"] == "Antwort bleibt."
    assert neu.finden("Frage")["id"] == kennung

    breit = FesteEinbettung(
        {"Frage": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]},
        modell="test-modell",
    )
    assert breit.breite == 8
    anderer = MiniKI(tmp_path / "acht.sqlite", breit)
    assert anderer.merken("Frage", "Breite acht.", bewertung="gut") is not None


def test_daten_ueberleben_erneutes_oeffnen(tmp_path):
    pfad = tmp_path / "dauer.sqlite"
    einbettung = FesteEinbettung({"Wie geht es dir?": E0})
    kern = MiniKI(pfad, einbettung)
    kennung = kern.merken(
        "Wie geht es dir?",
        "Danke, gut und munter.",
        bewertung="gut",
    )
    del kern
    neu = MiniKI(pfad, einbettung)
    assert neu.laden(kennung) == {
        "frage": "Wie geht es dir?",
        "antwort": "Danke, gut und munter.",
        "bewertung": "gut",
    }
    treffer = neu.finden("Wie geht es dir?")
    assert treffer is not None
    assert treffer["id"] == kennung
    assert treffer["antwort"] == "Danke, gut und munter."
    conn = verbinden(pfad)
    try:
        modus = conn.execute("PRAGMA journal_mode").fetchone()[0]
        meta = dict(conn.execute("SELECT schluessel, wert FROM meta"))
        zeile = conn.execute(
            "SELECT frage, antwort, bewertung, art, erstellt FROM eintrag WHERE id = ?",
            (kennung,),
        ).fetchone()
    finally:
        conn.close()
    assert modus.lower() == "wal"
    assert meta == {"modell": "test-modell", "breite": "4", "schema": "1"}
    assert zeile[0] == "Wie geht es dir?"
    assert zeile[1] == "Danke, gut und munter."
    assert zeile[2] == "gut"
    assert zeile[3] == "antwort"
    assert zeile[4]
