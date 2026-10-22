"""Audio-Anhänge als Opus in Ogg.

PCM (`audio/L16`, 16-bit vorzeichenbehaftet, Netzwerk-Bytefolge, 24 kHz,
mono) und WAV werden nach Opus umgewandelt. Fertiges Opus wird geprüft
und bytegleich zurückgegeben. Die Umwandlung ruft ffmpeg mit libopus auf.
Ohne dieses Werkzeug bleibt der übrige Kern lauffähig; nur die Umwandlung
meldet einen klaren Fehler.
"""

from __future__ import annotations

import shutil
import subprocess

OPUS_MEDIENTYP = "audio/ogg; codecs=opus"
PCM_MEDIENTYP = "audio/L16; rate=24000; channels=1"
RATE = 24_000
KANAELE = 1
STANDARD_BITRATE = 16_000

_MIN_BITRATE = 6_000
_MAX_BITRATE = 128_000
_WAV = {"audio/wav", "audio/x-wav", "audio/wave", "audio/vnd.wave"}
_ZEIT = 60


class AudioFehler(Exception):
    """Audiodaten lassen sich nicht ablegen oder nicht zurückwandeln."""

    def __init__(self, meldung: str, *, status: int = 400) -> None:
        self.meldung = meldung
        self.status = status
        super().__init__(meldung)


def bitrate_pruefen(wert: int) -> int:
    """Bit pro Sekunde. Voreinstellung ist 16 kbit/s."""
    if isinstance(wert, bool) or not isinstance(wert, int):
        raise ValueError("Die Bitrate muss eine ganze Zahl in Bit pro Sekunde sein.")
    if wert < _MIN_BITRATE or wert > _MAX_BITRATE:
        raise ValueError("Die Bitrate muss zwischen 6 und 128 kbit/s liegen.")
    return wert


def verfuegbar() -> bool:
    """Wahr, wenn ffmpeg und ffprobe Opus kodieren können."""
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        return False
    try:
        verfahren = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return verfahren.returncode == 0 and b"libopus" in verfahren.stdout


def nach_opus(daten: bytes, medientyp: str | None, *, bitrate: int = STANDARD_BITRATE) -> bytes:
    """Liefert die Bytes, die abgelegt werden. Opus bleibt dasselbe Objekt.

    Ohne bekannten Medientyp kommen die Bytes unverändert zurück. PCM und
    WAV werden kodiert. Ein unpassendes Audio-Format oder kaputte Daten
    werfen `AudioFehler`, bevor irgendwo eine Datei entsteht.
    """
    if not isinstance(daten, bytes):
        raise AudioFehler("Die Audiodaten sind beschädigt.")
    art = _art(medientyp)
    if art is None:
        return daten
    if art == "fremd":
        raise AudioFehler("Das Audio-Format wird nicht angenommen.")
    if art == "opus":
        _pruefe_opus(daten)
        return daten
    bitrate_pruefen(bitrate)
    if art == "pcm":
        _pcm_ok(medientyp or "", daten)
        return _kodiere(
            ["-f", "s16be", "-ar", str(RATE), "-ac", str(KANAELE), "-i", "pipe:0"],
            daten,
            bitrate,
        )
    if not daten:
        raise AudioFehler("Die Audiodaten sind beschädigt.")
    return _kodiere(["-i", "pipe:0"], daten, bitrate)


def nach_pcm(daten: bytes) -> bytes:
    """Opus nach `audio/L16`, 24 kHz, mono, Netzwerk-Bytefolge."""
    if not isinstance(daten, bytes) or not daten:
        raise AudioFehler("Die Audiodaten sind beschädigt.")
    roh = _lauf(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-f",
            "s16be",
            "-ar",
            str(RATE),
            "-ac",
            str(KANAELE),
            "-vn",
            "pipe:1",
        ],
        daten,
        ausgabe=True,
    )
    if len(roh) % 2 != 0:
        raise AudioFehler("Die Audiodaten sind beschädigt.")
    return roh


def _art(medientyp: str | None) -> str | None:
    if medientyp is None:
        return None
    if not isinstance(medientyp, str):
        return "fremd"
    text = medientyp.strip()
    if not text or len(text) > 200:
        return None if not text else "fremd"
    if any(ord(zeichen) < 32 or zeichen == "\x7f" for zeichen in text):
        return "fremd"
    basis, _parameter = _zerlegen(text)
    if basis in {"", "application/octet-stream"}:
        return None
    if basis == "audio/l16":
        return "pcm"
    if basis in _WAV:
        return "wav"
    if basis in {"audio/ogg", "audio/opus"}:
        return "opus"
    if basis.startswith("audio/"):
        return "fremd"
    return None


def _zerlegen(medientyp: str) -> tuple[str, dict[str, str]]:
    teile = [teil.strip() for teil in medientyp.split(";")]
    basis = teile[0].lower()
    parameter: dict[str, str] = {}
    for teil in teile[1:]:
        if "=" not in teil:
            continue
        name, wert = teil.split("=", 1)
        parameter[name.strip().lower()] = wert.strip().strip('"').lower()
    return basis, parameter


def _pcm_ok(medientyp: str, daten: bytes) -> None:
    _basis, parameter = _zerlegen(medientyp)
    rate = parameter.get("rate")
    kanaele = parameter.get("channels", "1")
    if rate != str(RATE) or kanaele != str(KANAELE):
        raise AudioFehler("PCM muss 24 kHz, mono und 16-bit sein.")
    if not daten or len(daten) % (2 * KANAELE) != 0:
        raise AudioFehler("PCM muss 24 kHz, mono und 16-bit sein.")


def _pruefe_opus(daten: bytes) -> None:
    if not daten.startswith(b"OggS") or b"OpusHead" not in daten[:4096]:
        raise AudioFehler("Die Audiodaten sind beschädigt.")
    codec = _codec(daten)
    if codec != "opus":
        raise AudioFehler("Das Audio ist kein Opus.")
    _lauf(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-f",
            "null",
            "-",
        ],
        daten,
        ausgabe=False,
    )


def _codec(daten: bytes) -> str:
    roh = _lauf(
        [
            "ffprobe",
            "-hide_banner",
            "-loglevel",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "default=nw=1:nk=1",
            "pipe:0",
        ],
        daten,
        ausgabe=True,
    )
    return roh.decode("utf-8", "replace").strip().lower()


def _kodiere(eingang: list[str], daten: bytes, bitrate: int) -> bytes:
    roh = _lauf(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            *eingang,
            "-c:a",
            "libopus",
            "-b:a",
            str(bitrate),
            "-application",
            "voip",
            "-ac",
            str(KANAELE),
            "-f",
            "ogg",
            "pipe:1",
        ],
        daten,
        ausgabe=True,
    )
    if not roh.startswith(b"OggS") or b"OpusHead" not in roh[:4096]:
        raise AudioFehler("Die Audiodaten sind beschädigt.")
    return roh


def _lauf(args: list[str], daten: bytes, *, ausgabe: bool) -> bytes:
    werkzeug = shutil.which(args[0])
    if werkzeug is None:
        raise AudioFehler("Die Audio-Abhängigkeit fehlt.", status=503)
    try:
        verfahren = subprocess.run(
            [werkzeug, *args[1:]],
            input=daten,
            capture_output=True,
            timeout=_ZEIT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise AudioFehler("Die Audiodaten konnten nicht gewandelt werden.") from None
    if verfahren.returncode != 0:
        raise AudioFehler("Die Audiodaten sind beschädigt.")
    roh = verfahren.stdout
    if ausgabe and not roh:
        raise AudioFehler("Die Audiodaten sind beschädigt.")
    return roh
