"""Messwerkzeug für die Schwelle. Fake ohne Modell, lokal nur mit Gewichten."""

import csv
import importlib.util
import io
import math
import os
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

_WURZEL = Path(__file__).resolve().parents[1]
_DATEI = _WURZEL / "werkzeuge" / "schwelle.py"
_SPEC = importlib.util.spec_from_file_location("schwelle_werkzeug", _DATEI)
schwelle = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules["schwelle_werkzeug"] = schwelle
_SPEC.loader.exec_module(schwelle)

_SCHLUESSEL = "pruef-schluessel-nicht-loggen"


class _Fest:
    """Kleine Richtungen, damit der Kosinus in der Tabelle feststeht."""

    modell = "fest-einbettung"
    breite = 2

    def vektoren(self, texte: list[str]) -> list[list[float]]:
        tafel = {
            "Pool": [1.0, 0.0],
            "Schwimmbad": [0.8, 0.6],
            "Frühstück": [0.0, 1.0],
        }
        return [list(tafel[text]) for text in texte]


def _paare(tmp_path: Path, zeilen: list[tuple[str, str, str]]) -> Path:
    pfad = tmp_path / "paare.csv"
    with pfad.open("w", encoding="utf-8", newline="") as datei:
        schreiber = csv.writer(datei)
        schreiber.writerow(["art", "links", "rechts"])
        schreiber.writerows(zeilen)
    return pfad


