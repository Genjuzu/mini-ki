"""Wissensspeicher. Ablegen, Suche, Löschen, ohne echtes Modell."""

import sqlite3

import pytest
import sqlite_vec

from mini_ki import ModellPasstNicht
from mini_ki.wissen import Wissensspeicher

E0 = [1.0, 0.0, 0.0, 0.0]
E1 = [0.0, 1.0, 0.0, 0.0]
_TABELLEN = ("dokument", "abschnitt", "abschnitt_vec", "abschnitt_fts")


class FesteEinbettung:
    """Text → Vektor. Unbekannter Text bekommt `standard`."""

    def __init__(
        self,
        vektoren: dict[str, list[float]],
        modell: str = "test-modell",
        standard: list[float] | None = None,
    ):
        self._vektoren = dict(vektoren)
        self._standard = list(standard if standard is not None else E0)
        breiten = {len(vektor) for vektor in self._vektoren.values()}
        breiten.add(len(self._standard))
        if len(breiten) != 1:
            raise ValueError("Alle Vektoren brauchen dieselbe Breite.")
        self.modell = modell
        self.breite = breiten.pop()
        self.aufrufe: list[list[str]] = []

    def vektoren(self, texte: list[str]) -> list[list[float]]:
        self.aufrufe.append(list(texte))
        return [list(self._vektoren.get(text, self._standard)) for text in texte]


class AndereEinbettung:
    def __init__(self, modell: str, breite: int) -> None:
        self.modell = modell
        self.breite = breite

    def vektoren(self, texte: list[str]) -> list[list[float]]:
        raise AssertionError(texte)


def verbinden(pfad):
    conn = sqlite3.connect(pfad)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def zaehlen(pfad) -> dict[str, int]:
    conn = verbinden(pfad)
    try:
        return {
            name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            for name in _TABELLEN
        }
    finally:
        conn.close()


def speicher(pfad, vektoren: dict[str, list[float]] | None = None, *, standard=None, **kwargs):
    einbettung = FesteEinbettung(vektoren or {}, standard=standard)
    return Wissensspeicher(pfad, einbettung, **kwargs)


def test_passender_abschnitt_ist_treffer_eins(tmp_path):
    pfad = tmp_path / "mandant" / "wissen.sqlite"
    pumpe = "Pumpe im Keller"
    heizung = "Heizung auf dem Dach"
    wissen = speicher(pfad, {pumpe: E0, heizung: E1})
    kennung = wissen.dokument_anlegen("Handbuch", "text/plain", 120)
    assert wissen.abschnitte_ablegen(
        kennung,
        [
            {"nr": 1, "stelle": "Seite 1", "text": heizung},
            {"nr": 2, "stelle": "Seite 2", "text": pumpe},
        ],
    ) == 2
    treffer = wissen.suchen(pumpe)
    assert treffer[0]["dokument_id"] == kennung
    assert treffer[0]["dokument"] == "Handbuch"
    assert treffer[0]["stelle"] == "Seite 2"
    assert treffer[0]["text"] == pumpe
    assert treffer[0]["aehnlichkeit"] == 1.0
    assert set(treffer[0]) == {
        "dokument_id",
        "dokument",
        "stelle",
        "text",
        "aehnlichkeit",
    }
    assert treffer[1]["text"] == heizung


def test_woertliche_nummer_ueber_fts(tmp_path):
    """24 nähere Abschnitte verdrängen die Nummer aus der Vektor-Rangliste."""
    nummer = "Typenschild ZX-90441"
    pfad = tmp_path / "wissen.sqlite"
    wissen = speicher(pfad, {nummer: E1}, standard=E0)
    kennung = wissen.dokument_anlegen("Schild", "text/plain", 40)
    abschnitte = [
        {"nr": index + 1, "stelle": f"S. {index + 1}", "text": f"Hinweis {index} zum Betrieb"}
        for index in range(24)
    ]
    abschnitte.append({"nr": 25, "stelle": "Schild", "text": nummer})
    assert wissen.abschnitte_ablegen(kennung, abschnitte) == 25
    treffer = wissen.suchen("ZX-90441", anzahl=5)
    fund = next(eintrag for eintrag in treffer if "ZX-90441" in eintrag["text"])
    assert fund["dokument_id"] == kennung
    assert fund["stelle"] == "Schild"
    assert fund["aehnlichkeit"] == 0.0
    assert any(eintrag["aehnlichkeit"] == 1.0 for eintrag in treffer)
    klein = wissen.suchen("zx-90441", anzahl=5)
    assert any("ZX-90441" in eintrag["text"] for eintrag in klein)


