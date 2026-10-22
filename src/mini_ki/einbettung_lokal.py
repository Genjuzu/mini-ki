"""Lokale Einbettung. MiniLM-L12 über fastembed, Gewichte nur im Cache."""

from __future__ import annotations

import threading
from pathlib import Path

MODELL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
BREITE = 384


def _fastembed_oeffnen(modell: str, cache: Path):
    try:
        from fastembed import TextEmbedding
    except ImportError as fehler:
        raise ImportError(
            "Lokale Einbettung braucht das Extra 'lokal' (fastembed)."
        ) from fehler
    cache.mkdir(parents=True, exist_ok=True)
    return TextEmbedding(model_name=modell, cache_dir=str(cache))


class LokaleEinbettung:
    """MiniLM-L12 über fastembed. 384 Dimensionen, Kosinus.

    `cache` ist der Ordner für die Gewichte. Sie liegen nie im Repository.
    Das Modell wird einmal pro Objekt geladen.
    """

    def __init__(self, cache: str | Path) -> None:
        self.modell = MODELL
        self.breite = BREITE
        self._cache = Path(cache)
        self._geladen = None
        self._sperre = threading.Lock()

    def vektoren(self, texte: list[str]) -> list[list[float]]:
        """Ein Vektor pro Text. Die Länge jedes Vektors ist `breite`."""
        if not texte:
            return []
        modell = self._holen()
        roh = list(modell.embed(list(texte)))
        if len(roh) != len(texte):
            raise ValueError("Einbettung lieferte nicht einen Vektor pro Text.")
        fertig: list[list[float]] = []
        for vektor in roh:
            zahlen = [float(wert) for wert in vektor]
            if len(zahlen) != self.breite:
                raise ValueError(
                    f"Vektor hat Breite {len(zahlen)}, erwartet {self.breite}."
                )
            fertig.append(zahlen)
        return fertig

    def _holen(self):
        geladen = self._geladen
        if geladen is not None:
            return geladen
        with self._sperre:
            if self._geladen is None:
                self._geladen = _fastembed_oeffnen(self.modell, self._cache)
            return self._geladen
