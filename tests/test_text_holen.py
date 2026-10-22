"""Text aus TXT, Markdown, PDF, DOCX und EPUB.

Ohne pypdf oder python-docx werden nur die Tests übersprungen, die das
Paket brauchen. TXT, Markdown, EPUB und die Typprüfung laufen immer.
"""

import importlib
import zipfile
from pathlib import Path

import pytest

from mini_ki.text_holen import Dateityp, KeinText, text_holen
from mini_ki.wissen import Wissensspeicher

DATEN = Path(__file__).parent / "daten"
E0 = [1.0, 0.0, 0.0, 0.0]


class FesteEinbettung:
    modell = "test-modell"
    breite = 4

    def __init__(self, vektoren: dict[str, list[float]]):
        self._vektoren = vektoren

    def vektoren(self, texte: list[str]) -> list[list[float]]:
        return [list(self._vektoren.get(text, E0)) for text in texte]


def _braucht(modul: str) -> None:
    try:
        importlib.import_module(modul)
    except ImportError:
        paket = "python-docx" if modul == "docx" else modul
        pytest.skip(f"optionale Abhängigkeit dokumente ({paket}) fehlt")


def test_txt_absatz_und_umlaute():
    assert text_holen(DATEN / "gruss.txt") == [
        ("", "Hallo aus der Textdatei."),
        ("", "Äöü und Größe bleiben."),
    ]


def test_txt_cp1252():
    roh = (DATEN / "groesse.txt").read_bytes()
    with pytest.raises(UnicodeDecodeError):
        roh.decode("utf-8")
    assert text_holen(DATEN / "groesse.txt") == [("", "Die Größe bleibt.")]


def test_txt_raute_ist_keine_stelle(tmp_path):
    datei = tmp_path / "roh.txt"
    datei.write_text("# Keine Stelle\n\nWeiter äöü.\n", encoding="utf-8")
    assert text_holen(datei) == [("", "# Keine Stelle"), ("", "Weiter äöü.")]


def test_utf8_bom(tmp_path):
    datei = tmp_path / "bom.txt"
    datei.write_bytes(b"\xef\xbb\xbfGr\xc3\xb6\xc3\x9fe\n")
    assert text_holen(datei) == [("", "Größe")]


def test_markdown_ueberschrift_und_umlaute():
    assert text_holen(DATEN / "notiz.md") == [
        ("Über den Berg", "Äpfel und Öl stehen im Tal."),
        ("Zweites Stück", "Die Stachelbeere wächst an der Straße."),
    ]


def test_markdown_setext(tmp_path):
    datei = tmp_path / "alt.md"
    datei.write_text("Kapitel 3\n==========\n\nText der Stelle.\n", encoding="utf-8")
    assert text_holen(datei) == [("Kapitel 3", "Text der Stelle.")]


def test_markdown_codeblock_ist_keine_ueberschrift(tmp_path):
    datei = tmp_path / "code.md"
    datei.write_text("# Echt\n\n```\n# Nicht\n```\n\nDanach.\n", encoding="utf-8")
    assert text_holen(datei) == [("Echt", "# Nicht"), ("Echt", "Danach.")]


def test_epub_spine_und_kapitel():
    assert text_holen(DATEN / "buch.epub") == [
        ("Über den Berg", "Äpfel und Öl stehen im Tal."),
        ("Zweites Stück", "Die Stachelbeere wächst an der Straße."),
    ]


def test_exe_mit_pdf_endung():
    with pytest.raises(Dateityp) as fehler:
        text_holen(DATEN / "falsch.pdf")
    assert str(fehler.value) == "Der Dateityp ist unbekannt."


def test_text_mit_pdf_endung_ist_dateityp(tmp_path):
    datei = tmp_path / "notiz.pdf"
    datei.write_text("Nur Text, kein PDF.\n", encoding="utf-8")
    with pytest.raises(Dateityp):
        text_holen(datei)


def test_fremdes_zip_ist_dateityp(tmp_path):
    datei = tmp_path / "paket.pdf"
    with zipfile.ZipFile(datei, "w") as paket:
        paket.writestr("liesmich.txt", "Hallo")
    with pytest.raises(Dateityp):
        text_holen(datei)


def test_unbekannte_endung(tmp_path):
    datei = tmp_path / "notiz.bin"
    datei.write_text("Nur Text.\n", encoding="utf-8")
    with pytest.raises(Dateityp):
        text_holen(datei)


def test_markdown_landet_im_wissensspeicher(tmp_path):
    teile = text_holen(DATEN / "notiz.md")
    wissen = Wissensspeicher(tmp_path / "wissen.sqlite", FesteEinbettung({}))
    datei = DATEN / "notiz.md"
    kennung = wissen.dokument_anlegen(datei.name, "text/markdown", datei.stat().st_size)
    assert wissen.abschnitte_ablegen(
        kennung,
        [
            {"nr": index + 1, "stelle": stelle, "text": text}
            for index, (stelle, text) in enumerate(teile)
        ],
    ) == len(teile)
    treffer = wissen.suchen("Stachelbeere")
    assert treffer
    assert treffer[0]["stelle"] == "Zweites Stück"
    assert treffer[0]["text"] == "Die Stachelbeere wächst an der Straße."
    fund = next(eintrag for eintrag in wissen.suchen("Öl") if "Öl" in eintrag["text"])
    assert fund["stelle"] == "Über den Berg"
    assert fund["text"] == "Äpfel und Öl stehen im Tal."


@pytest.mark.dokumente
def test_docx_absatz_und_ueberschrift():
    _braucht("docx")
    assert text_holen(DATEN / "brief.docx") == [
        ("", "Vor dem Kapitel."),
        ("Grüße", "Äpfel, Öl und Straße."),
        ("Zweites", "Noch ein Satz mit Größe."),
    ]


@pytest.mark.dokumente
def test_docx_trotz_pdf_endung(tmp_path):
    _braucht("docx")
    datei = tmp_path / "brief.pdf"
    datei.write_bytes((DATEN / "brief.docx").read_bytes())
    assert text_holen(datei)[1] == ("Grüße", "Äpfel, Öl und Straße.")


@pytest.mark.dokumente
def test_pdf_seiten():
    _braucht("pypdf")
    assert text_holen(DATEN / "seite.pdf") == [
        ("S. 1", "Hallo vom Blatt."),
        ("S. 2", "Die Größe bleibt."),
    ]


@pytest.mark.dokumente
def test_pdf_ohne_text():
    _braucht("pypdf")
    with pytest.raises(KeinText) as fehler:
        text_holen(DATEN / "scan.pdf")
    assert str(fehler.value) == "Kein Text gefunden (Scan?)"


@pytest.mark.dokumente
def test_pdf_trotz_txt_endung(tmp_path):
    _braucht("pypdf")
    datei = tmp_path / "seite.txt"
    datei.write_bytes((DATEN / "seite.pdf").read_bytes())
    assert text_holen(datei)[0] == ("S. 1", "Hallo vom Blatt.")
