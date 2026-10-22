"""Docker-Stapel: ein Dienst, Volume /data, Port nur auf 127.0.0.1, keine Gewichte."""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from mini_ki.api import dienen
from mini_ki.stapel import api_bauen, bindung, daten_wurzel, haupt, layout

WURZEL = Path(__file__).resolve().parents[1]
GEWICHTE = {".onnx", ".onnx_data", ".safetensors", ".gguf", ".pt", ".pth"}
TOKEN = "pruef-zugang-stapel"


def lesen(name: str) -> str:
    return (WURZEL / name).read_text(encoding="utf-8")


def holen(url: str, token: str | None = None):
    anfrage = urllib.request.Request(url, method="GET")
    if token is not None:
        anfrage.add_header("Authorization", f"Bearer {token}")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        antwort = opener.open(anfrage, timeout=2)
    except urllib.error.HTTPError as fehler:
        antwort = fehler
    try:
        roh = antwort.read()
        return antwort.getcode(), json.loads(roh.decode("utf-8"))
    finally:
        antwort.close()


def test_layout_legt_sqlite_cache_und_anhaenge_an(tmp_path):
    pfade = layout(tmp_path)
    assert pfade["sqlite"] == tmp_path / "mandanten" / "standard" / "mini-ki.sqlite"
    assert pfade["anhaenge"].is_dir()
    assert pfade["cache"].is_dir()
    assert list(pfade["cache"].iterdir()) == []


def test_cache_darf_kein_verweis_sein(tmp_path):
    fremd = tmp_path / "fremd"
    fremd.mkdir()
    (tmp_path / "modell-cache").symlink_to(fremd, target_is_directory=True)
    with pytest.raises(ValueError):
        layout(tmp_path)
    assert list(fremd.iterdir()) == []


def test_start_antwortet_gesundheit_ohne_gewichte(tmp_path, monkeypatch):
    def oeffnen(*_args, **_kwargs):
        raise AssertionError("Gewichte dürfen beim Start nicht geladen werden.")

    monkeypatch.setattr("mini_ki.einbettung_lokal._fastembed_oeffnen", oeffnen)
    monkeypatch.delenv("MINI_KI_ZUGANG", raising=False)
    api = api_bauen(tmp_path)
    with dienen(api, host="127.0.0.1", port=0) as dienst:
        status, daten = holen(dienst.basis + "/v1/gesundheit")
    assert status == 200
    assert daten["einbettung_bereit"] is True
    assert daten["breite"] == 384
    assert daten["anzahl"] == 0
    assert daten["modell"] == "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    sqlite = tmp_path / "mandanten" / "standard" / "mini-ki.sqlite"
    assert sqlite.is_file()
    assert not list((tmp_path / "modell-cache").iterdir())
    gewichte = [pfad for pfad in tmp_path.rglob("*") if pfad.suffix.lower() in GEWICHTE]
    assert gewichte == []


def test_zugang_aus_der_umgebung_bleibt_aus_dem_speicher(tmp_path, monkeypatch):
    monkeypatch.setenv("MINI_KI_ZUGANG", TOKEN)
    api = api_bauen(tmp_path)
    with dienen(api, host="127.0.0.1", port=0) as dienst:
        assert holen(dienst.basis + "/v1/gesundheit")[0] == 401
        status, daten = holen(dienst.basis + "/v1/gesundheit", token=TOKEN)
    assert status == 200
    assert daten["anzahl"] == 0
    sqlite = tmp_path / "mandanten" / "standard" / "mini-ki.sqlite"
    assert TOKEN.encode("utf-8") not in sqlite.read_bytes()


def test_voreinstellung_nur_auf_dem_geraet(monkeypatch):
    monkeypatch.delenv("MINI_KI_HOST", raising=False)
    monkeypatch.delenv("MINI_KI_PORT", raising=False)
    assert bindung() == ("127.0.0.1", 8080)


def test_datenordner_leer_oder_datei_oder_verweis(tmp_path, monkeypatch):
    monkeypatch.setenv("MINI_KI_DATA", "  ")
    assert daten_wurzel() == Path("/data")
    datei = tmp_path / "datei"
    datei.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        daten_wurzel(datei)
    ziel = tmp_path / "echt"
    ziel.mkdir()
    verweis = tmp_path / "verweis"
    verweis.symlink_to(ziel, target_is_directory=True)
    with pytest.raises(ValueError):
        daten_wurzel(verweis)
    with pytest.raises(ValueError):
        daten_wurzel("   ")


def test_port_ungueltig(monkeypatch):
    monkeypatch.setenv("MINI_KI_PORT", "keins")
    with pytest.raises(ValueError):
        bindung()
    monkeypatch.setenv("MINI_KI_PORT", "70000")
    with pytest.raises(ValueError):
        bindung()


