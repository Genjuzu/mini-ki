"""Mandanten: eigene Daten, ein Modell, Schlüssel nur als Hash."""

import hashlib
import hmac
import json
import logging
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from mini_ki.api import Api, dienen
from mini_ki.mandanten import (
    STANDARD,
    ZUGANG_DATEI,
    Mandanten,
    MandantenFehler,
    MandantGesperrt,
    id_gueltig,
)
from mini_ki.stapel import api_bauen

WURZEL = Path(__file__).resolve().parents[1]
FRAGE = "Wie erreiche ich Avatari?"
ANTWORT = "Die Kontaktdaten stehen auf der Webseite von Avatari."
AUDIO = b"OggS" + b"\x00mandant-a-audio\xff" * 8
AUSBRUCH = "ausbruch-mini-ki-15"


class Gleich:
    """Jeder Text liegt auf demselben Vektor. Ein Treffer wäre sonst sicher."""

    def __init__(self) -> None:
        self.modell = "zaehl-einbettung"
        self.breite = 4

    def vektoren(self, texte: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0, 0.0] for _ in texte]


def fabrik(zaehler: list[int]):
    def bauen():
        zaehler[0] += 1
        return Gleich()

    return bauen


def welt(tmp_path: Path, namen: tuple[str, ...] = ("kunde-a", "kunde-b")):
    zaehler = [0]
    mandanten = Mandanten(tmp_path, fabrik=fabrik(zaehler))
    schluessel = {name: mandanten.anlegen(name) for name in namen}
    api = Api(mandanten=mandanten)
    return mandanten, api, schluessel, zaehler


def kopf(koepfe, name: str) -> str:
    for schluessel, wert in koepfe.items():
        if schluessel.lower() == name.lower():
            return wert
    return ""


def deuten(koepfe, roh: bytes):
    if "application/json" in kopf(koepfe, "content-type") and roh:
        return json.loads(roh.decode("utf-8"))
    return roh


def ruf(api: Api, methode: str, pfad: str, daten=None, roh: bytes | None = None, token=None, extra=None):
    koepfe = {}
    inhalt = b"" if roh is None else roh
    if daten is not None:
        inhalt = json.dumps(daten, ensure_ascii=False).encode("utf-8")
        koepfe["Content-Type"] = "application/json"
    if token is not None:
        koepfe["Authorization"] = f"Bearer {token}"
    if extra:
        koepfe.update(extra)
    status, antwort_kopf, antwort = api.bearbeiten(methode, pfad, inhalt, koepfe)
    return status, antwort_kopf, deuten(antwort_kopf, antwort)


def roh_ruf(api: Api, methode: str, pfad: str, daten=None, token=None):
    koepfe = {}
    inhalt = b""
    if daten is not None:
        inhalt = json.dumps(daten, ensure_ascii=False).encode("utf-8")
        koepfe["Content-Type"] = "application/json"
    if token is not None:
        koepfe["Authorization"] = f"Bearer {token}"
    return api.bearbeiten(methode, pfad, inhalt, koepfe)


def dateien(wurzel: Path) -> list[Path]:
    return [pfad for pfad in wurzel.rglob("*") if pfad.is_file() and not pfad.is_symlink()]


def enthaelt(wurzel: Path, nadel: bytes) -> bool:
    return any(nadel in pfad.read_bytes() for pfad in dateien(wurzel))


def test_mandant_a_trifft_mandant_b_nicht(tmp_path):
    """A merkt und bewertet gut. Dieselbe Frage bei B ist kein Treffer."""
    mandanten, api, schluessel, _zaehler = welt(tmp_path)
    status, _, angelegt = ruf(
        api,
        "POST",
        "/v1/eintraege",
        {"frage": FRAGE, "antwort": ANTWORT},
        token=schluessel["kunde-a"],
    )
    assert status == 201
    kennung = angelegt["id"]
    assert ruf(
        api,
        "POST",
        f"/v1/anfragen/{kennung}/bewertung",
        {"bewertung": "gut"},
        token=schluessel["kunde-a"],
    )[0] == 200

    status, _, fremd = ruf(
        api,
        "POST",
        "/v1/anfragen",
        {"text": FRAGE},
        token=schluessel["kunde-b"],
    )
    assert status == 200
    assert fremd == {"id": None, "herkunft": "fehltreffer", "text": ""}

    status, _, eigen = ruf(
        api,
        "POST",
        "/v1/anfragen",
        {"text": FRAGE},
        token=schluessel["kunde-a"],
    )
    assert status == 200
    assert eigen["herkunft"] == "speicher"
    assert eigen["id"] == kennung
    assert eigen["text"] == ANTWORT
    assert enthaelt(mandanten.ordner("kunde-a"), ANTWORT.encode())
    assert not enthaelt(mandanten.ordner("kunde-b"), ANTWORT.encode())


