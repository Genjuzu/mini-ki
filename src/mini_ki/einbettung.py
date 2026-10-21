"""Einbettung. Texte rein, Vektoren raus. Das Modell bleibt draußen."""

from __future__ import annotations

from typing import Protocol


class Einbettung(Protocol):
    """Modellname, Breite und eine Abbildung von Texten auf Vektoren."""

    modell: str
    breite: int

    def vektoren(self, texte: list[str]) -> list[list[float]]:
        """Ein Vektor pro Text. Die Länge jedes Vektors ist `breite`."""
