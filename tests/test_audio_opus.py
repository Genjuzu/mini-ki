"""Opus-Anhänge. Ohne ffmpeg/libopus werden die Umwandlungstests übersprungen."""

import array
import io
import json
import math
import sys
import urllib.error
import urllib.request
import wave
from pathlib import Path

import pytest

from mini_ki import MiniKI
from mini_ki.api import Api, dienen
from mini_ki.audio import (
    OPUS_MEDIENTYP,
    PCM_MEDIENTYP,
    RATE,
    STANDARD_BITRATE,
    AudioFehler,
    verfuegbar,
)

FRAGE = "Wie spät ist es?"
ANTWORT = "Es ist drei Uhr am späteren Nachmittag."
NEU = "Es ist vier Uhr am späteren Nachmittag."
VEKTOR = [1.0, 0.0, 0.0, 0.0]
_AUDIO_DA = verfuegbar()


class FesteEinbettung:
    modell = "test-modell"
    breite = 4

    def vektoren(self, texte: list[str]) -> list[list[float]]:
        return [list(VEKTOR) for _text in texte]


def _braucht_audio() -> None:
    if not _AUDIO_DA:
        pytest.skip("optionale Abhängigkeit audio fehlt")


def _kern(pfad: Path, **kwargs) -> tuple[MiniKI, str]:
    kern = MiniKI(pfad, FesteEinbettung(), **kwargs)
    kennung = kern.merken(FRAGE, ANTWORT, bewertung="gut")
    assert kennung
    return kern, kennung


def _pcm(sekunden: float, frequenz: float = 440.0) -> bytes:
    """16-bit vorzeichenbehaftet, Netzwerk-Bytefolge, 24 kHz, mono."""
    anzahl = int(round(sekunden * RATE))
    werte = array.array(
        "h",
        (
            int(12_000 * math.sin(2 * math.pi * frequenz * i / RATE))
            for i in range(anzahl)
        ),
    )
    if sys.byteorder == "little":
        werte.byteswap()
    return werte.tobytes()


def _wav(sekunden: float, rate: int = RATE, kanaele: int = 1) -> bytes:
    anzahl = int(round(sekunden * rate))
    werte = array.array("h")
    for i in range(anzahl):
        wert = int(8_000 * math.sin(2 * math.pi * 440 * i / rate))
        werte.extend([wert] * kanaele)
    if sys.byteorder != "little":
        werte.byteswap()
    puffer = io.BytesIO()
    with wave.open(puffer, "wb") as datei:
        datei.setnchannels(kanaele)
        datei.setsampwidth(2)
        datei.setframerate(rate)
        datei.writeframes(werte.tobytes())
    return puffer.getvalue()


