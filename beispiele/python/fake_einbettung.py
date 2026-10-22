"""Einbettung ohne Modell und ohne Netz.

Jeder Text wird zu einem festen Einheitsvektor. Die erste Formulierung
einer Gruppe ist der Basis-Vektor, weitere liegen bei Kosinus 0,86:
über der Treffer-Schwelle 0,80 und unter der Gegenbeispiel-Schwelle 0,93.
Das gemessene Modell macht das über die Bedeutung. Hier ist es die Gruppe.
"""

from __future__ import annotations

import hashlib
import math

from texte import GRUPPEN

BREITE = 32
NAH = 0.86


def _einheit(text: str) -> list[float]:
    roh = hashlib.sha256(text.encode("utf-8")).digest()
    werte: list[float] = []
    while len(werte) < BREITE:
        roh = hashlib.sha256(roh).digest()
        for byte in roh:
            werte.append(1.0 if byte & 1 else -1.0)
            if len(werte) == BREITE:
                break
    laenge = math.sqrt(sum(wert * wert for wert in werte))
    return [wert / laenge for wert in werte]


def _nah(basis: list[float], kosinus: float, salz: str) -> list[float]:
    """Einheitsvektor mit festem Kosinus zur Basis, seitlich aus `salz`."""
    senkrecht = _einheit(salz)
    projektion = sum(links * rechts for links, rechts in zip(basis, senkrecht))
    ortho = [rechts - projektion * links for links, rechts in zip(basis, senkrecht)]
    laenge = math.sqrt(sum(wert * wert for wert in ortho))
    if laenge < 1e-8:
        raise ValueError("Die Richtung liegt auf der Basis.")
    ortho = [wert / laenge for wert in ortho]
    rest = math.sqrt(max(0.0, 1.0 - kosinus * kosinus))
    return [kosinus * links + rest * rechts for links, rechts in zip(basis, ortho)]


class FakeEinbettung:
    """Modellname, Breite und Vektoren. Fest, damit Beispiele ohne Gewichte laufen."""

    modell = "fake-einbettung"
    breite = BREITE

    def __init__(self, gruppen: dict[str, list[str]] | None = None) -> None:
        self._basis: dict[str, str] = {}
        self._variante: dict[str, str] = {}
        for name, texte in (gruppen if gruppen is not None else GRUPPEN).items():
            if not texte:
                continue
            self._basis[texte[0]] = name
            for text in texte[1:]:
                self._variante[text] = name
        self._cache: dict[str, list[float]] = {}

    def vektoren(self, texte: list[str]) -> list[list[float]]:
        return [list(self._einer(text)) for text in texte]

    def _einer(self, text: str) -> list[float]:
        if text in self._variante:
            schluessel = "variante:" + text
            vektor = self._cache.get(schluessel)
            if vektor is None:
                vektor = _nah(self._basis_vektor(self._variante[text]), NAH, schluessel)
                self._cache[schluessel] = vektor
            return vektor
        if text in self._basis:
            return self._basis_vektor(self._basis[text])
        vektor = self._cache.get(text)
        if vektor is None:
            vektor = _einheit(text)
            self._cache[text] = vektor
        return vektor

    def _basis_vektor(self, name: str) -> list[float]:
        schluessel = "basis:" + name
        vektor = self._cache.get(schluessel)
        if vektor is None:
            vektor = _einheit(schluessel)
            self._cache[schluessel] = vektor
        return vektor
