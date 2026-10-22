"""Ein Dienst, ein Datenordner.

Voreingestellt hört der Prozess nur auf 127.0.0.1. Im Container setzt
Compose `MINI_KI_HOST=0.0.0.0`, veröffentlicht den Port aber nur auf
127.0.0.1. SQLite und Anhänge liegen unter `mandanten/<id>/`.
Ohne `mandanten-zugang.json` ist das genau `standard`.
Gewichte nur im Ordner `modell-cache`, nie im Image.
"""

from __future__ import annotations

import os
from pathlib import Path

from mini_ki import MiniKI
from mini_ki.api import Api, laufen
from mini_ki.einstellungen import Einstellungen, standard_fabrik
from mini_ki.mandanten import Mandanten

_MANDANT = "standard"
_HOST = "127.0.0.1"
_PORT = 8080
_DATEN = "/data"


def daten_wurzel(pfad: str | Path | None = None) -> Path:
    """Ordner für SQLite, Anhänge und den Modell-Cache."""
    if pfad is None:
        roh = os.environ.get("MINI_KI_DATA")
        if roh is None or roh.strip() == "":
            roh = _DATEN
    else:
        roh = os.fspath(pfad)
    text = roh.strip()
    if text == "":
        raise ValueError("Der Datenordner fehlt.")
    angegeben = Path(text).expanduser()
    if angegeben.is_symlink():
        raise ValueError("Der Datenordner darf kein Verweis sein.")
    wurzel = angegeben.resolve(strict=False)
    if wurzel.exists() and not wurzel.is_dir():
        raise ValueError("Der Datenordner muss ein Ordner sein.")
    return wurzel


def _ordner(pfad: Path) -> None:
    if pfad.is_symlink():
        raise ValueError("Der Datenordner darf kein Verweis sein.")
    pfad.mkdir(parents=True, exist_ok=True)
    if pfad.is_symlink():
        raise ValueError("Der Datenordner darf kein Verweis sein.")


def layout(wurzel: Path) -> dict[str, Path]:
    """Legt die Ordner aus der Architektur an. Lädt keine Gewichte."""
    cache = wurzel / "modell-cache"
    mandant = wurzel / "mandanten" / _MANDANT
    anhaenge = mandant / "anhaenge"
    sqlite = mandant / "mini-ki.sqlite"
    for pfad in (wurzel / "mandanten", mandant, cache, anhaenge):
        if pfad.is_symlink():
            raise ValueError("Der Datenordner darf kein Verweis sein.")
    _ordner(cache)
    _ordner(anhaenge)
    return {"cache": cache, "sqlite": sqlite, "anhaenge": anhaenge}


def zugang_aus_umgebung() -> str | None:
    """Bearer aus `MINI_KI_ZUGANG`. Leer heißt: kein Schlüssel nötig."""
    roh = os.environ.get("MINI_KI_ZUGANG")
    if roh is None or roh == "":
        return None
    return roh


def api_bauen(pfad: str | Path | None = None) -> Api:
    """Kern auf dem Datenordner. Die Gewichte bleiben im Cache-Ordner.

    Liegt `mandanten-zugang.json` mit mindestens einem Mandanten, gilt
    der Kunden-Schlüssel daraus. Sonst bleibt es ein Mandant `standard`,
    optional mit `MINI_KI_ZUGANG`. Liegt `einstellungen.json` neben der
    SQLite-Datei, öffnet der Dienst mit dieser Einbettung. Ohne Datei
    bleibt es das lokale Modell.
    """
    wurzel = daten_wurzel(pfad)
    pfade = layout(wurzel)
    mandanten = Mandanten(wurzel)
    if mandanten.konfiguriert():
        return Api(mandanten=mandanten)
    datei = pfade["sqlite"].parent / "einstellungen.json"
    einstellungen = Einstellungen(
        datei,
        fabrik=standard_fabrik(pfade["cache"]),
        cache=pfade["cache"],
    )
    einbettung = einstellungen.fuer_start(pfade["sqlite"])
    kern = MiniKI(pfade["sqlite"], einbettung)
    return Api(
        kern,
        token=zugang_aus_umgebung(),
        einstellungen=einstellungen,
    )


def bindung() -> tuple[str, int]:
    """Rechner und Port. Ohne Umgebung nur 127.0.0.1:8080."""
    host = os.environ.get("MINI_KI_HOST", _HOST).strip() or _HOST
    roh = os.environ.get("MINI_KI_PORT", str(_PORT)).strip() or str(_PORT)
    if not roh.isdigit():
        raise ValueError("Der Port ist ungültig.")
    port = int(roh)
    if port > 65535:
        raise ValueError("Der Port ist ungültig.")
    return host, port


def haupt() -> None:
    """Bedient Anfragen, bis der Prozess endet."""
    host, port = bindung()
    api = api_bauen()
    print(f"Mini-KI hört auf {host}:{port}", flush=True)
    laufen(api, host=host, port=port)
