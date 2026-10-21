"""Sperre. E-Mail, Telefon und IBAN bleiben draußen."""

from __future__ import annotations

import re

_HINWEIS = re.compile(
    r"\b(dazu|darüber|daruber|hierzu|diesem|diesen|diese|jenes|davon)\b",
    re.IGNORECASE,
)
_JA = re.compile(r"^(ja|nein|genau|ok|okay|klar)\b", re.IGNORECASE)

_PII = re.compile(
    r"(\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b|"
    r"\b(?:\+?\d[\d\s./()-]{6,}\d)\b|"
    r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b)",
    re.IGNORECASE,
)


def gesperrt(text: str) -> bool:
    """E-Mail, Telefonnummer oder IBAN."""
    return bool(_PII.search(text or ""))


def braucht_kontext(text: str) -> bool:
    """Kurzer Verweis auf die vorige Runde. Volle Fragen bleiben stehen."""
    bereinigt = (text or "").strip()
    if _HINWEIS.search(bereinigt):
        return True
    return bool(_JA.match(bereinigt) and len(bereinigt.split()) <= 14)
