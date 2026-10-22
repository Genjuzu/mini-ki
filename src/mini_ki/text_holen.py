"""Reinen Text aus einer Datei holen und die Stelle merken.

Rückgabe von `text_holen`: Liste von `(stelle, text)`. Die Stelle ist leer
bei reinem Text, die letzte Überschrift bei Markdown und DOCX, `S. 12`
bei PDF und der Kapiteltitel bei EPUB.

Der Typ folgt den Magic Bytes, nicht der Endung. PDF nutzt `pypdf` (BSD),
DOCX nutzt `python-docx` (MIT), beides die optionale Abhängigkeit
`dokumente`. EPUB bleibt in der Standardbibliothek (`zipfile`,
`html.parser`).
"""

from __future__ import annotations

import importlib
import io
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

__all__ = ["Dateityp", "KeinText", "PaketFehlt", "TextFehler", "text_holen"]

_SCAN = "Kein Text gefunden (Scan?)"
_UNBEKANNT = "Der Dateityp ist unbekannt."
_PAKETE = {"pypdf": "pypdf", "docx": "python-docx"}
_HTML = {"application/xhtml+xml", "text/html", "application/xhtml"}
_HTML_ENDUNG = {"xhtml", "html", "htm"}
_ATX = re.compile(r"^(#{1,6})[ \t]+(.*)$")
_ZAUN = re.compile(r"^(```+|~~~+)")
_THEMA = re.compile(r"([-*_])\1{2,}")


class TextFehler(Exception):
    """Der Text lässt sich nicht herausholen."""

    def __init__(self, meldung: str) -> None:
        self.meldung = meldung
        super().__init__(meldung)


class KeinText(TextFehler):
    """Die Datei enthält keinen lesbaren Text."""

    def __init__(self, meldung: str = "Kein Text gefunden.") -> None:
        super().__init__(meldung)


class Dateityp(TextFehler):
    """Die Datei hat keinen bekannten Typ."""

    def __init__(self, meldung: str = _UNBEKANNT) -> None:
        super().__init__(meldung)


class PaketFehlt(TextFehler):
    """Ein Paket aus der optionalen Abhängigkeit `dokumente` fehlt."""


def text_holen(pfad: str | Path) -> list[tuple[str, str]]:
    """Liest `pfad` und liefert `(stelle, text)` je Teil.

    Beispiele: `("S. 12", "...")` für eine PDF-Seite, `("Kapitel 3", "...")`
    für eine Überschrift oder ein EPUB-Kapitel. Bei `.txt` ist die Stelle leer.
    Ein PDF ohne Text wirft `KeinText` („Kein Text gefunden (Scan?)“).
    Ein unbekannter Inhalt wirft `Dateityp`.
    """
    weg = _pfad(pfad)
    daten = weg.read_bytes()
    art = _erkennen(daten, weg.name)
    if art == "txt":
        return _bloecke(_dekodieren(daten), markdown=False)
    if art == "md":
        return _bloecke(_dekodieren(daten), markdown=True)
    if art == "pdf":
        return _pdf(daten)
    if art == "docx":
        return _docx(daten)
    if art == "epub":
        return _epub(daten)
    raise Dateityp()


def _pfad(pfad: object) -> Path:
    if isinstance(pfad, Path):
        return pfad
    if isinstance(pfad, str):
        if not pfad.strip():
            raise ValueError("Der Pfad fehlt.")
        return Path(pfad)
    raise TypeError("Der Pfad muss Text oder ein Pfad sein.")


def _erkennen(daten: bytes, name: str) -> str:
    if _ist_pdf(daten):
        return "pdf"
    if daten.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return _zip_art(daten)
    if not _ist_text(daten):
        raise Dateityp()
    endung = Path(name).suffix.casefold()
    if endung in {".md", ".markdown"}:
        return "md"
    if endung == ".txt":
        return "txt"
    raise Dateityp()


