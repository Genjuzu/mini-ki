"""HTTP-Dienst für die Beispiele. Fake-Einbettung, kein Modell, kein Netz.

Gibt genau eine Zeile aus: die Basis-Adresse, zum Beispiel
`http://127.0.0.1:12345`. Ein gesetztes `MINI_KI_ZUGANG` wird als Bearer
verlangt und nicht ausgegeben. Der Produktionsstart bleibt `python -m mini_ki`.
"""

from __future__ import annotations

import os
import shutil
import signal
import sys
import tempfile
import threading
from pathlib import Path

_WURZEL = Path(__file__).resolve().parents[2]
_QUELLE = _WURZEL / "src"
if _QUELLE.is_dir():
    sys.path.insert(0, str(_QUELLE))

from mini_ki import MiniKI  # noqa: E402
from mini_ki.api import Api, dienen  # noqa: E402

from fake_einbettung import FakeEinbettung  # noqa: E402
from texte import FRAGE, NEU  # noqa: E402


def sprachmodell(system: str, nutzer: str) -> str:
    """Platzhalter, damit /neu und ein Verweis im Beispiel einen Text haben."""
    if system.startswith("Formuliere die bisherige Antwort neu"):
        return NEU
    if system.startswith("Formuliere die neue Äußerung"):
        return FRAGE
    return nutzer.strip()


def _zugang() -> str | None:
    roh = os.environ.get("MINI_KI_ZUGANG")
    if roh is None or roh == "":
        return None
    return roh


def main() -> None:
    host = "127.0.0.1"
    ordner = tempfile.mkdtemp(prefix="mini-ki-beispiel-")
    stop = threading.Event()

    def _ende(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, _ende)
    signal.signal(signal.SIGINT, _ende)
    try:
        kern = MiniKI(Path(ordner) / "mini-ki.sqlite", FakeEinbettung())
        api = Api(kern, token=_zugang(), sprachmodell=sprachmodell)
        with dienen(api, host=host, port=0) as dienst:
            print(dienst.basis, flush=True)
            stop.wait()
    finally:
        shutil.rmtree(ordner, ignore_errors=True)


if __name__ == "__main__":
    main()
