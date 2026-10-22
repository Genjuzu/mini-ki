"""Messwerkzeug für die Schwelle.

Liest Paare aus einer CSV und gibt den Kosinus je Paar für die
übergebene Einbettung aus. Die Zahl gehört zum Modell. Wer das Modell
wechselt, misst hier neu, bevor eine Schwelle gilt.

`gefaehrlich` sind verschiedene Inhalte, die sich trotzdem nahe kommen
können, etwa eine Uhrzeit. `umschreibung` ist dieselbe Sache in anderen
Worten. `fremd` bleibt weit auseinander und hält die Schwelle unten fest.

Aufruf vom Repository aus:

    python3 werkzeuge/schwelle.py --einbettung fake
    python3 werkzeuge/schwelle.py --einbettung lokal --cache /pfad/modell-cache
    python3 werkzeuge/schwelle.py --einbettung api --adresse https://beispiel.invalid/v1 --modell name --breite 384 --schluessel …

Der Schlüssel steht nur im Aufruf an den Endpunkt und nie in der Ausgabe.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import math
import sys
from dataclasses import dataclass
from pathlib import Path


def _quelle_einhaengen() -> None:
    quelle = Path(__file__).resolve().parents[1] / "src"
    eintrag = str(quelle)
    if quelle.is_dir() and eintrag not in sys.path:
        sys.path.insert(0, eintrag)


_quelle_einhaengen()

from mini_ki.einbettung import Einbettung  # noqa: E402
from mini_ki.einbettung_api import ApiEinbettung, EinbettungApiFehler  # noqa: E402
from mini_ki.einbettung_lokal import LokaleEinbettung  # noqa: E402

PAARE = Path(__file__).resolve().parent / "paare.csv"
ARTEN = ("gefaehrlich", "umschreibung", "fremd")
_FAKE_BREITE = 32


class PaarFehler(ValueError):
    """Die Paarliste ist nicht brauchbar."""


@dataclass(frozen=True)
class Paar:
    """Ein Messpaar. `art` ist eine der drei Rollen aus der Paarliste."""

    art: str
    links: str
    rechts: str


@dataclass(frozen=True)
class Messung:
    """Kosinus eines Paars für genau das Modell, das die Vektoren gebaut hat."""

    art: str
    links: str
    rechts: str
    kosinus: float


class FakeEinbettung:
    """Feste Vektoren aus dem Text. Kein Modell, kein Netz."""

    modell = "fake-einbettung"
    breite = _FAKE_BREITE

    def vektoren(self, texte: list[str]) -> list[list[float]]:
        return [_einheit(text, self.breite) for text in texte]


def _einheit(text: str, breite: int) -> list[float]:
    roh = hashlib.sha256(text.encode("utf-8")).digest()
    werte: list[float] = []
    while len(werte) < breite:
        roh = hashlib.sha256(roh).digest()
        for byte in roh:
            werte.append((byte / 127.5) - 1.0)
            if len(werte) == breite:
                break
    laenge = math.sqrt(sum(wert * wert for wert in werte))
    if laenge == 0.0:
        raise ValueError("Der Fake-Vektor hat die Länge null.")
    return [wert / laenge for wert in werte]


def paare_lesen(pfad: str | Path) -> list[Paar]:
    """Liest `art,links,rechts`. Leere Zeilen fallen weg, die Reihenfolge bleibt."""
    datei = Path(pfad)
    if datei.is_dir():
        raise PaarFehler("Die Paarliste muss eine Datei sein.")
    if not datei.is_file():
        raise PaarFehler(f"Die Paarliste fehlt: {datei}")
    try:
        inhalt = datei.read_text(encoding="utf-8")
    except UnicodeError:
        raise PaarFehler("Die Paarliste ist kein UTF-8.") from None
    except OSError:
        raise PaarFehler(f"Die Paarliste ist nicht lesbar: {datei}") from None
    leser = csv.DictReader(io.StringIO(inhalt))
    felder = list(leser.fieldnames or [])
    fehlend = [name for name in ("art", "links", "rechts") if name not in felder]
    if fehlend:
        raise PaarFehler("Der Paarliste fehlen Spalten: " + ", ".join(fehlend))
    paare: list[Paar] = []
    for nummer, zeile in enumerate(leser, start=2):
        art = (zeile.get("art") or "").strip()
        links = (zeile.get("links") or "").strip()
        rechts = (zeile.get("rechts") or "").strip()
        if art == "" and links == "" and rechts == "":
            continue
        if art == "" or links == "" or rechts == "":
            raise PaarFehler(f"Zeile {nummer} ist unvollständig.")
        if art not in ARTEN:
            erlaubt = ", ".join(ARTEN)
            raise PaarFehler(
                f"Zeile {nummer} hat eine unbekannte Art. Erlaubt sind {erlaubt}."
            )
        if "\n" in links or "\r" in links or "\n" in rechts or "\r" in rechts:
            raise PaarFehler(f"Zeile {nummer} enthält einen Zeilenumbruch im Text.")
        if links == rechts:
            raise PaarFehler(f"Zeile {nummer} vergleicht einen Text mit sich.")
        paare.append(Paar(art, links, rechts))
    if not paare:
        raise PaarFehler("Die Paarliste enthält kein Paar.")
    return paare


def kosinus(links: list[float], rechts: list[float]) -> float:
    """Kosinus zweier gleich langer Vektoren. Null und keine endliche Zahl scheitern."""
    if len(links) != len(rechts):
        raise ValueError("Die Vektoren haben verschiedene Breiten.")
    skalar = 0.0
    norm_links = 0.0
    norm_rechts = 0.0
    for links_wert, rechts_wert in zip(links, rechts, strict=True):
        if not math.isfinite(links_wert) or not math.isfinite(rechts_wert):
            raise ValueError("Ein Vektor enthält keine endliche Zahl.")
        skalar += links_wert * rechts_wert
        norm_links += links_wert * links_wert
        norm_rechts += rechts_wert * rechts_wert
    if norm_links == 0.0 or norm_rechts == 0.0:
        raise ValueError("Ein Vektor hat die Länge null.")
    return skalar / math.sqrt(norm_links * norm_rechts)


def messen(einbettung: Einbettung, paare: list[Paar]) -> list[Messung]:
    """Ein Kosinus je Paar. Jeder verschiedene Text wird einmal eingebettet."""
    if not paare:
        raise ValueError("Es gibt kein Paar zum Messen.")
    if not hasattr(einbettung, "vektoren") or not hasattr(einbettung, "breite"):
        raise ValueError("Die Einbettung nennt keine Breite und keine Vektoren.")
    gesehen: dict[str, int] = {}
    texte: list[str] = []
    for paar in paare:
        for text in (paar.links, paar.rechts):
            if text not in gesehen:
                gesehen[text] = len(texte)
                texte.append(text)
    roh = einbettung.vektoren(texte)
    if len(roh) != len(texte):
        raise ValueError("Einbettung lieferte nicht einen Vektor pro Text.")
    breite = einbettung.breite
    if isinstance(breite, bool) or not isinstance(breite, int) or breite < 1:
        raise ValueError("Die Breite der Einbettung ist ungültig.")
    vektoren: list[list[float]] = []
    for vektor in roh:
        try:
            zahlen = [float(wert) for wert in vektor]
        except (TypeError, ValueError):
            raise ValueError("Einbettung lieferte keine Zahlen.") from None
        if len(zahlen) != breite:
            raise ValueError(f"Vektor hat Breite {len(zahlen)}, erwartet {breite}.")
        vektoren.append(zahlen)
    return [
        Messung(
            paar.art,
            paar.links,
            paar.rechts,
            kosinus(vektoren[gesehen[paar.links]], vektoren[gesehen[paar.rechts]]),
        )
        for paar in paare
    ]


def tabelle(messungen: list[Messung], einbettung: Einbettung) -> str:
    """Texttabelle. Der Kosinus steht mit Punkt und drei Nachkommastellen."""
    if not hasattr(einbettung, "modell") or not hasattr(einbettung, "breite"):
        raise ValueError("Die Einbettung nennt kein Modell.")
    zeilen = [
        f"Modell: {einbettung.modell}",
        f"Breite: {einbettung.breite}",
        "",
    ]
    kopf = ("art", "kosinus", "links", "rechts")
    daten = [
        (messung.art, f"{messung.kosinus:.3f}", messung.links, messung.rechts)
        for messung in messungen
    ]
    breiten: list[int] = []
    for spalte in range(4):
        laenge = len(kopf[spalte])
        for zeile in daten:
            laenge = max(laenge, len(zeile[spalte]))
        breiten.append(laenge)

    def _formatieren(zellen: tuple[str, str, str, str]) -> str:
        teile: list[str] = []
        for spalte, zelle in enumerate(zellen):
            if spalte == 1:
                teile.append(zelle.rjust(breiten[spalte]))
            else:
                teile.append(zelle.ljust(breiten[spalte]))
        return "  ".join(teile).rstrip()

    zeilen.append(_formatieren(kopf))
    zeilen.extend(_formatieren(zeile) for zeile in daten)
    return "\n".join(zeilen) + "\n"


def lokal_einbettung(cache: str | Path) -> LokaleEinbettung:
    """MiniLM-L12. Die Gewichte liegen im Cache und werden erst beim Messen geladen."""
    return LokaleEinbettung(cache)


def api_einbettung(
    adresse: str,
    modell: str,
    schluessel: str,
    breite: int,
    wartezeit: float = 30.0,
) -> ApiEinbettung:
    """OpenAI-kompatible Einbettung. Der Schlüssel kommt nicht in die Tabelle."""
    return ApiEinbettung(adresse, modell, schluessel, breite, wartezeit=wartezeit)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="werkzeuge/schwelle.py",
        description="Gibt den Kosinus je Paar für das eingestellte Modell aus.",
    )
    parser.add_argument(
        "--einbettung",
        required=True,
        choices=("fake", "lokal", "api"),
        help="fake ohne Modell, lokal mit MiniLM, api für den kompatiblen Endpunkt",
    )
    parser.add_argument(
        "--paare",
        type=Path,
        default=PAARE,
        help="CSV mit den Spalten art, links, rechts",
    )
    parser.add_argument("--cache", type=Path, help="Ordner für die lokalen Gewichte")
    parser.add_argument("--adresse", help="Basis oder Endpunkt der API-Einbettung")
    parser.add_argument("--modell", help="Modellname der API-Einbettung")
    parser.add_argument("--breite", type=int, help="Vektorbreite der API-Einbettung")
    parser.add_argument(
        "--schluessel",
        help="Schlüssel der API-Einbettung. Wird nicht ausgegeben.",
    )
    parser.add_argument(
        "--wartezeit",
        type=float,
        default=30.0,
        help="Sekunden, die die API-Einbettung auf eine Antwort wartet",
    )
    return parser


def _einbettung_aus_args(args: argparse.Namespace) -> Einbettung:
    if args.einbettung == "fake":
        return FakeEinbettung()
    if args.einbettung == "lokal":
        if args.cache is None:
            raise PaarFehler("Lokale Einbettung braucht --cache.")
        return lokal_einbettung(args.cache)
    if (
        args.adresse is None
        or args.modell is None
        or args.breite is None
        or args.schluessel is None
    ):
        raise PaarFehler(
            "Die API-Einbettung braucht --adresse, --modell, --breite und --schluessel."
        )
    return api_einbettung(
        args.adresse,
        args.modell,
        args.schluessel,
        args.breite,
        args.wartezeit,
    )


def haupt(argv: list[str] | None = None) -> int:
    """Liest die Paare, misst und schreibt die Tabelle nach stdout."""
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as ende:
        code = ende.code
        return code if isinstance(code, int) else 2
    try:
        einbettung = _einbettung_aus_args(args)
        messungen = messen(einbettung, paare_lesen(args.paare))
        text = tabelle(messungen, einbettung)
    except (PaarFehler, ValueError, ImportError, EinbettungApiFehler) as fehler:
        print(str(fehler), file=sys.stderr)
        return 1
    ausgabe = sys.stdout
    if hasattr(ausgabe, "reconfigure"):
        try:
            ausgabe.reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass
    print(text, end="", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(haupt())