def _ist_pdf(daten: bytes) -> bool:
    kopf = daten[:1024]
    stelle = kopf.find(b"%PDF-")
    if stelle < 0:
        return False
    return all(byte in b" \t\r\n" for byte in kopf[:stelle])


def _ist_text(daten: bytes) -> bool:
    if b"\x00" in daten:
        return False
    try:
        text = _dekodieren(daten)
    except UnicodeDecodeError:
        return False
    return not any(ord(zeichen) < 32 and zeichen not in "\t\n\r" for zeichen in text)


def _dekodieren(daten: bytes) -> str:
    """UTF-8, bei einem Fehler cp1252. Ein UTF-8-BOM fällt weg."""
    try:
        return daten.decode("utf-8-sig")
    except UnicodeDecodeError:
        return daten.decode("cp1252")


def _bloecke(text: str, *, markdown: bool) -> list[tuple[str, str]]:
    zeilen = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    stelle = ""
    puffer: list[str] = []
    teile: list[tuple[str, str]] = []
    im_code = False
    zaun = ""

    def flush() -> None:
        nonlocal puffer
        inhalt = "\n".join(puffer).strip()
        puffer = []
        if inhalt:
            teile.append((stelle, inhalt))

    index = 0
    while index < len(zeilen):
        zeile = zeilen[index]
        nackt = zeile.strip()
        if markdown and im_code:
            if nackt.startswith(zaun) and set(nackt) == {zaun[0]}:
                im_code = False
                flush()
            else:
                puffer.append(zeile)
            index += 1
            continue
        if markdown:
            geoeffnet = _ZAUN.match(nackt)
            if geoeffnet:
                flush()
                im_code = True
                zaun = geoeffnet.group(1)
                index += 1
                continue
            ueberschrift = _atx(nackt)
            if ueberschrift is not None:
                flush()
                stelle = ueberschrift
                index += 1
                continue
            if nackt and index + 1 < len(zeilen) and _setext(zeilen[index + 1]):
                flush()
                stelle = nackt
                index += 2
                continue
            if _THEMA.fullmatch(nackt):
                flush()
                index += 1
                continue
        if not nackt:
            flush()
        else:
            puffer.append(nackt)
        index += 1
    flush()
    if not teile:
        raise KeinText()
    return teile


def _atx(zeile: str) -> str | None:
    treffer = _ATX.match(zeile)
    if not treffer:
        return None
    rest = re.sub(r"[ \t]+#+\s*$", "", treffer.group(2)).strip()
    return rest or None


def _setext(zeile: str) -> bool:
    nackt = zeile.strip()
    return bool(nackt) and (set(nackt) == {"="} or set(nackt) == {"-"})


def _paket(modul: str):
    try:
        return importlib.import_module(modul)
    except ImportError:
        name = _PAKETE.get(modul, modul)
        raise PaketFehlt(f"Das Paket {name} fehlt (Abhängigkeit dokumente).") from None


def _pdf(daten: bytes) -> list[tuple[str, str]]:
    pypdf = _paket("pypdf")
    try:
        leser = pypdf.PdfReader(io.BytesIO(daten))
    except Exception as exc:
        if _pdf_fehler(exc):
            raise Dateityp() from None
        raise
    teile: list[tuple[str, str]] = []
    for nummer, seite in enumerate(leser.pages, start=1):
        try:
            roh = seite.extract_text() or ""
        except Exception as exc:
            if _pdf_fehler(exc):
                raise Dateityp() from None
            raise
        text = _zeile(roh)
        if text:
            teile.append((f"S. {nummer}", text))
    if not teile:
        raise KeinText(_SCAN)
    return teile


def _pdf_fehler(exc: BaseException) -> bool:
    name = exc.__class__.__name__
    return name.startswith("Pdf") and name.endswith("Error")