def test_audio_von_a_ist_fuer_b_nicht_lesbar(tmp_path):
    _mandanten, api, schluessel, _zaehler = welt(tmp_path)
    status, _, angelegt = ruf(
        api,
        "POST",
        "/v1/eintraege",
        {"frage": FRAGE, "antwort": ANTWORT, "bewertung": "gut"},
        token=schluessel["kunde-a"],
    )
    kennung = angelegt["id"]
    pfad = f"/v1/anfragen/{kennung}/anhaenge/audio"
    assert ruf(api, "PUT", pfad, roh=AUDIO, token=schluessel["kunde-a"])[0] == 200
    status, _, roh = ruf(api, "GET", pfad, token=schluessel["kunde-a"])
    assert status == 200
    assert roh == AUDIO

    status, _, daten = ruf(api, "GET", pfad, token=schluessel["kunde-b"])
    assert status == 404
    assert daten == {"fehler": "Nicht gefunden."}
    assert ruf(
        api,
        "GET",
        "/v1/anfragen/rate-die-id/anhaenge/audio",
        token=schluessel["kunde-b"],
    )[0] == 404
    assert not enthaelt(Path(tmp_path) / "mandanten" / "kunde-b", AUDIO)


def test_ohne_oder_falscher_schluessel_401_gesperrt_403(tmp_path):
    mandanten, api, schluessel, _zaehler = welt(tmp_path)
    assert ruf(api, "GET", "/v1/gesundheit")[0] == 401
    status, koepfe, daten = ruf(api, "GET", "/v1/gesundheit", token="falscher-zugang-xx")
    assert status == 401
    assert daten == {"fehler": "Der Zugang fehlt."}
    assert kopf(koepfe, "WWW-Authenticate").startswith("Bearer")
    assert ruf(api, "GET", "/v1/gesundheit", extra={"Authorization": "Basic abc"})[0] == 401

    assert ruf(api, "GET", "/v1/gesundheit", token=schluessel["kunde-a"])[0] == 200
    mandanten.sperren("kunde-a")
    status, _, daten = ruf(api, "GET", "/v1/gesundheit", token=schluessel["kunde-a"])
    assert status == 403
    assert daten == {"fehler": "Der Mandant ist gesperrt."}
    assert schluessel["kunde-a"] not in json.dumps(daten)
    with pytest.raises(MandantGesperrt):
        mandanten.zuordnen(schluessel["kunde-a"])
    mandanten.freigeben("kunde-a")
    assert ruf(api, "GET", "/v1/gesundheit", token=schluessel["kunde-a"])[0] == 200


def test_id_mit_ausbruch_oder_grossbuchstaben_wird_abgewiesen(tmp_path):
    mandanten = Mandanten(tmp_path, fabrik=fabrik([0]))
    assert id_gueltig("kunde-a")
    assert id_gueltig(STANDARD)
    assert id_gueltig("a" * 64)
    verboten = (
        "../" + AUSBRUCH,
        "..",
        ".",
        "",
        " ",
        "Kunde",
        "a/b",
        "a\\b",
        "a..b",
        "aa/../bb",
        "a" * 65,
        "ä",
        "a b",
        "kunde\n",
    )
    for roh in verboten:
        assert not id_gueltig(roh)
        with pytest.raises(MandantenFehler) as fehler:
            mandanten.anlegen(roh)
        assert AUSBRUCH not in str(fehler.value)
        assert "/" not in str(fehler.value)
    assert not (tmp_path / AUSBRUCH).exists()
    assert not (tmp_path / "mandanten" / "Kunde").exists()
    assert not (tmp_path / "mandanten" / "a").exists()
    assert not (tmp_path / "mandanten" / "bb").exists()
    assert list(tmp_path.iterdir()) == []

    schluessel = mandanten.anlegen("kunde-a")
    assert mandanten.ordner("kunde-a") == tmp_path / "mandanten" / "kunde-a"
    assert mandanten.ordner("kunde-a").is_dir()
    assert schluessel not in str(mandanten.ordner("kunde-a"))