def _lauf(args: list[str]) -> subprocess.CompletedProcess[str]:
    umgebung = os.environ.copy()
    umgebung["PYTHONIOENCODING"] = "utf-8"
    umgebung["PYTHONPATH"] = str(_WURZEL / "src")
    return subprocess.run(
        [sys.executable, str(_DATEI), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=umgebung,
    )


def _aufruf(args: list[str]) -> tuple[int, str, str]:
    ausgabe = io.StringIO()
    fehler = io.StringIO()
    with redirect_stdout(ausgabe), redirect_stderr(fehler):
        code = schwelle.haupt(args)
    return code, ausgabe.getvalue(), fehler.getvalue()


def test_standardliste_enthaelt_die_prototyp_paare():
    paare = schwelle.paare_lesen(schwelle.PAARE)
    nach_art = {(paar.art, paar.links, paar.rechts) for paar in paare}
    assert ("umschreibung", "Pool", "Schwimmbad") in nach_art
    assert ("fremd", "Pool", "Frühstück") in nach_art
    assert ("gefaehrlich", "Frühstück um sieben", "Frühstück um acht") in nach_art
    assert (
        "umschreibung",
        "Wie erreiche ich euch bei Avatari?",
        "Wie erreiche ich Avatari",
    ) in nach_art
    assert ("gefaehrlich", "Guten Morgen.", "Guten Morgen aber, wie geht es dir?") in nach_art
    assert all(paar.art in schwelle.ARTEN for paar in paare)
    assert len(paare) == len(nach_art)


def test_fake_liefert_tabelle():
    paare = [
        schwelle.Paar("umschreibung", "Pool", "Schwimmbad"),
        schwelle.Paar("fremd", "Pool", "Frühstück"),
    ]
    einbettung = _Fest()
    messungen = schwelle.messen(einbettung, paare)
    assert messungen[0].kosinus == pytest.approx(0.8)
    assert messungen[1].kosinus == pytest.approx(0.0)
    text = schwelle.tabelle(messungen, einbettung)
    zeilen = text.splitlines()
    assert zeilen[0] == "Modell: fest-einbettung"
    assert zeilen[1] == "Breite: 2"
    assert zeilen[3].split()[:2] == ["art", "kosinus"]
    assert "0.800" in zeilen[4]
    assert "Pool" in zeilen[4] and "Schwimmbad" in zeilen[4]
    assert zeilen[4].startswith("umschreibung")
    assert "0.000" in zeilen[5]
    assert zeilen[5].startswith("fremd")
    assert text.endswith("\n")


def test_cli_fake_liefert_dieselbe_tabelle():
    ergebnis = _lauf(["--einbettung", "fake"])
    assert ergebnis.returncode == 0
    assert ergebnis.stderr == ""
    paare = schwelle.paare_lesen(schwelle.PAARE)
    einbettung = schwelle.FakeEinbettung()
    erwartet = schwelle.tabelle(schwelle.messen(einbettung, paare), einbettung)
    assert ergebnis.stdout == erwartet
    assert "Modell: fake-einbettung" in ergebnis.stdout
    assert "Pool" in ergebnis.stdout and "Schwimmbad" in ergebnis.stdout
    assert "Frühstück um sieben" in ergebnis.stdout
    daten = [
        zeile
        for zeile in ergebnis.stdout.splitlines()
        if zeile.startswith(schwelle.ARTEN)
    ]
    assert len(daten) == len(paare)


def test_cli_fake_mit_eigener_liste(tmp_path):
    pfad = _paare(tmp_path, [("umschreibung", "Pool", "Schwimmbad")])
    ergebnis = _lauf(["--paare", str(pfad), "--einbettung", "fake"])
    assert ergebnis.returncode == 0
    assert "Schwimmbad" in ergebnis.stdout
    assert "Frühstück um sieben" not in ergebnis.stdout


def test_jeder_text_wird_einmal_eingebettet():
    class Zaehler:
        modell = "zaehler"
        breite = 2

        def __init__(self) -> None:
            self.texte: list[list[str]] = []

        def vektoren(self, texte: list[str]) -> list[list[float]]:
            self.texte.append(list(texte))
            return [[1.0, 0.0] if text == "Pool" else [0.0, 1.0] for text in texte]

    einbettung = Zaehler()
    paare = [
        schwelle.Paar("fremd", "Pool", "Frühstück"),
        schwelle.Paar("umschreibung", "Frühstück", "Pool"),
    ]
    messungen = schwelle.messen(einbettung, paare)
    assert einbettung.texte == [["Pool", "Frühstück"]]
    assert messungen[0].kosinus == pytest.approx(0.0)
    assert messungen[1].kosinus == pytest.approx(messungen[0].kosinus)


def test_leere_zeile_und_raender(tmp_path):
    pfad = tmp_path / "paare.csv"
    pfad.write_text(
        "art,links,rechts\n\n umschreibung , Pool , Schwimmbad \n",
        encoding="utf-8",
    )
    paare = schwelle.paare_lesen(pfad)
    assert paare == [schwelle.Paar("umschreibung", "Pool", "Schwimmbad")]


def test_paarliste_weist_kaputte_zeilen_ab(tmp_path):
    leer = tmp_path / "leer.csv"
    leer.write_text("", encoding="utf-8")
    with pytest.raises(schwelle.PaarFehler, match="Spalten"):
        schwelle.paare_lesen(leer)
    with pytest.raises(schwelle.PaarFehler, match="fehlt"):
        schwelle.paare_lesen(tmp_path / "fehlt.csv")
    with pytest.raises(schwelle.PaarFehler, match="Datei"):
        schwelle.paare_lesen(tmp_path)
    kaputt = tmp_path / "kaputt.csv"
    kaputt.write_bytes("art,links,rechts\n".encode("latin-1") + "ü".encode("latin-1"))
    with pytest.raises(schwelle.PaarFehler, match="UTF-8"):
        schwelle.paare_lesen(kaputt)
    nur_kopf = _paare(tmp_path, [])
    with pytest.raises(schwelle.PaarFehler, match="kein Paar"):
        schwelle.paare_lesen(nur_kopf)
    halb = tmp_path / "halb.csv"
    halb.write_text("art,links,rechts\ngefaehrlich,nur links,\n", encoding="utf-8")
    with pytest.raises(schwelle.PaarFehler, match="unvollständig"):
        schwelle.paare_lesen(halb)
    art = tmp_path / "art.csv"
    art.write_text("art,links,rechts\nsonst,Pool,Schwimmbad\n", encoding="utf-8")
    with pytest.raises(schwelle.PaarFehler, match="unbekannte Art"):
        schwelle.paare_lesen(art)
    selbst = tmp_path / "selbst.csv"
    selbst.write_text("art,links,rechts\nfremd,Pool,Pool\n", encoding="utf-8")
    with pytest.raises(schwelle.PaarFehler, match="mit sich"):
        schwelle.paare_lesen(selbst)


def test_vektor_ohne_zahl_oder_mit_falscher_form():
    paare = [schwelle.Paar("fremd", "Pool", "Frühstück")]

    class Zuwenig:
        modell = "zuwenig"
        breite = 2

        def vektoren(self, texte):
            return [[1.0, 0.0]]

    with pytest.raises(ValueError, match="einen Vektor pro Text"):
        schwelle.messen(Zuwenig(), paare)

    class Schmal:
        modell = "schmal"
        breite = 2

        def vektoren(self, texte):
            return [[1.0], [1.0]]

    with pytest.raises(ValueError, match="Breite"):
        schwelle.messen(Schmal(), paare)

    class Null:
        modell = "null"
        breite = 2

        def vektoren(self, texte):
            return [[0.0, 0.0], [1.0, 0.0]]

    with pytest.raises(ValueError, match="Länge null"):
        schwelle.messen(Null(), paare)

    class Unendlich:
        modell = "unendlich"
        breite = 1

        def vektoren(self, texte):
            return [[math.nan], [1.0]]

    with pytest.raises(ValueError, match="endliche Zahl"):
        schwelle.messen(Unendlich(), paare)

    with pytest.raises(ValueError, match="kein Paar"):
        schwelle.messen(_Fest(), [])


def test_lokal_laedt_die_gewichte_nicht_beim_bauen(tmp_path, monkeypatch):
    def oeffnen(modell, cache):
        raise AssertionError((modell, cache))

    monkeypatch.setattr("mini_ki.einbettung_lokal._fastembed_oeffnen", oeffnen)
    einbettung = schwelle.lokal_einbettung(tmp_path / "cache")
    assert einbettung.modell.endswith("paraphrase-multilingual-MiniLM-L12-v2")
    assert einbettung.breite == 384
    assert einbettung.vektoren([]) == []


def test_api_bleibt_offline_und_verbirgt_den_schluessel():
    einbettung = schwelle.api_einbettung(
        "http://127.0.0.1:9/v1",
        "pruef-modell",
        _SCHLUESSEL,
        4,
        wartezeit=1.0,
    )
    assert einbettung.modell == "pruef-modell"
    assert einbettung.breite == 4
    assert _SCHLUESSEL not in repr(einbettung)


def test_cli_ohne_einbettung_und_ohne_cache():
    code, ausgabe, fehler = _aufruf([])
    assert code == 2
    assert ausgabe == ""
    assert "einbettung" in fehler
    code, ausgabe, fehler = _aufruf(["--einbettung", "lokal"])
    assert code == 1
    assert ausgabe == ""
    assert "--cache" in fehler
    code, ausgabe, fehler = _aufruf(
        ["--einbettung", "api", "--schluessel", _SCHLUESSEL]
    )
    assert code == 1
    assert _SCHLUESSEL not in fehler
    assert _SCHLUESSEL not in ausgabe
    assert "--adresse" in fehler


def test_hilfe_nennt_den_kosinus():
    code, ausgabe, fehler = _aufruf(["--help"])
    assert code == 0
    assert fehler == ""
    assert "Kosinus" in ausgabe
    assert "fake" in ausgabe and "lokal" in ausgabe and "api" in ausgabe


def test_cli_lokal_ohne_fastembed_meldet_das_extra(tmp_path):
    if importlib.util.find_spec("fastembed") is not None:
        pytest.skip("fastembed ist installiert, der Fehlerpfad gilt ohne das Extra.")
    ergebnis = _lauf(
        ["--einbettung", "lokal", "--cache", str(tmp_path / "cache")]
    )
    assert ergebnis.returncode == 1
    assert ergebnis.stdout == ""
    assert "fastembed" in ergebnis.stderr
    assert "Traceback" not in ergebnis.stderr


def test_cli_api_schreibt_den_schluessel_nicht(tmp_path):
    pfad = _paare(tmp_path, [("umschreibung", "Pool", "Schwimmbad")])
    ergebnis = _lauf(
        [
            "--paare",
            str(pfad),
            "--einbettung",
            "api",
            "--adresse",
            "http://127.0.0.1:9/v1",
            "--modell",
            "pruef-modell",
            "--breite",
            "4",
            "--schluessel",
            _SCHLUESSEL,
            "--wartezeit",
            "1",
        ]
    )
    assert ergebnis.returncode == 1
    assert _SCHLUESSEL not in ergebnis.stdout
    assert _SCHLUESSEL not in ergebnis.stderr
    assert "Traceback" not in ergebnis.stderr


@pytest.mark.modell
def test_lokales_modell_trifft_den_prototyp(tmp_path):
    """Pool gegen Schwimmbad liegt wie im Prototyp bei etwa 0,80."""
    pytest.importorskip("fastembed")
    einbettung = schwelle.lokal_einbettung(tmp_path / "cache")
    paare = schwelle.paare_lesen(schwelle.PAARE)
    messungen = schwelle.messen(einbettung, paare)
    text = schwelle.tabelle(messungen, einbettung)
    werte = {(messung.links, messung.rechts): messung.kosinus for messung in messungen}
    assert werte[("Pool", "Schwimmbad")] == pytest.approx(0.804, abs=0.02)
    assert werte[("Pool", "Schwimmbad")] >= 0.80
    assert f"{werte[('Pool', 'Schwimmbad')]:.3f}" in text
    assert werte[("Pool", "Frühstück")] == pytest.approx(0.357, abs=0.02)
    assert werte[("Frühstück um sieben", "Frühstück um acht")] == pytest.approx(
        0.854, abs=0.02
    )
    assert werte[("Guten Morgen.", "Guten Morgen")] == pytest.approx(0.981, abs=0.02)
    assert werte[("Guten Morgen.", "Guten Morgen!")] == pytest.approx(0.987, abs=0.02)
    assert werte[("Guten Morgen.", "Guten Morgen aber, wie geht es dir?")] == pytest.approx(
        0.845, abs=0.02
    )
    assert werte[("Guten Morgen.", "Morgen.")] == pytest.approx(0.825, abs=0.02)
    assert werte[("Hallo Ava.", "Habuaka.")] == pytest.approx(0.232, abs=0.02)
    assert werte[("Hallo Ava.", "Hallo?")] == pytest.approx(0.757, abs=0.02)
    assert werte[("Hallo Ava.", "Hallo, Aldo.")] == pytest.approx(0.701, abs=0.02)
    assert werte[("Wie erreiche ich euch bei Avatari?", "Wie erreiche ich Avatari")] == pytest.approx(
        0.92, abs=0.02
    )
    assert "paraphrase-multilingual-MiniLM-L12-v2" in text