def _docx(daten: bytes) -> list[tuple[str, str]]:
    docx = _paket("docx")
    try:
        dokument = docx.Document(io.BytesIO(daten))
    except (ValueError, zipfile.BadZipFile) as exc:
        raise Dateityp() from exc
    except Exception as exc:
        if exc.__class__.__name__ == "PackageNotFoundError":
            raise Dateityp() from None
        raise
    stelle = ""
    teile: list[tuple[str, str]] = []
    for absatz in dokument.paragraphs:
        text = _zeile(absatz.text)
        if not text:
            continue
        if _ueberschrift(absatz):
            stelle = text
            continue
        teile.append((stelle, text))
    if not teile:
        raise KeinText()
    return teile


def _ueberschrift(absatz: object) -> bool:
    stil = getattr(absatz, "style", None)
    if stil is None:
        return False
    namen = [getattr(stil, "name", None) or "", getattr(stil, "style_id", None) or ""]
    for roh in namen:
        name = str(roh).replace(" ", "").casefold()
        if name in {"title", "titel"}:
            return True
        if name.startswith(("heading", "überschrift", "ueberschrift")):
            return True
    return False


def _epub(daten: bytes) -> list[tuple[str, str]]:
    try:
        paket = zipfile.ZipFile(io.BytesIO(daten))
    except zipfile.BadZipFile:
        raise Dateityp() from None
    with paket:
        namen = _zip_namen(paket)
        opf_name = _opf_name(paket, namen)
        opf = _dekodieren(paket.read(opf_name))
        normal = opf_name.replace("\\", "/")
        basis = normal.rsplit("/", 1)[0] if "/" in normal else ""
        manifest, spine = _opf(opf)
        if not spine:
            raise Dateityp()
        teile: list[tuple[str, str]] = []
        for kennung in spine:
            if kennung not in manifest:
                raise Dateityp()
            href, medientyp = manifest[kennung]
            if not _ist_html(medientyp, href):
                continue
            ziel = _zip_ziel(basis, href)
            original = _finden(namen, ziel)
            if original is None:
                raise Dateityp()
            stelle, text = _kapitel(_dekodieren(paket.read(original)))
            if text:
                teile.append((stelle, text))
    if not teile:
        raise KeinText()
    return teile


def _zip_art(daten: bytes) -> str:
    try:
        paket = zipfile.ZipFile(io.BytesIO(daten))
    except zipfile.BadZipFile:
        raise Dateityp() from None
    with paket:
        namen = _zip_namen(paket)
        mimetype = _finden(namen, "mimetype")
        if mimetype is not None and paket.read(mimetype).strip() == b"application/epub+zip":
            return "epub"
        if _finden(namen, "word/document.xml") is not None:
            return "docx"
    raise Dateityp()


def _zip_namen(paket: zipfile.ZipFile) -> dict[str, str]:
    zuordnung: dict[str, str] = {}
    for name in paket.namelist():
        normal = name.replace("\\", "/").lstrip("/")
        if not normal or normal.endswith("/"):
            continue
        zuordnung.setdefault(normal, name)
    return zuordnung


def _finden(namen: dict[str, str], gesucht: str) -> str | None:
    if gesucht in namen:
        return namen[gesucht]
    falt = gesucht.casefold()
    for normal, original in namen.items():
        if normal.casefold() == falt:
            return original
    return None


def _opf_name(paket: zipfile.ZipFile, namen: dict[str, str]) -> str:
    container = _finden(namen, "META-INF/container.xml")
    if container is None:
        raise Dateityp()
    for name, attrs in _tags(_dekodieren(paket.read(container))):
        if name == "rootfile" and attrs.get("full-path"):
            pfad = unquote(attrs["full-path"]).replace("\\", "/").lstrip("/")
            original = _finden(namen, pfad)
            if original is None:
                raise Dateityp()
            return original
    raise Dateityp()


