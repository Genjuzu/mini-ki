"""Einstellungen und Modellwechsel. Kein Modell, kein Netz, kein Dienst.

Die Prüfung läuft über `Api.bearbeiten`, also im Prozess und ohne Warten.
Der Schlüssel liegt nur in `tmp_path`.
"""

import json
import math
import stat
from collections import Counter
from pathlib import Path

from mini_ki import MiniKI
from mini_ki.api import Api
from mini_ki.einstellungen import Einstellungen

FRAGE = "Wie erreiche ich Avatari?"
ANDERE = "Wo ist das Büro?"
FORM = "Wie kann ich Avatari erreichen?"
NAH = "Wie erreiche ich Avatari heute?"
ANTWORT = "Die Kontaktdaten stehen auf der Webseite von Avatari."
ANTWORT_B = "Das Büro ist im ersten Stock."
SCHLUESSEL = "pruef-volume-schluessel"
ADRESSE = "http://127.0.0.1:9/v1"

def _nah(kosinus: float, achse: int) -> list[float]:
    """Einheitsvektor mit Kosinus `kosinus` zur Achse `achse`."""
    rest = math.sqrt(1.0 - kosinus * kosinus)
    vektor = [0.0, 0.0, 0.0, 0.0]
    vektor[achse] = kosinus
    vektor[0 if achse else 1] = rest
    return vektor


# NAH liegt bei 0,85: trifft noch, sperrt die Frage selbst aber nicht (Gegenbeispiel 0,93).
ALT = {
    FRAGE: [1.0, 0.0, 0.0, 0.0],
    ANDERE: [0.0, 0.0, 0.0, 1.0],
    FORM: [0.0, 0.0, 1.0, 0.0],
    NAH: _nah(0.85, 0),
}
NEU = {
    FRAGE: [0.0, 1.0, 0.0, 0.0],
    ANDERE: [0.0, 0.0, 1.0, 0.0],
    FORM: [0.0, 0.0, 0.0, 1.0],
    NAH: _nah(0.85, 1),
}
BREIT = {
    FRAGE: [0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0],
    ANDERE: [0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0],
    FORM: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0],
    NAH: [0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0],
}


class FesteEinbettung:
    """Wörterbuch Text → Vektor. Breite folgt aus den Vektoren."""

    def __init__(self, vektoren: dict[str, list[float]], modell: str) -> None:
        breiten = {len(vektor) for vektor in vektoren.values()}
        if len(breiten) != 1:
            raise ValueError("Alle Vektoren brauchen dieselbe Breite.")
        self.modell = modell
        self.breite = breiten.pop()
        self._vektoren = dict(vektoren)
        self.aufrufe: list[list[str]] = []

    def vektoren(self, texte: list[str]) -> list[list[float]]:
        self.aufrufe.append(list(texte))
        fehlend = [text for text in texte if text not in self._vektoren]
        if fehlend:
            raise KeyError(fehlend[0])
        return [list(self._vektoren[text]) for text in texte]


class _Kaputt:
    modell = "modell-kaputt"
    breite = 4

    def vektoren(self, texte: list[str]) -> list[list[float]]:
        raise RuntimeError(SCHLUESSEL)


def fabrik_fuer(modelle: dict[str, object]):
    def fabrik(daten: dict):
        modell = daten["modell"]
        if modell == "modell-kaputt":
            return _Kaputt()
        return modelle[modell]

    return fabrik


def ruf(api: Api, methode: str, pfad: str, daten=None):
    inhalt = b""
    koepfe = {}
    if daten is not None:
        inhalt = json.dumps(daten, ensure_ascii=False).encode("utf-8")
        koepfe["Content-Type"] = "application/json"
    status, antwort_kopf, antwort = api.bearbeiten(methode, pfad, inhalt, koepfe)
    if antwort and "application/json" in antwort_kopf.get("Content-Type", ""):
        return status, antwort_kopf, json.loads(antwort.decode("utf-8"))
    return status, antwort_kopf, antwort


def roh_von(status_kopf_daten) -> bytes:
    _status, koepfe, daten = status_kopf_daten
    teile = [json.dumps(koepfe, ensure_ascii=False).encode("utf-8")]
    if isinstance(daten, bytes):
        teile.append(daten)
    else:
        teile.append(json.dumps(daten, ensure_ascii=False).encode("utf-8"))
    return b" ".join(teile)


def dateien(wurzel: Path) -> list[Path]:
    return [pfad for pfad in wurzel.rglob("*") if pfad.is_file()]