def test_symlink_liegt_nicht_ausserhalb(tmp_path):
    fremd = tmp_path / "fremd"
    fremd.mkdir()
    (fremd / "geheim.txt").write_text("bleib", encoding="utf-8")
    mandanten = Mandanten(tmp_path, fabrik=fabrik([0]))
    (tmp_path / "mandanten").mkdir()
    (tmp_path / "mandanten" / "kunde-a").symlink_to(fremd, target_is_directory=True)
    with pytest.raises(MandantenFehler):
        mandanten.anlegen("kunde-a")
    assert (fremd / "geheim.txt").read_text(encoding="utf-8") == "bleib"
    assert not (tmp_path / ZUGANG_DATEI).exists()

    mandanten.anlegen("kunde-b")
    kern = mandanten.kern("kunde-b")
    kennung = kern.merken(FRAGE, ANTWORT, bewertung="gut")
    assert kennung
    aussen = tmp_path / "aussen.txt"
    aussen.write_text("bleib", encoding="utf-8")
    (mandanten.ordner("kunde-b") / "link").symlink_to(aussen)
    assert mandanten.vergessen("kunde-b") is True
    assert not mandanten.ordner("kunde-b").exists()
    assert aussen.read_text(encoding="utf-8") == "bleib"
    ziel = tmp_path / "woanders.json"
    ziel.write_text("{}\n", encoding="utf-8")
    (tmp_path / ZUGANG_DATEI).unlink()
    (tmp_path / ZUGANG_DATEI).symlink_to(ziel)
    with pytest.raises(MandantenFehler):
        mandanten.zuordnen("dieser-text-ist-kein-schluessel")
    assert ziel.read_text(encoding="utf-8") == "{}\n"


def test_einbettung_wird_bei_drei_mandanten_einmal_geladen(tmp_path):
    zaehler = [0]
    mandanten = Mandanten(tmp_path, fabrik=fabrik(zaehler))
    assert zaehler[0] == 0
    namen = ("eins", "zwei", "drei")
    for name in namen:
        mandanten.anlegen(name)
    assert zaehler[0] == 0
    kerne = [mandanten.kern(name) for name in namen]
    assert zaehler[0] == 1
    assert mandanten.ladungen == 1
    assert kerne[0]._einbettung is kerne[1]._einbettung is kerne[2]._einbettung
    for kern in kerne:
        assert kern.merken(FRAGE, ANTWORT, bewertung="gut")
    assert zaehler[0] == 1
    assert len({kern._speicher.pfad for kern in kerne}) == 3


def test_api_modell_hat_eigene_breite_lokales_bleibt_geteilt(tmp_path):
    zaehler = [0]
    mandanten = Mandanten(tmp_path, fabrik=fabrik(zaehler))
    mandanten.anlegen("api-kunde")
    datei = mandanten.ordner("api-kunde") / "einstellungen.json"
    datei.write_text(
        json.dumps(
            {
                "einbettung": "api",
                "adresse": "http://127.0.0.1:9/v1",
                "modell": "test/andere-breite",
                "breite": 8,
                "schluessel": "nur-ein-testwert",
            }
        ),
        encoding="utf-8",
    )
    api_kern = mandanten.kern("api-kunde")
    assert zaehler[0] == 0
    assert api_kern._einbettung.breite == 8
    mandanten.anlegen("lokal-a")
    mandanten.anlegen("lokal-b")
    kern_a = mandanten.kern("lokal-a")
    kern_b = mandanten.kern("lokal-b")
    assert zaehler[0] == 1
    assert mandanten.ladungen == 1
    assert kern_a._einbettung is kern_b._einbettung
    assert kern_a._einbettung is not api_kern._einbettung
    assert kern_a._einbettung.breite == 4