def test_haupt_ohne_umgebung_hoert_lokal(tmp_path, monkeypatch):
    gesehen = {}

    def fake(api, *, host, port):
        gesehen["api"] = api
        gesehen["host"] = host
        gesehen["port"] = port

    monkeypatch.setenv("MINI_KI_DATA", str(tmp_path))
    monkeypatch.delenv("MINI_KI_HOST", raising=False)
    monkeypatch.delenv("MINI_KI_PORT", raising=False)
    monkeypatch.delenv("MINI_KI_ZUGANG", raising=False)
    monkeypatch.setattr("mini_ki.stapel.laufen", fake)
    haupt()
    assert gesehen["host"] == "127.0.0.1"
    assert gesehen["port"] == 8080
    assert (tmp_path / "mandanten" / "standard" / "mini-ki.sqlite").is_file()


def freier_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_modul_startet_und_gesundheit_antwortet(tmp_path):
    port = freier_port()
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path),
        "PYTHONPATH": str(WURZEL / "src"),
        "PYTHONNOUSERSITE": "1",
        "MINI_KI_DATA": str(tmp_path),
        "MINI_KI_HOST": "127.0.0.1",
        "MINI_KI_PORT": str(port),
    }
    prozess = subprocess.Popen(
        [sys.executable, "-m", "mini_ki"],
        cwd=WURZEL,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    url = f"http://127.0.0.1:{port}/v1/gesundheit"
    status = None
    daten = None
    try:
        ende = time.monotonic() + 8
        letzter = ""
        while time.monotonic() < ende:
            if prozess.poll() is not None:
                break
            try:
                status, daten = holen(url)
                break
            except (urllib.error.URLError, TimeoutError, ConnectionError) as fehler:
                letzter = str(fehler)
                time.sleep(0.05)
        else:
            letzter = letzter or "Zeit abgelaufen"
        if status != 200:
            ausgabe, fehler = prozess.communicate(timeout=2)
            pytest.fail(f"{letzter}\n{ausgabe}\n{fehler}")
    finally:
        if prozess.poll() is None:
            prozess.terminate()
            try:
                prozess.wait(timeout=3)
            except subprocess.TimeoutExpired:
                prozess.kill()
                prozess.wait(timeout=3)
    assert daten is not None
    assert daten["einbettung_bereit"] is True
    assert daten["anzahl"] == 0
    assert not list((tmp_path / "modell-cache").iterdir())


def test_compose_ein_dienst_ein_volume_nur_lokal():
    text = lesen("compose.yaml")
    assert "services:\n  mini-ki:\n" in text
    dienste = [
        zeile.strip()[:-1]
        for zeile in text.split("services:", 1)[1].split("volumes:", 1)[0].splitlines()
        if zeile.startswith("  ") and not zeile.startswith("   ") and zeile.rstrip().endswith(":")
    ]
    assert dienste == ["mini-ki"]
    assert '- "127.0.0.1:${MINI_KI_PORT:-8080}:8080"' in text
    ports = text.split("ports:", 1)[1].split("environment:", 1)[0]
    assert "0.0.0.0" not in ports
    assert ports.count("127.0.0.1:") == 1
    assert 'MINI_KI_HOST: "0.0.0.0"' in text
    assert 'MINI_KI_DATA: "/data"' in text
    assert 'MINI_KI_PORT: "8080"' in text
    assert "- mini-ki-data:/data" in text
    volumen = [
        zeile.strip()[:-1]
        for zeile in text.split("\nvolumes:\n", 1)[1].splitlines()
        if zeile.strip() and not zeile.strip().startswith("#")
    ]
    assert volumen == ["mini-ki-data"]


def test_env_example_ohne_werte():
    schluessel = []
    for zeile in lesen(".env.example").splitlines():
        text = zeile.strip()
        if not text or text.startswith("#"):
            continue
        name, trenner, wert = text.partition("=")
        assert trenner == "="
        assert name.strip()
        assert wert.strip().strip('"').strip("'") == ""
        schluessel.append(name.strip())
    assert schluessel == ["MINI_KI_PORT", "MINI_KI_ZUGANG"]


def test_dockerfile_enthaelt_keine_gewichte():
    text = lesen("Dockerfile")
    klein = text.lower()
    for verboten in (
        "wget",
        "curl",
        "huggingface",
        "fastembed",
        "snapshot_download",
        ".onnx",
        ".safetensors",
        "[lokal]",
    ):
        assert verboten not in klein
    assert "VOLUME /data" in text
    assert "USER mini" in text
    assert 'CMD ["python", "-m", "mini_ki"]' in text
    assert "/v1/gesundheit" in text
    kopien = [zeile for zeile in text.splitlines() if zeile.startswith("COPY ")]
    assert kopien == [
        "COPY pyproject.toml README.md /app/",
        "COPY src /app/src",
    ]


def test_dockerignore_sperrt_geheimnisse_und_gewichte():
    text = lesen(".dockerignore")
    for muster in (
        ".env",
        ".onnx",
        ".safetensors",
        ".gguf",
        "data",
        ".git",
        "__pycache__",
        ".venv",
        "tests",
    ):
        assert muster in text
    for pfad in WURZEL.rglob("*"):
        if not pfad.is_file():
            continue
        assert pfad.name != ".env"
        assert pfad.suffix.lower() not in GEWICHTE