def test_get_zeigt_schluessel_gesetzt_und_nie_den_schluessel(tmp_path):
    """GET nach PUT: Flagge wahr, Schlüssel nur in der Datei im tmp_path."""
    alt = FesteEinbettung(ALT, "modell-alt")
    kern = MiniKI(tmp_path / "mini-ki.sqlite", alt)
    api = Api(kern, einbettung_fabrik=fabrik_fuer({"modell-alt": alt}))

    status, _, sicht = ruf(api, "GET", "/v1/einstellungen")
    assert status == 200
    assert sicht["einbettung"] == "api"
    assert sicht["modell"] == "modell-alt"
    assert sicht["breite"] == 4
    assert sicht["schluessel_gesetzt"] is False
    assert "schluessel" not in sicht
    assert SCHLUESSEL.encode("utf-8") not in roh_von((status, {}, sicht))

    status, koepfe, sicht = ruf(
        api,
        "PUT",
        "/v1/einstellungen",
        {
            "einbettung": "api",
            "adresse": ADRESSE,
            "modell": "modell-alt",
            "breite": 4,
            "schluessel": SCHLUESSEL,
        },
    )
    assert status == 200
    assert sicht == {
        "einbettung": "api",
        "adresse": ADRESSE,
        "modell": "modell-alt",
        "breite": 4,
        "schluessel_gesetzt": True,
    }
    assert "schluessel" not in sicht
    assert SCHLUESSEL.encode("utf-8") not in roh_von((status, koepfe, sicht))
    assert SCHLUESSEL not in repr(api)

    status, koepfe, gelesen = ruf(api, "GET", "/v1/einstellungen")
    assert status == 200
    assert gelesen == sicht
    assert gelesen["schluessel_gesetzt"] is True
    assert SCHLUESSEL.encode("utf-8") not in roh_von((status, koepfe, gelesen))

    datei = tmp_path / "einstellungen.json"
    assert datei.is_file()
    assert stat.S_IMODE(datei.stat().st_mode) == 0o600
    assert SCHLUESSEL.encode("utf-8") in datei.read_bytes()
    assert SCHLUESSEL not in repr(Einstellungen(datei))
    for pfad in dateien(tmp_path):
        if pfad == datei:
            continue
        assert SCHLUESSEL.encode("utf-8") not in pfad.read_bytes()

    status, koepfe, daten = ruf(api, "POST", "/v1/einstellungen", {"schluessel": SCHLUESSEL})
    assert status == 405
    assert SCHLUESSEL.encode("utf-8") not in roh_von((status, koepfe, daten))


def test_modellwechsel_baut_neu_und_trifft_wie_vorher(tmp_path):
    """Anderes Modell, andere Vektoren: dieselben Fragen treffen dieselben Antworten."""
    alt = FesteEinbettung(ALT, "modell-alt")
    neu = FesteEinbettung(NEU, "modell-neu")
    kern = MiniKI(tmp_path / "mini-ki.sqlite", alt)
    haupt = kern.merken(FRAGE, ANTWORT, bewertung="gut")
    neben = kern.merken(ANDERE, ANTWORT_B, bewertung="gut")
    assert kern.formen(haupt, [FORM, FRAGE]) == 2
    assert kern.trennen(NAH, haupt) is True
    assert kern.finden(FRAGE)["id"] == haupt
    assert kern.finden(FORM)["id"] == haupt
    assert kern.finden(ANDERE)["id"] == neben
    assert kern.finden(NAH) is None

    api = Api(
        kern,
        einbettung_fabrik=fabrik_fuer({"modell-alt": alt, "modell-neu": neu}),
    )
    vorher = len(neu.aufrufe)
    status, _, sicht = ruf(
        api,
        "PUT",
        "/v1/einstellungen",
        {
            "einbettung": "api",
            "adresse": ADRESSE,
            "modell": "modell-neu",
            "breite": 4,
            "schluessel": SCHLUESSEL,
        },
    )
    assert status == 200
    assert sicht["modell"] == "modell-neu"
    assert sicht["schluessel_gesetzt"] is True
    assert SCHLUESSEL.encode("utf-8") not in json.dumps(sicht).encode("utf-8")
    assert len(neu.aufrufe) == vorher + 1
    assert Counter(neu.aufrufe[-1]) == Counter([ANDERE, FORM, FRAGE, NAH])

    treffer = ruf(api, "POST", "/v1/anfragen", {"text": FRAGE})[2]
    assert treffer["herkunft"] == "speicher"
    assert treffer["id"] == haupt
    assert treffer["text"] == ANTWORT
    form = ruf(api, "POST", "/v1/anfragen", {"text": FORM})[2]
    assert form["id"] == haupt
    assert form["text"] == ANTWORT
    buero = ruf(api, "POST", "/v1/anfragen", {"text": ANDERE})[2]
    assert buero["id"] == neben
    assert buero["text"] == ANTWORT_B
    assert ruf(api, "POST", "/v1/anfragen", {"text": NAH})[2]["herkunft"] == "fehltreffer"

    gesund = ruf(api, "GET", "/v1/gesundheit")[2]
    assert gesund["modell"] == "modell-neu"
    assert gesund["breite"] == 4
    datei = tmp_path / "einstellungen.json"
    for pfad in dateien(tmp_path):
        if pfad == datei:
            assert SCHLUESSEL.encode("utf-8") in pfad.read_bytes()
        else:
            assert SCHLUESSEL.encode("utf-8") not in pfad.read_bytes()

    aufrufe = len(neu.aufrufe)
    status, _, erneut = ruf(
        api,
        "PUT",
        "/v1/einstellungen",
        {"einbettung": "api", "modell": "modell-neu", "breite": 4},
    )
    assert status == 200
    assert erneut["schluessel_gesetzt"] is True
    assert SCHLUESSEL.encode("utf-8") not in json.dumps(erneut).encode("utf-8")
    assert len(neu.aufrufe) == aufrufe

    konfiguration = Einstellungen(
        tmp_path / "einstellungen.json",
        fabrik=fabrik_fuer({"modell-alt": alt, "modell-neu": neu}),
    )
    start = konfiguration.fuer_start(tmp_path / "mini-ki.sqlite")
    assert start is neu
    assert len(neu.aufrufe) == aufrufe
    wieder = MiniKI(tmp_path / "mini-ki.sqlite", start)
    assert wieder.finden(FRAGE)["id"] == haupt
    assert wieder.finden(NAH) is None
    assert wieder.finden(ANDERE)["id"] == neben