def test_vergessen_loescht_genau_den_ordner(tmp_path):
    mandanten, api, schluessel, _zaehler = welt(tmp_path)
    ruf(
        api,
        "POST",
        "/v1/eintraege",
        {"frage": FRAGE, "antwort": ANTWORT, "bewertung": "gut"},
        token=schluessel["kunde-a"],
    )
    status, _, angelegt = ruf(
        api,
        "POST",
        "/v1/eintraege",
        {"frage": FRAGE, "antwort": "Nur bei B.", "bewertung": "gut"},
        token=schluessel["kunde-b"],
    )
    kennung_b = angelegt["id"]
    cache = tmp_path / "modell-cache"
    cache.mkdir()
    (cache / "marker.txt").write_text("gewichte", encoding="utf-8")
    (tmp_path / "nebenan.txt").write_text("bleib", encoding="utf-8")
    assert mandanten.vergessen("kunde-a") is True
    assert not (tmp_path / "mandanten" / "kunde-a").exists()
    assert (tmp_path / "mandanten" / "kunde-b" / "mini-ki.sqlite").is_file()
    assert (cache / "marker.txt").read_text(encoding="utf-8") == "gewichte"
    assert (tmp_path / "nebenan.txt").read_text(encoding="utf-8") == "bleib"
    assert ruf(api, "GET", "/v1/gesundheit", token=schluessel["kunde-a"])[0] == 401
    treffer = ruf(api, "POST", "/v1/anfragen", {"text": FRAGE}, token=schluessel["kunde-b"])[2]
    assert treffer["herkunft"] == "speicher"
    assert treffer["id"] == kennung_b
    assert mandanten.vergessen("fehlt-nicht") is False