def _opf(xml: str) -> tuple[dict[str, tuple[str, str]], list[str]]:
    manifest: dict[str, tuple[str, str]] = {}
    spine: list[str] = []
    for name, attrs in _tags(xml):
        if name == "item" and attrs.get("id") and attrs.get("href"):
            manifest[attrs["id"]] = (attrs["href"], attrs.get("media-type", ""))
        elif name == "itemref" and attrs.get("idref"):
            spine.append(attrs["idref"])
    return manifest, spine


def _ist_html(medientyp: str, href: str) -> bool:
    art = medientyp.split(";", 1)[0].strip().lower()
    if art in _HTML:
        return True
    if art:
        return False
    endung = href.split("#", 1)[0].rsplit(".", 1)[-1].lower()
    return endung in _HTML_ENDUNG


def _zip_ziel(basis: str, href: str) -> str:
    roh = unquote(href).split("#", 1)[0].split("?", 1)[0].replace("\\", "/")
    if not roh or roh.startswith("/"):
        raise Dateityp()
    teile: list[str] = []
    vorgabe = [teil for teil in basis.split("/") if teil not in {"", "."}]
    for stueck in (*vorgabe, *roh.split("/")):
        if stueck in {"", "."}:
            continue
        if stueck == "..":
            raise Dateityp()
        teile.append(stueck)
    if not teile:
        raise Dateityp()
    return "/".join(teile)


def _kapitel(xml: str) -> tuple[str, str]:
    leser = _Kapitel()
    leser.feed(xml)
    leser.close()
    return leser.fertig()


def _tags(xml: str) -> list[tuple[str, dict[str, str]]]:
    leser = _Starttags()
    leser.feed(xml)
    leser.close()
    return leser.tags


def _zeile(text: str) -> str:
    return " ".join(text.replace("\x00", "").split())


class _Starttags(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower().rsplit(":", 1)[-1]
        werte = {
            schluessel.lower().rsplit(":", 1)[-1]: wert or ""
            for schluessel, wert in attrs
        }
        self.tags.append((name, werte))


class _Kapitel(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.titel = ""
        self.ueberschrift = ""
        self.bloecke: list[str] = []
        self._puffer: list[str] = []
        self._in_titel = False
        self._in_kopf = False
        self._ueberschrift = False
        self._aus = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower().rsplit(":", 1)[-1]
        if name in {"script", "style"}:
            self._aus += 1
        elif name == "head":
            self._in_kopf = True
        elif name == "title":
            self._in_titel = True
        elif name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._abschluss()
            self._ueberschrift = True
        elif name in {"p", "div", "li", "blockquote", "tr", "section", "article"}:
            self._abschluss()
        elif name == "br":
            self._puffer.append("\n")

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower().rsplit(":", 1)[-1]
        if name in {"script", "style"} and self._aus:
            self._aus -= 1
        elif name == "head":
            self._in_kopf = False
        elif name == "title":
            self._in_titel = False
        elif name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            text = self._nehmen()
            if text and not self.ueberschrift:
                self.ueberschrift = text
            self._ueberschrift = False
        elif name in {"p", "div", "li", "blockquote", "tr", "section", "article", "body"}:
            self._abschluss()

    def handle_data(self, data: str) -> None:
        if self._aus:
            return
        if self._in_titel:
            self.titel += data
            return
        if self._in_kopf:
            return
        self._puffer.append(data)

    def fertig(self) -> tuple[str, str]:
        self._abschluss()
        stelle = self.ueberschrift or _zeile(self.titel)
        return stelle, "\n".join(self.bloecke).strip()

    def _nehmen(self) -> str:
        text = _zeile("".join(self._puffer))
        self._puffer = []
        return text

    def _abschluss(self) -> None:
        if self._ueberschrift:
            text = self._nehmen()
            if text and not self.ueberschrift:
                self.ueberschrift = text
            self._ueberschrift = False
            return
        text = self._nehmen()
        if text:
            self.bloecke.append(text)
