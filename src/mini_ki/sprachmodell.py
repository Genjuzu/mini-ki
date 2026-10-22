"""Sprachmodell-Helfer.

Verweis in eine allein stehende Frage umschreiben, Formulierungen als JSON
erzeugen und lesen, eine Antwort mit Zusatz neu schreiben. Das Modell ist
eine Funktion `(system, nutzer) -> str`. Ein fester Anbieter steht hier nicht.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from .sperre import braucht_kontext, gesperrt

Sprachmodell = Callable[[str, str], str]

_HOECHSTENS = 8
_RAHMEN = "\"'„“”«»‚‘’"

_SYSTEM_VERWEIS = (
    "Formuliere die neue Äußerung zu einer allein stehenden Frage. "
    "Sie soll ohne den Verlauf verständlich sein. "
    "Gib ausschließlich diese Frage zurück."
)
_SYSTEM_FORMEN = (
    "Formuliere Suchfragen auf Deutsch. Eine Antwort schreibst du nicht. "
    "kanonisch ist die eine Frage, die ohne Verlauf verständlich ist. "
    "formen sind weitere natürliche Formulierungen, höchstens sieben. "
    "Pronomen brauchen einen Bezug. Namen, E-Mail, Telefon und IBAN "
    "lässt du weg. Antworte ausschließlich mit einem JSON-Objekt mit "
    "den Schlüsseln kanonisch und formen."
)
_SYSTEM_NEU = (
    "Formuliere die bisherige Antwort neu, ohne ihren Sinn zu ändern. "
    "Steht ein Zusatz dabei, setze ihn um. "
    "Antworte nur mit dem neuen Wortlaut."
)


class SprachmodellFehler(RuntimeError):
    """Das Modell hat keinen brauchbaren Text geliefert."""


def formulierungen_lesen(roh: str) -> list[str]:
    """Liest `kanonisch` und `formen` aus JSON, auch aus einem Code-Zaun.

    Die Reihenfolge bleibt. Groß- und Kleinschreibung und überzählige
    Leerzeichen gelten als dieselbe Formulierung. Höchstens acht Einträge.
    Kaputtes JSON ergibt eine leere Liste. Gesperrte Texte fallen weg.
    """
    objekt = _objekt(roh)
    if objekt is None:
        return []
    return _aus_objekt(objekt)


def formulierungen(
    modell: Sprachmodell,
    frage: str,
    antwort: str,
    verlauf: str = "",
) -> list[str]:
    """Lässt das Modell Formulierungen als JSON erzeugen und liest sie.

    Steht die gesagte Frage für sich und das JSON ist gültig, bleibt sie
    die erste Formulierung. Ein Fehler oder kaputtes JSON ergibt eine
    leere Liste.
    """
    frage_text = _satz(frage)
    antwort_text = _block(antwort)
    verlauf_text = _block(verlauf)
    if not frage_text and not antwort_text and not verlauf_text:
        return []
    try:
        roh = _rufen(
            modell,
            _SYSTEM_FORMEN,
            _nutzer_formen(frage_text, antwort_text, verlauf_text),
        )
    except Exception:
        return []
    objekt = _objekt(roh)
    if objekt is None:
        return []
    gelesen = _aus_objekt(objekt)
    if (
        frage_text
        and not braucht_kontext(frage_text)
        and not gesperrt(frage_text)
    ):
        return _eindeutig([frage_text, *gelesen])
    return gelesen


def verweis_umschreiben(
    modell: Sprachmodell,
    frage: str,
    verlauf: str = "",
) -> str:
    """Schreibt einen Verweis in eine allein stehende Frage um.

    Eine Frage, die für sich steht, geht unverändert zurück und das Modell
    wird nicht gerufen. Wirft das Modell einen Fehler oder liefert nichts
    Brauchbares, kommt die ursprüngliche Frage zurück.
    """
    original = _block(frage)
    if not original or not braucht_kontext(original):
        return original
    try:
        roh = _rufen(
            modell,
            _SYSTEM_VERWEIS,
            _nutzer_verweis(original, _block(verlauf)),
        )
    except Exception:
        return original
    allein = _eine_frage(roh)
    if not allein or gesperrt(allein):
        return original
    return allein


def neu(
    modell: Sprachmodell,
    frage: str,
    antwort: str,
    zusatz: str = "",
) -> str:
    """Schreibt die Antwort neu. `zusatz` ist eine weitere Anweisung.

    Der Speicher wird hier nicht durchsucht. Fehlt dem Modell der Text,
    bleibt die bisherige Antwort beim Aufrufer.
    """
    antwort_text = _block(antwort)
    if not antwort_text:
        raise ValueError("Die Antwort fehlt.")
    try:
        roh = _rufen(
            modell,
            _SYSTEM_NEU,
            _nutzer_neu(_block(frage), antwort_text, _block(zusatz)),
        )
    except Exception:
        raise SprachmodellFehler(
            "Das Sprachmodell hat keine neue Antwort geliefert."
        ) from None
    text = roh.strip()
    if not text or gesperrt(text):
        raise SprachmodellFehler(
            "Das Sprachmodell hat keine neue Antwort geliefert."
        )
    return text


def _aus_objekt(objekt: dict) -> list[str]:
    teile: list[object] = []
    if "kanonisch" in objekt:
        teile.append(objekt.get("kanonisch"))
    extra = objekt.get("formen")
    if isinstance(extra, list):
        teile.extend(extra)
    return _eindeutig(teile)


def _eindeutig(texte: list[object]) -> list[str]:
    gesehen: set[str] = set()
    fertig: list[str] = []
    for eintrag in texte:
        text = _satz(eintrag)
        schluessel = text.casefold()
        if not text or schluessel in gesehen or gesperrt(text):
            continue
        gesehen.add(schluessel)
        fertig.append(text)
        if len(fertig) >= _HOECHSTENS:
            break
    return fertig


def _objekt(roh: object) -> dict | None:
    text = _json_rohtext(roh)
    if not text:
        return None
    try:
        daten = json.loads(text)
    except json.JSONDecodeError:
        pass
    else:
        return daten if isinstance(daten, dict) else None
    klammer = text.find("{")
    if klammer < 0:
        return None
    try:
        daten, _ende = json.JSONDecoder().raw_decode(text[klammer:])
    except json.JSONDecodeError:
        return None
    return daten if isinstance(daten, dict) else None


def _json_rohtext(roh: object) -> str:
    if not isinstance(roh, str):
        return ""
    text = roh.strip().lstrip("\ufeff")
    anfang = text.find("```")
    if anfang < 0:
        return text
    rest = text[anfang + 3 :]
    ende = rest.find("```")
    inhalt = rest if ende < 0 else rest[:ende]
    return _ohne_sprache(inhalt).strip()


def _ohne_sprache(inhalt: str) -> str:
    rest = inhalt.lstrip()
    if rest.startswith("{") or rest.startswith("["):
        return rest
    umbruch = rest.find("\n")
    if umbruch >= 0:
        return rest[umbruch + 1 :]
    klammer = rest.find("{")
    if klammer >= 0:
        return rest[klammer:]
    return rest


def _satz(wert: object) -> str:
    if not isinstance(wert, str):
        return ""
    return " ".join(wert.split())


def _block(wert: object) -> str:
    if not isinstance(wert, str):
        return ""
    return wert.strip()


def _rufen(modell: Sprachmodell, system: str, nutzer: str) -> str:
    if not callable(modell):
        raise TypeError("Das Sprachmodell muss eine Funktion sein.")
    ergebnis = modell(system, nutzer)
    if not isinstance(ergebnis, str):
        raise TypeError("Das Sprachmodell muss Text liefern.")
    return ergebnis


def _eine_frage(roh: str) -> str:
    if not isinstance(roh, str):
        return ""
    zeile = ""
    for teil in roh.splitlines():
        zeile = teil.strip()
        if zeile:
            break
    zeile = " ".join(zeile.strip(_RAHMEN).split())
    if not zeile or zeile.startswith("```") or zeile.startswith("{"):
        return ""
    return zeile


def _nutzer_verweis(frage: str, verlauf: str) -> str:
    bloecke: list[str] = []
    if verlauf:
        bloecke.append("Verlauf:\n" + verlauf)
    bloecke.append("Neue Äußerung:\n" + frage)
    return "\n\n".join(bloecke)


def _nutzer_formen(frage: str, antwort: str, verlauf: str) -> str:
    bloecke: list[str] = []
    if verlauf:
        bloecke.append("Verlauf:\n" + verlauf)
    if antwort:
        bloecke.append("Antwort:\n" + antwort)
    if frage:
        bloecke.append("Gesagte Frage:\n" + frage)
    return "\n\n".join(bloecke)


def _nutzer_neu(frage: str, antwort: str, zusatz: str) -> str:
    bloecke: list[str] = []
    if frage:
        bloecke.append("Frage:\n" + frage)
    bloecke.append("Bisherige Antwort:\n" + antwort)
    if zusatz:
        bloecke.append("Zusatz:\n" + zusatz)
    return "\n\n".join(bloecke)