def test_dokumente_grenzen_die_suche_ein(tmp_path):
    pfad = tmp_path / "wissen.sqlite"
    text = "Pumpe im Keller"
    wissen = speicher(pfad, {text: E0})
    erste = wissen.dokument_anlegen("Keller", "text/plain", 10)
    zweite = wissen.dokument_anlegen("Dach", "text/plain", 11)
    wissen.abschnitte_ablegen(
        erste, [{"nr": 1, "stelle": "Unten", "text": text}]
    )
    wissen.abschnitte_ablegen(
        zweite, [{"nr": 1, "stelle": "Oben", "text": text}]
    )
    alle = wissen.suchen(text)
    assert {eintrag["dokument_id"] for eintrag in alle} == {erste, zweite}
    nur_erste = wissen.suchen(text, dokumente=[erste])
    assert nur_erste
    assert {eintrag["dokument_id"] for eintrag in nur_erste} == {erste}
    assert nur_erste[0]["stelle"] == "Unten"
    nur_zweite = wissen.suchen(text, dokumente=[zweite])
    assert {eintrag["dokument_id"] for eintrag in nur_zweite} == {zweite}
    assert wissen.suchen(text, dokumente=[]) == []


def test_loeschen_raeumt_alle_tabellen(tmp_path):
    pfad = tmp_path / "wissen.sqlite"
    wissen = speicher(
        pfad,
        {"Alpha einzig QX1": E0, "Beta einzig QX2": E1},
    )
    erste = wissen.dokument_anlegen("Alpha", "text/plain", 3)
    zweite = wissen.dokument_anlegen("Beta", "text/plain", 4)
    wissen.abschnitte_ablegen(
        erste, [{"text": "Alpha einzig QX1", "stelle": "A"}]
    )
    wissen.abschnitte_ablegen(
        zweite, [{"text": "Beta einzig QX2", "stelle": "B"}]
    )
    assert zaehlen(pfad) == {
        "dokument": 2,
        "abschnitt": 2,
        "abschnitt_vec": 2,
        "abschnitt_fts": 2,
    }
    assert wissen.loeschen(erste) is True
    assert wissen.loeschen(erste) is False
    assert wissen.holen(erste) is None
    assert zaehlen(pfad) == {
        "dokument": 1,
        "abschnitt": 1,
        "abschnitt_vec": 1,
        "abschnitt_fts": 1,
    }
    assert all(
        "QX1" not in eintrag["text"] for eintrag in wissen.suchen("QX1")
    )
    rest = wissen.suchen("QX2")
    assert rest[0]["dokument_id"] == zweite
    assert rest[0]["text"] == "Beta einzig QX2"
    assert wissen.loeschen(zweite) is True
    assert zaehlen(pfad) == {
        "dokument": 0,
        "abschnitt": 0,
        "abschnitt_vec": 0,
        "abschnitt_fts": 0,
    }
    assert wissen.liste() == []