def test_breitenwechsel_trifft_die_gleiche_antwort(tmp_path):
    alt = FesteEinbettung(ALT, "modell-alt")
    breit = FesteEinbettung(BREIT, "modell-breit")
    kern = MiniKI(tmp_path / "mini-ki.sqlite", alt)
    kennung = kern.merken(FRAGE, ANTWORT, bewertung="gut")
    api = Api(
        kern,
        einbettung_fabrik=fabrik_fuer({"modell-alt": alt, "modell-breit": breit}),
    )
    status, _, sicht = ruf(
        api,
        "PUT",
        "/v1/einstellungen",
        {
            "einbettung": "api",
            "adresse": ADRESSE,
            "modell": "modell-breit",
            "breite": 8,
            "schluessel": SCHLUESSEL,
        },
    )
    assert status == 200
    assert sicht["breite"] == 8
    assert sicht["schluessel_gesetzt"] is True
    treffer = ruf(api, "POST", "/v1/anfragen", {"text": FRAGE})[2]
    assert treffer["id"] == kennung
    assert treffer["text"] == ANTWORT
    assert treffer["aehnlichkeit"] == 1.0
    assert SCHLUESSEL.encode("utf-8") not in json.dumps(sicht).encode("utf-8")


def test_fehlgeschlagener_neuaufbau_behaelt_den_alten_treffer(tmp_path):
    alt = FesteEinbettung(ALT, "modell-alt")
    kern = MiniKI(tmp_path / "mini-ki.sqlite", alt)
    kennung = kern.merken(FRAGE, ANTWORT, bewertung="gut")
    api = Api(kern, einbettung_fabrik=fabrik_fuer({"modell-alt": alt}))
    status, koepfe, daten = ruf(
        api,
        "PUT",
        "/v1/einstellungen",
        {
            "einbettung": "api",
            "adresse": ADRESSE,
            "modell": "modell-kaputt",
            "breite": 4,
            "schluessel": SCHLUESSEL,
        },
    )
    assert status == 409
    assert daten == {"fehler": "Der Neuaufbau ist fehlgeschlagen."}
    assert SCHLUESSEL.encode("utf-8") not in roh_von((status, koepfe, daten))
    assert not (tmp_path / "einstellungen.json").exists()
    for pfad in dateien(tmp_path):
        assert SCHLUESSEL.encode("utf-8") not in pfad.read_bytes()
    assert kern.finden(FRAGE)["id"] == kennung
    assert ruf(api, "GET", "/v1/einstellungen")[2]["schluessel_gesetzt"] is False


def test_ungueltige_eingabe_schreibt_den_schluessel_nicht(tmp_path):
    alt = FesteEinbettung(ALT, "modell-alt")
    kern = MiniKI(tmp_path / "mini-ki.sqlite", alt)
    api = Api(kern, einbettung_fabrik=fabrik_fuer({}))
    status, koepfe, daten = ruf(
        api,
        "PUT",
        "/v1/einstellungen",
        {
            "einbettung": "api",
            "adresse": "keine-adresse",
            "modell": "modell-neu",
            "breite": 4,
            "schluessel": SCHLUESSEL,
        },
    )
    assert status == 400
    assert "fehler" in daten
    assert SCHLUESSEL.encode("utf-8") not in roh_von((status, koepfe, daten))
    assert not (tmp_path / "einstellungen.json").exists()
    for pfad in dateien(tmp_path):
        assert SCHLUESSEL.encode("utf-8") not in pfad.read_bytes()

    ziel = tmp_path / "ausserhalb.json"
    ziel.write_text("{}\n", encoding="utf-8")
    link = tmp_path / "einstellungen.json"
    link.symlink_to(ziel)
    status, koepfe, daten = ruf(
        api,
        "PUT",
        "/v1/einstellungen",
        {
            "einbettung": "api",
            "adresse": ADRESSE,
            "modell": "modell-alt",
            "breite": 4,
            "schluessel": SCHLUESSEL,
        },
    )
    assert status == 400
    assert SCHLUESSEL.encode("utf-8") not in roh_von((status, koepfe, daten))
    assert SCHLUESSEL.encode("utf-8") not in ziel.read_bytes()
    assert SCHLUESSEL.encode("utf-8") not in link.read_bytes()