def test_kunden_schluessel_steht_nicht_im_log_oder_in_der_antwort(tmp_path, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    mandanten = Mandanten(tmp_path, fabrik=fabrik([0]))
    schluessel = mandanten.anlegen("kunde-a")
    mandanten.anlegen("kunde-b")
    api = Api(mandanten=mandanten)
    antworten = []
    with caplog.at_level(logging.DEBUG):
        antworten.append(roh_ruf(api, "GET", "/v1/gesundheit", token=schluessel))
        antworten.append(roh_ruf(api, "GET", "/v1/gesundheit"))
        antworten.append(roh_ruf(api, "GET", "/v1/gesundheit", token="anderer-zugang-ohne-treffer"))
        antworten.append(
            roh_ruf(
                api,
                "POST",
                "/v1/eintraege",
                {"frage": FRAGE, "antwort": ANTWORT, "bewertung": "gut"},
                token=schluessel,
            )
        )
        mandanten.sperren("kunde-a")
        antworten.append(roh_ruf(api, "GET", "/v1/gesundheit", token=schluessel))
        assert "mandanten=True" in repr(api)
        assert schluessel not in repr(api)
        assert schluessel not in repr(mandanten)
    gefangen = capsys.readouterr()
    texte = [caplog.text, gefangen.out, gefangen.err, repr(api), repr(mandanten)]
    for record in caplog.records:
        texte.append(record.getMessage())
        texte.append(repr(record.args))
    for status, koepfe, inhalt in antworten:
        texte.append(inhalt.decode("utf-8", errors="replace"))
        texte.extend(koepfe.values())
        assert status in {200, 201, 401, 403}
    for text in texte:
        assert schluessel not in text
    assert caplog.records
    datei = tmp_path / ZUGANG_DATEI
    roh = datei.read_bytes()
    assert schluessel.encode("utf-8") not in roh
    assert stat.S_IMODE(datei.stat().st_mode) == 0o600
    eintrag = json.loads(roh.decode("utf-8"))["eintraege"][0]
    digest = hmac.new(bytes.fromhex(eintrag["salt"]), schluessel.encode("utf-8"), hashlib.sha256)
    assert hmac.compare_digest(digest.hexdigest(), eintrag["hash"])
    assert "schluessel" not in eintrag
    for pfad in dateien(tmp_path):
        assert schluessel.encode("utf-8") not in pfad.read_bytes()


def test_ohne_konfiguration_laeuft_als_standard(tmp_path):
    zaehler = [0]
    mandanten = Mandanten(tmp_path, fabrik=fabrik(zaehler))
    assert mandanten.konfiguriert() is False
    api = Api(mandanten=mandanten)
    assert "standard" in repr(api)
    status, _, daten = ruf(api, "GET", "/v1/gesundheit")
    assert status == 200
    assert daten["einbettung_bereit"] is True
    assert (tmp_path / "mandanten" / STANDARD / "mini-ki.sqlite").is_file()
    status, _, angelegt = ruf(
        api,
        "POST",
        "/v1/eintraege",
        {"frage": FRAGE, "antwort": ANTWORT},
    )
    assert status == 201
    assert ruf(
        api,
        "POST",
        f"/v1/anfragen/{angelegt['id']}/bewertung",
        {"bewertung": "gut"},
    )[0] == 200
    treffer = ruf(api, "POST", "/v1/anfragen", {"text": FRAGE})[2]
    assert treffer["herkunft"] == "speicher"
    assert treffer["id"] == angelegt["id"]
    with pytest.raises(MandantenFehler):
        mandanten.kern("../" + AUSBRUCH)


def test_id_aus_pfad_oder_body_reicht_nicht(tmp_path):
    _mandanten, api, schluessel, _zaehler = welt(tmp_path)
    status, _, _daten = ruf(
        api,
        "POST",
        "/v1/eintraege",
        {"frage": FRAGE, "antwort": ANTWORT, "bewertung": "gut", "mandant": "kunde-b"},
        token=schluessel["kunde-a"],
        extra={"X-Mandant": "kunde-b"},
    )
    assert status == 201
    fremd = ruf(api, "POST", "/v1/anfragen", {"text": FRAGE, "mandant": "kunde-a"}, token=schluessel["kunde-b"])
    assert fremd[2]["herkunft"] == "fehltreffer"
    eigen = ruf(api, "POST", "/v1/anfragen", {"text": FRAGE}, token=schluessel["kunde-a"])
    assert eigen[2]["herkunft"] == "speicher"
    assert ruf(api, "POST", "/v1/mandanten", {"id": "neu"}, token=schluessel["kunde-a"])[0] == 404
    assert ruf(api, "POST", "/v1/mandanten/kunde-b/anfragen", {"text": FRAGE})[0] == 401


def test_integration_http_zwei_mandanten(tmp_path):
    """Der laufende Dienst auf 127.0.0.1 trennt Cache, Audio und Zugang."""
    import urllib.error
    import urllib.request

    mandanten, api, schluessel, zaehler = welt(tmp_path)

    def holen(url: str, methode: str, daten=None, roh: bytes | None = None, token=None):
        inhalt = roh
        typ = None
        if daten is not None:
            inhalt = json.dumps(daten, ensure_ascii=False).encode("utf-8")
            typ = "application/json"
        anfrage = urllib.request.Request(url, data=inhalt, method=methode)
        if typ:
            anfrage.add_header("Content-Type", typ)
        if token is not None:
            anfrage.add_header("Authorization", f"Bearer {token}")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            antwort = opener.open(anfrage, timeout=5)
        except urllib.error.HTTPError as fehler:
            antwort = fehler
        try:
            koerper = antwort.read()
            koepfe = {name: wert for name, wert in antwort.headers.items()}
            return antwort.getcode(), deuten(koepfe, koerper)
        finally:
            antwort.close()

    with dienen(api, host="127.0.0.1", port=0) as dienst:
        basis = dienst.basis
        assert holen(basis + "/v1/gesundheit", "GET")[0] == 401
        assert holen(basis + "/v1/gesundheit", "GET", token="falscher-zugang-yy")[0] == 401
        status, angelegt = holen(
            basis + "/v1/eintraege",
            "POST",
            {"frage": FRAGE, "antwort": ANTWORT},
            token=schluessel["kunde-a"],
        )
        assert status == 201
        kennung = angelegt["id"]
        assert holen(
            basis + f"/v1/anfragen/{kennung}/bewertung",
            "POST",
            {"bewertung": "gut"},
            token=schluessel["kunde-a"],
        )[0] == 200
        audio_pfad = basis + f"/v1/anfragen/{kennung}/anhaenge/audio"
        assert holen(audio_pfad, "PUT", roh=AUDIO, token=schluessel["kunde-a"])[0] == 200
        assert holen(audio_pfad, "GET", token=schluessel["kunde-b"])[0] == 404
        status, fremd = holen(
            basis + "/v1/anfragen",
            "POST",
            {"text": FRAGE},
            token=schluessel["kunde-b"],
        )
        assert status == 200
        assert fremd["herkunft"] == "fehltreffer"
        status, eigen = holen(
            basis + "/v1/anfragen",
            "POST",
            {"text": FRAGE},
            token=schluessel["kunde-a"],
        )
        assert eigen["id"] == kennung
        assert schluessel["kunde-a"].encode("utf-8") not in json.dumps(eigen).encode("utf-8")
        mandanten.sperren("kunde-b")
        assert holen(basis + "/v1/gesundheit", "GET", token=schluessel["kunde-b"])[0] == 403
    assert zaehler[0] == 1


def _umgebung(tmp_path: Path) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path),
        "PYTHONPATH": str(WURZEL / "src"),
        "PYTHONNOUSERSITE": "1",
        "MINI_KI_DATA": str(tmp_path),
    }