def test_anderes_modell_oder_andere_breite_beim_oeffnen(tmp_path):
    pfad = tmp_path / "wissen.sqlite"
    einbettung = FesteEinbettung({"Pumpe im Keller": E0})
    wissen = Wissensspeicher(pfad, einbettung)
    kennung = wissen.dokument_anlegen("Handbuch", "text/plain", 8)
    wissen.abschnitte_ablegen(kennung, [{"text": "Pumpe im Keller"}])
    with pytest.raises(ModellPasstNicht, match="anderes-modell"):
        Wissensspeicher(pfad, AndereEinbettung("anderes-modell", 4))
    with pytest.raises(ModellPasstNicht, match="passt nicht"):
        Wissensspeicher(pfad, AndereEinbettung("test-modell", 8))
    neu = Wissensspeicher(pfad, einbettung)
    assert neu.holen(kennung)["name"] == "Handbuch"
    assert neu.suchen("Pumpe im Keller")[0]["dokument_id"] == kennung
    conn = verbinden(pfad)
    try:
        modus = conn.execute("PRAGMA journal_mode").fetchone()[0]
        meta = dict(conn.execute("SELECT schluessel, wert FROM meta"))
    finally:
        conn.close()
    assert modus.lower() == "wal"
    assert meta == {"modell": "test-modell", "breite": "4", "schema": "1"}

    acht = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    breit = FesteEinbettung({"nur text": acht}, modell="test-modell", standard=acht)
    assert breit.breite == 8
    anderer = Wissensspeicher(tmp_path / "acht.sqlite", breit)
    andere_id = anderer.dokument_anlegen("A", "text/plain", 1)
    assert anderer.abschnitte_ablegen(andere_id, [{"text": "nur text"}]) == 1


def test_abschnitte_in_stapeln(tmp_path):
    pfad = tmp_path / "wissen.sqlite"
    einbettung = FesteEinbettung({})
    wissen = Wissensspeicher(pfad, einbettung, stapelgroesse=2)
    kennung = wissen.dokument_anlegen("Liste", "text/plain", 5)
    texte = [{"text": f"Satz {index}"} for index in range(5)]
    assert wissen.abschnitte_ablegen(kennung, texte) == 5
    assert [len(aufruf) for aufruf in einbettung.aufrufe] == [2, 2, 1]
    assert [text for aufruf in einbettung.aufrufe for text in aufruf] == [
        f"Satz {index}" for index in range(5)
    ]


def test_stapel_bricht_ab_ohne_reste(tmp_path):
    pfad = tmp_path / "wissen.sqlite"

    class Bruch(FesteEinbettung):
        def __init__(self) -> None:
            super().__init__({})
            self._runde = 0

        def vektoren(self, texte: list[str]) -> list[list[float]]:
            self._runde += 1
            if self._runde == 2:
                raise RuntimeError("stapel")
            return super().vektoren(texte)

    einbettung = Bruch()
    wissen = Wissensspeicher(pfad, einbettung, stapelgroesse=2)
    kennung = wissen.dokument_anlegen("Liste", "text/plain", 5)
    with pytest.raises(RuntimeError, match="stapel"):
        wissen.abschnitte_ablegen(
            kennung, [{"text": f"Satz {index}"} for index in range(5)]
        )
    assert zaehlen(pfad)["abschnitt"] == 0
    assert zaehlen(pfad)["abschnitt_vec"] == 0
    assert zaehlen(pfad)["abschnitt_fts"] == 0
    assert wissen.holen(kennung)["status"] == "neu"
    assert wissen.abschnitte_ablegen(kennung, [{"text": "Satz 0"}]) == 1
    assert zaehlen(pfad)["abschnitt"] == 1


def test_status_liste_holen(tmp_path):
    pfad = tmp_path / "wissen.sqlite"
    wissen = speicher(pfad)
    kennung = wissen.dokument_anlegen(" Handbuch ", "text/plain", 15)
    zeile = wissen.holen(kennung)
    assert zeile["name"] == "Handbuch"
    assert zeile["typ"] == "text/plain"
    assert zeile["bytes"] == 15
    assert zeile["status"] == "neu"
    assert zeile["fortschritt"] == 0
    assert zeile["fehler"] is None
    assert zeile["erstellt"]
    assert wissen.status_setzen(kennung, "liest") is True
    assert wissen.holen(kennung)["fortschritt"] == 0
    assert wissen.status_setzen(kennung, "liest", fortschritt=40) is True
    assert wissen.status_setzen(kennung, "fehler", fehler="Datei kaputt") is True
    assert wissen.holen(kennung)["fortschritt"] == 40
    assert wissen.holen(kennung)["fehler"] == "Datei kaputt"
    assert wissen.status_setzen(kennung, "fertig", fortschritt=100, fehler=None) is True
    fertig = wissen.holen(kennung)
    assert fertig["status"] == "fertig"
    assert fertig["fortschritt"] == 100
    assert fertig["fehler"] is None
    assert wissen.liste()[0]["id"] == kennung
    assert wissen.status_setzen("fehlt", "fertig") is False
    assert wissen.holen("fehlt") is None