def _korrelation(links: bytes, rechts: bytes) -> float:
    a = array.array("h")
    b = array.array("h")
    a.frombytes(links[: len(links) // 2 * 2])
    b.frombytes(rechts[: len(rechts) // 2 * 2])
    if sys.byteorder == "little":
        a.byteswap()
        b.byteswap()
    n = min(len(a), len(b))
    schritt = 20
    summe_a = 0.0
    summe_b = 0.0
    zaehler = 0
    for i in range(0, n, schritt):
        summe_a += a[i]
        summe_b += b[i]
        zaehler += 1
    if zaehler < 10:
        return 0.0
    mittel_a = summe_a / zaehler
    mittel_b = summe_b / zaehler
    var_a = var_b = cov = 0.0
    for i in range(0, n, schritt):
        da = a[i] - mittel_a
        db = b[i] - mittel_b
        var_a += da * da
        var_b += db * db
        cov += da * db
    if var_a <= 0.0 or var_b <= 0.0:
        return 0.0
    return cov / math.sqrt(var_a * var_b)


def _dauer_abweichung(pcm: bytes, zurueck: bytes) -> float:
    return abs(len(zurueck) - len(pcm)) / 2 / RATE


def test_bitrate_ist_voreinstellung_und_grenzt_sich_ein(tmp_path):
    pfad = tmp_path / "mini-ki.sqlite"
    kern = MiniKI(pfad, FesteEinbettung())
    assert kern._audio_bitrate == STANDARD_BITRATE == 16_000
    with pytest.raises(ValueError, match="Bitrate"):
        MiniKI(tmp_path / "zu-klein.sqlite", FesteEinbettung(), audio_bitrate=16)
    assert not (tmp_path / "zu-klein.sqlite").exists()
    with pytest.raises(ValueError, match="Bitrate"):
        MiniKI(tmp_path / "falsch.sqlite", FesteEinbettung(), audio_bitrate=True)


@pytest.mark.audio
def test_minute_pcm_wird_opus_und_kommt_als_pcm_zurueck(tmp_path):
    _braucht_audio()
    pfad = tmp_path / "mandant" / "mini-ki.sqlite"
    kern, kennung = _kern(pfad)
    pcm = _pcm(60)
    assert len(pcm) == 60 * RATE * 2
    assert kern.anhang_setzen(kennung, "audio", pcm, PCM_MEDIENTYP) is True

    datei = pfad.parent / "anhaenge" / kennung / "audio"
    gespeichert = datei.read_bytes()
    assert len(gespeichert) < 200_000
    assert gespeichert.startswith(b"OggS")
    treffer = kern.finden(FRAGE)
    assert treffer is not None
    assert treffer["anhaenge"][0]["medientyp"] == OPUS_MEDIENTYP
    assert treffer["anhaenge"][0]["groesse"] == len(gespeichert)
    assert kern.anhang_lesen(kennung, "audio") == gespeichert

    zurueck = kern.anhang_lesen(kennung, "audio", format="pcm")
    assert zurueck is not None
    assert _dauer_abweichung(pcm, zurueck) <= 0.050
    assert len(zurueck) % 2 == 0
    assert _korrelation(pcm, zurueck) > 0.8


@pytest.mark.audio
def test_opus_wird_unveraendert_abgelegt(tmp_path):
    _braucht_audio()
    pfad = tmp_path / "opus.sqlite"
    kern, kennung = _kern(pfad)
    assert (
        kern.anhang_setzen(kennung, "audio", _pcm(1), "audio/L16;channels=1;rate=24000")
        is True
    )
    datei = pfad.parent / "anhaenge" / kennung / "audio"
    opus = datei.read_bytes()
    assert kern.anhang_setzen(kennung, "audio", opus, "audio/ogg;codecs=opus") is True
    assert datei.read_bytes() == opus
    assert kern.anhang_lesen(kennung, "audio") == opus


@pytest.mark.audio
def test_kaputtes_audio_ergibt_fehler_ohne_halben_anhang(tmp_path):
    _braucht_audio()
    pfad = tmp_path / "kaputt.sqlite"
    kern, kennung = _kern(pfad)
    with pytest.raises(AudioFehler, match="beschädigt"):
        kern.anhang_setzen(kennung, "audio", b"OggS" + b"\x00" * 64, OPUS_MEDIENTYP)
    assert kern.anhang_lesen(kennung, "audio") is None
    assert not (pfad.parent / "anhaenge").exists()
    assert list(tmp_path.rglob("*.teil")) == []

    pcm = _pcm(0.4)
    assert kern.anhang_setzen(kennung, "audio", pcm, PCM_MEDIENTYP) is True
    datei = pfad.parent / "anhaenge" / kennung / "audio"
    vorher = datei.read_bytes()
    with pytest.raises(AudioFehler, match="beschädigt"):
        kern.anhang_setzen(kennung, "audio", vorher[:48], OPUS_MEDIENTYP)
    assert datei.read_bytes() == vorher
    assert kern.anhang_lesen(kennung, "audio") == vorher
    with pytest.raises(AudioFehler, match="24 kHz"):
        kern.anhang_setzen(
            kennung,
            "audio",
            pcm,
            "audio/L16; rate=16000; channels=2",
        )
    assert datei.read_bytes() == vorher
    with pytest.raises(AudioFehler, match="nicht angenommen"):
        kern.anhang_setzen(kennung, "audio", pcm, "audio/mpeg")
    assert datei.read_bytes() == vorher
    assert list(tmp_path.rglob("*.teil")) == []


@pytest.mark.audio
def test_wav_wird_opus_und_textaenderung_loescht_es(tmp_path):
    _braucht_audio()
    pfad = tmp_path / "wav.sqlite"
    kern, kennung = _kern(pfad)
    wav = _wav(0.5, rate=48_000, kanaele=2)
    assert kern.anhang_setzen(kennung, "audio", wav, "audio/wav") is True
    datei = pfad.parent / "anhaenge" / kennung / "audio"
    assert datei.read_bytes().startswith(b"OggS")
    assert kern.finden(FRAGE)["anhaenge"][0]["medientyp"] == OPUS_MEDIENTYP
    zurueck = kern.anhang_lesen(kennung, "audio", format="pcm")
    assert zurueck is not None
    erwartet = int(0.5 * RATE) * 2
    assert abs(len(zurueck) - erwartet) / 2 / RATE <= 0.050

    assert kern.umschreiben(kennung, NEU) is True
    assert not datei.exists()
    assert kern.anhang_lesen(kennung, "audio") is None
    assert kern.finden(FRAGE).get("anhaenge", []) == []


@pytest.mark.audio
def test_hoehere_bitrate_wird_groesser(tmp_path):
    _braucht_audio()
    pcm = _pcm(2)
    klein_pfad = tmp_path / "klein.sqlite"
    gross_pfad = tmp_path / "gross.sqlite"
    klein, klein_id = _kern(klein_pfad, audio_bitrate=16_000)
    gross, gross_id = _kern(gross_pfad, audio_bitrate=64_000)
    assert klein.anhang_setzen(klein_id, "audio", pcm, PCM_MEDIENTYP) is True
    assert gross.anhang_setzen(gross_id, "audio", pcm, PCM_MEDIENTYP) is True
    klein_groesse = (klein_pfad.parent / "anhaenge" / klein_id / "audio").stat().st_size
    gross_groesse = (gross_pfad.parent / "anhaenge" / gross_id / "audio").stat().st_size
    assert gross_groesse > klein_groesse


def _kopf(koepfe, name: str) -> str:
    for schluessel, wert in koepfe.items():
        if schluessel.lower() == name.lower():
            return wert
    return ""


def _deuten(koepfe, roh: bytes):
    if "application/json" in _kopf(koepfe, "content-type") and roh:
        return json.loads(roh.decode("utf-8"))
    return roh


def _holen(url: str, methode: str, roh: bytes | None = None, typ: str | None = None):
    anfrage = urllib.request.Request(url, data=roh, method=methode)
    if typ:
        anfrage.add_header("Content-Type", typ)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        antwort = opener.open(anfrage, timeout=30)
    except urllib.error.HTTPError as fehler:
        antwort = fehler
    try:
        koerper = antwort.read()
        koepfe = {name: wert for name, wert in antwort.headers.items()}
        return antwort.getcode(), koepfe, _deuten(koepfe, koerper)
    finally:
        antwort.close()


@pytest.mark.audio
def test_http_pcm_opus_und_rueckwandlung(tmp_path):
    """Echter Dienst auf 127.0.0.1: PCM rein, Opus raus, ?format=pcm zurück."""
    _braucht_audio()
    kern = MiniKI(tmp_path / "mini-ki.sqlite", FesteEinbettung())
    api = Api(kern)
    pcm = _pcm(1)
    with dienen(api) as dienst:
        assert dienst.host == "127.0.0.1"
        basis = dienst.basis
        status, _, angelegt = _holen(
            basis + "/v1/eintraege",
            "POST",
            json.dumps(
                {"frage": FRAGE, "antwort": ANTWORT, "bewertung": "gut"},
                ensure_ascii=False,
            ).encode("utf-8"),
            "application/json",
        )
        assert status == 201
        kennung = angelegt["id"]
        pfad = f"{basis}/v1/anfragen/{kennung}/anhaenge/audio"

        status, _, _meta = _holen(pfad, "PUT", pcm, PCM_MEDIENTYP)
        assert status == 200
        status, koepfe, opus = _holen(pfad, "GET")
        assert status == 200
        assert isinstance(opus, bytes)
        assert len(opus) < 200_000
        assert opus.startswith(b"OggS")
        assert _kopf(koepfe, "content-type") == OPUS_MEDIENTYP

        status, koepfe, zurueck = _holen(pfad + "?format=pcm", "GET")
        assert status == 200
        assert _kopf(koepfe, "content-type") == PCM_MEDIENTYP
        assert isinstance(zurueck, bytes)
        assert _dauer_abweichung(pcm, zurueck) <= 0.050
        assert _korrelation(pcm, zurueck) > 0.8

        status, _, nochmal = _holen(pfad, "PUT", opus, OPUS_MEDIENTYP)
        assert status == 200
        assert _holen(pfad, "GET")[2] == opus

        status, _, fehler = _holen(pfad, "PUT", b"kein-audio", OPUS_MEDIENTYP)
        assert status == 400
        assert "fehler" in fehler
        assert "beschädigt" in fehler["fehler"]
        assert _holen(pfad, "GET")[2] == opus

        status, _, _text = _holen(
            f"{basis}/v1/anfragen/{kennung}/text",
            "PUT",
            json.dumps({"text": NEU}, ensure_ascii=False).encode("utf-8"),
            "application/json",
        )
        assert status == 200
        assert _holen(pfad, "GET")[0] == 404
        assert list(tmp_path.rglob("*.teil")) == []