def _cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mini_ki.mandanten", "--daten", str(tmp_path), *args],
        cwd=WURZEL,
        env=_umgebung(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_gibt_den_schluessel_einmal_aus(tmp_path):
    angelegt = _cli(tmp_path, "anlegen", "kunde-a")
    assert angelegt.returncode == 0
    schluessel = angelegt.stdout.strip()
    assert schluessel
    assert "\n" not in schluessel
    assert schluessel not in angelegt.stderr
    roh = (tmp_path / ZUGANG_DATEI).read_text(encoding="utf-8")
    assert schluessel not in roh
    mandanten = Mandanten(tmp_path, fabrik=fabrik([0]))
    assert mandanten.zuordnen(schluessel) == "kunde-a"
    gesperrt = _cli(tmp_path, "sperren", "kunde-a")
    assert gesperrt.returncode == 0
    assert schluessel not in gesperrt.stdout
    assert schluessel not in gesperrt.stderr
    with pytest.raises(MandantGesperrt):
        mandanten.zuordnen(schluessel)
    assert _cli(tmp_path, "freigeben", "kunde-a").returncode == 0
    assert mandanten.zuordnen(schluessel) == "kunde-a"
    assert _cli(tmp_path, "vergessen", "kunde-a").returncode == 0
    assert not (tmp_path / "mandanten" / "kunde-a").exists()
    assert _cli(tmp_path, "anlegen", "../" + AUSBRUCH).returncode == 1
    assert not (tmp_path / AUSBRUCH).exists()


def test_stapel_verlangt_den_kunden_schluessel(tmp_path, monkeypatch):
    def oeffnen(*_args, **_kwargs):
        raise AssertionError("Gewichte dürfen beim Start nicht geladen werden.")

    monkeypatch.setattr("mini_ki.einbettung_lokal._fastembed_oeffnen", oeffnen)
    monkeypatch.delenv("MINI_KI_ZUGANG", raising=False)
    schluessel = Mandanten(tmp_path).anlegen("kunde-a")
    api = api_bauen(tmp_path)
    assert ruf(api, "GET", "/v1/gesundheit")[0] == 401
    assert ruf(api, "GET", "/v1/gesundheit", token="falscher-zugang-zz")[0] == 401
    status, _, daten = ruf(api, "GET", "/v1/gesundheit", token=schluessel)
    assert status == 200
    assert daten["einbettung_bereit"] is True
    assert daten["modell"]
    sqlite = tmp_path / "mandanten" / "kunde-a" / "mini-ki.sqlite"
    assert sqlite.is_file()
    assert schluessel.encode("utf-8") not in sqlite.read_bytes()
    assert schluessel.encode("utf-8") not in (tmp_path / ZUGANG_DATEI).read_bytes()