def test_erneutes_ablegen_ersetzt_abschnitte(tmp_path):
    pfad = tmp_path / "wissen.sqlite"
    wissen = speicher(pfad, {"alt": E0, "neu": E1})
    kennung = wissen.dokument_anlegen("Notiz", "text/plain", 2)
    wissen.abschnitte_ablegen(kennung, [{"text": "alt", "stelle": "1"}])
    wissen.abschnitte_ablegen(
        kennung,
        [
            {"text": "neu", "stelle": "2"},
            {"nr": 3, "text": "noch", "stelle": "3"},
        ],
    )
    assert zaehlen(pfad) == {
        "dokument": 1,
        "abschnitt": 2,
        "abschnitt_vec": 2,
        "abschnitt_fts": 2,
    }
    texte = {eintrag["text"] for eintrag in wissen.suchen("neu", anzahl=5)}
    assert "alt" not in texte
    assert "neu" in texte
    wissen.abschnitte_ablegen(kennung, [])
    assert zaehlen(pfad)["abschnitt"] == 0
    assert zaehlen(pfad)["abschnitt_vec"] == 0
    assert zaehlen(pfad)["abschnitt_fts"] == 0
    assert wissen.holen(kennung)["id"] == kennung


def test_abschnitte_pruefen_vor_dem_einbetten(tmp_path):
    pfad = tmp_path / "wissen.sqlite"
    einbettung = FesteEinbettung({})
    wissen = Wissensspeicher(pfad, einbettung)
    with pytest.raises(ValueError, match="fehlt"):
        wissen.abschnitte_ablegen("fehlt", [{"text": "x"}])
    kennung = wissen.dokument_anlegen("Notiz", "text/plain", 1)
    with pytest.raises(ValueError, match="fehlt"):
        wissen.abschnitte_ablegen(kennung, [{"text": "  "}])
    with pytest.raises(ValueError, match="doppelt"):
        wissen.abschnitte_ablegen(
            kennung,
            [{"nr": 1, "text": "a"}, {"nr": 1, "text": "b"}],
        )
    assert einbettung.aufrufe == []
    assert zaehlen(pfad)["abschnitt"] == 0


def test_ablauf_anlegen_suchen_loeschen(tmp_path):
    """Weg wie ein Aufrufer: anlegen, Status, Abschnitte, Suche, Grenze, Löschen."""
    pfad = tmp_path / "mandant" / "wissen.sqlite"
    pumpe = "Pumpe im Keller"
    wissen = speicher(pfad, {pumpe: E0, "Heizung auf dem Dach": E1})
    kennung = wissen.dokument_anlegen("Handbuch", "text/plain", 80)
    assert wissen.status_setzen(kennung, "liest", fortschritt=20) is True
    assert wissen.abschnitte_ablegen(
        kennung,
        [
            {"nr": 1, "stelle": "Seite 1", "text": "Heizung auf dem Dach"},
            {"nr": 2, "stelle": "Seite 2", "text": pumpe},
        ],
    ) == 2
    assert wissen.status_setzen(kennung, "fertig", fortschritt=100) is True
    assert wissen.holen(kennung)["status"] == "fertig"
    assert wissen.suchen(pumpe)[0]["stelle"] == "Seite 2"
    andere = wissen.dokument_anlegen("Zweites", "text/plain", 8)
    wissen.abschnitte_ablegen(andere, [{"stelle": "Anhang", "text": pumpe}])
    assert {eintrag["dokument_id"] for eintrag in wissen.suchen(pumpe, dokumente=[kennung])} == {
        kennung
    }
    assert wissen.loeschen(andere) is True
    erneut = Wissensspeicher(pfad, FesteEinbettung({pumpe: E0, "Heizung auf dem Dach": E1}))
    assert erneut.suchen("Pumpe im Keller")[0]["dokument_id"] == kennung
    with pytest.raises(ModellPasstNicht):
        Wissensspeicher(pfad, AndereEinbettung("fremdes-modell", 4))
