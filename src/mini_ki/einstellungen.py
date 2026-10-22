"""Einstellungen der Einbettung. Der Schlüssel liegt nur in der Datei.

`GET` sieht `schluessel_gesetzt`, nie den Schlüssel. Wechselt Modell oder
Breite, werden alle gespeicherten Fragen neu eingebettet. Vektoren zweier
Modelle passen nicht zusammen (`entscheidungen/einbettung.md`).
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from urllib.parse import urlsplit

import sqlite_vec

ADRESSE_API = "https://openrouter.ai/api/v1"
_DATEI = "einstellungen.json"

Fabrik = Callable[[Mapping[str, object]], object]


class EinstellungenFehler(Exception):
    """Die Einstellung wurde nicht übernommen. Der Text nennt keinen Schlüssel."""

    def __init__(self, meldung: str, status: int = 400) -> None:
        self.meldung = meldung
        self.status = status
        super().__init__(meldung)


def _neuaufbau() -> EinstellungenFehler:
    return EinstellungenFehler("Der Neuaufbau ist fehlgeschlagen.", status=409)


def standard_fabrik(cache: str | Path) -> Fabrik:
    """Lokale Einbettung oder OpenAI-kompatible API. Baut nur das Objekt."""

    cache_pfad = Path(cache)

    def bauen(daten: Mapping[str, object]):
        if daten.get("einbettung") == "lokal":
            from .einbettung_lokal import LokaleEinbettung

            return LokaleEinbettung(cache_pfad)
        from .einbettung_api import ApiEinbettung

        breite = daten.get("breite")
        if isinstance(breite, bool) or not isinstance(breite, int):
            raise EinstellungenFehler("Die Breite fehlt.")
        try:
            return ApiEinbettung(
                str(daten.get("adresse") or ""),
                str(daten.get("modell") or ""),
                str(daten.get("schluessel") or ""),
                breite,
            )
        except (TypeError, ValueError):
            raise EinstellungenFehler("Die Einbettung lässt sich nicht bauen.") from None

    return bauen


def cache_fuer(sqlite: Path) -> Path:
    """Modell-Cache neben `mandanten/`, sonst im Ordner der SQLite-Datei."""
    mandant = sqlite.parent
    if mandant.parent.name == "mandanten":
        return mandant.parent.parent / "modell-cache"
    return mandant / "modell-cache"


def aus_kern(kern: object, fabrik: Fabrik | None = None) -> Einstellungen:
    """Datei `einstellungen.json` neben der SQLite-Datei des Kerns."""
    speicher = getattr(kern, "_speicher", None)
    pfad = getattr(speicher, "pfad", None)
    if pfad is None:
        raise EinstellungenFehler("Keine Einstellungen.", status=503)
    sqlite = Path(pfad)
    return Einstellungen(
        sqlite.parent / _DATEI,
        fabrik=fabrik,
        cache=cache_fuer(sqlite),
    )


class Einstellungen:
    """Eine JSON-Datei pro Mandant. Der Schlüssel steht nur dort."""

    def __init__(
        self,
        datei: str | Path,
        *,
        fabrik: Fabrik | None = None,
        cache: str | Path | None = None,
    ) -> None:
        self.datei = Path(datei)
        self._fabrik = fabrik
        self._cache = Path(cache) if cache is not None else self.datei.parent / "modell-cache"

    def __repr__(self) -> str:
        return f"Einstellungen(datei={self.datei.name!r})"

    def lesen(self, kern: object | None = None) -> dict:
        """Öffentliche Sicht. Enthält nie den Schlüssel.

        Ohne Datei gilt die Einbettung, mit der der Kern läuft. Erst ein
        Schreiben legt die Datei an.
        """
        intern = self._laden()
        if intern is None:
            return _oeffentlich(_ohne_datei(kern))
        return _oeffentlich(intern)

    def schreiben(self, daten: Mapping[str, object], kern: object | None = None) -> dict:
        """Speichert die Einstellung und hängt die neue Einbettung an den Kern."""
        if not isinstance(daten, Mapping):
            raise EinstellungenFehler("Der Inhalt muss ein Objekt sein.")
        neu = self._zusammen(self._laden(), daten)
        einbettung = self._bauen(neu)
        _uebernehmen(neu, einbettung)
        sperre = _sperre(kern)
        if sperre is None:
            self._anwenden(neu, einbettung, kern)
        else:
            with sperre:
                self._anwenden(neu, einbettung, kern)
        return _oeffentlich(neu)

    def fuer_start(self, sqlite: str | Path):
        """Einbettung zum Öffnen des Speichers. Ohne Datei die lokale.

        Weicht die Datei vom gespeicherten Modell ab, werden die Vektoren
        vorher neu berechnet. Sonst bleibt der Aufruf ohne Netz und ohne
        Gewichte.
        """
        intern = self._laden()
        if not _startbar(intern):
            einbettung = _lokale(self._cache)
        else:
            einbettung = self._bauen(intern)
        pfad = Path(sqlite)
        if pfad.is_file() and _meta_weicht_ab(pfad, einbettung):
            vektoren_neu_schreiben(pfad, einbettung)
        return einbettung

    def _anwenden(self, neu: dict, einbettung: object, kern: object | None) -> None:
        alt = self._lesen_roh()
        self._speichern(neu)
        try:
            if kern is not None and _weicht(kern, einbettung):
                vektoren_neu_schreiben(Path(kern._speicher.pfad), einbettung)
            if kern is not None:
                _umhaengen(kern, einbettung)
        except Exception:
            self._schreiben_roh(alt)
            raise

    def _bauen(self, daten: Mapping[str, object]):
        fabrik = self._fabrik if self._fabrik is not None else standard_fabrik(self._cache)
        try:
            einbettung = fabrik(daten)
        except EinstellungenFehler:
            raise
        except Exception:
            raise EinstellungenFehler("Die Einbettung lässt sich nicht bauen.") from None
        modell = getattr(einbettung, "modell", None)
        breite = getattr(einbettung, "breite", None)
        if not isinstance(modell, str) or modell.strip() == "":
            raise EinstellungenFehler("Der Modellname fehlt.")
        if isinstance(breite, bool) or not isinstance(breite, int) or breite < 1:
            raise EinstellungenFehler("Die Breite fehlt.")
        if not callable(getattr(einbettung, "vektoren", None)):
            raise EinstellungenFehler("Die Einbettung lässt sich nicht bauen.")
        return einbettung

    def _zusammen(self, alt: dict | None, daten: Mapping[str, object]) -> dict:
        basis = dict(alt) if alt is not None else _leer()
        if "einbettung" in daten:
            art = daten["einbettung"]
            if art not in ("lokal", "api"):
                raise EinstellungenFehler("Die Einbettung muss lokal oder api sein.")
            basis["einbettung"] = art
        if "adresse" in daten:
            basis["adresse"] = _text(daten["adresse"], "Die Adresse")
        if "modell" in daten:
            basis["modell"] = _text(daten["modell"], "Der Modellname")
        if "breite" in daten and daten["breite"] is not None:
            basis["breite"] = _breite(daten["breite"])
        if "schluessel" in daten and daten["schluessel"] not in (None, ""):
            if not isinstance(daten["schluessel"], str):
                raise EinstellungenFehler("Der Schlüssel muss Text sein.")
            _schluessel_ok(daten["schluessel"])
            basis["schluessel"] = daten["schluessel"]
        if basis["einbettung"] == "lokal":
            return basis
        if not basis["adresse"]:
            basis["adresse"] = ADRESSE_API
        _adresse_ok(basis["adresse"])
        if not basis["modell"]:
            raise EinstellungenFehler("Der Modellname fehlt.")
        if not basis["breite"]:
            raise EinstellungenFehler("Die Breite fehlt.")
        if not basis["schluessel"]:
            raise EinstellungenFehler("Der Schlüssel fehlt.")
        return basis

    def _laden(self) -> dict | None:
        roh = self._lesen_roh()
        if roh is None:
            return None
        try:
            daten = json.loads(roh.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            raise EinstellungenFehler(
                "Die Einstellungen sind unlesbar.",
                status=500,
            ) from None
        if not isinstance(daten, dict):
            raise EinstellungenFehler("Die Einstellungen sind unlesbar.", status=500)
        einbettung = daten.get("einbettung")
        if einbettung not in ("lokal", "api"):
            einbettung = "api"
        adresse = daten.get("adresse")
        modell = daten.get("modell")
        schluessel = daten.get("schluessel")
        breite = daten.get("breite")
        if isinstance(breite, bool) or not isinstance(breite, int) or breite < 1:
            breite = None
        return {
            "einbettung": einbettung,
            "adresse": adresse if isinstance(adresse, str) else "",
            "modell": modell if isinstance(modell, str) else "",
            "breite": breite,
            "schluessel": schluessel if isinstance(schluessel, str) else "",
        }

    def _lesen_roh(self) -> bytes | None:
        datei = self.datei
        if datei.is_symlink():
            raise EinstellungenFehler("Die Einstellungen dürfen kein Verweis sein.")
        if not datei.exists():
            return None
        try:
            return datei.read_bytes()
        except OSError:
            raise EinstellungenFehler(
                "Die Einstellungen sind unlesbar.",
                status=500,
            ) from None

    def _speichern(self, intern: dict) -> None:
        inhalt = {
            "einbettung": intern["einbettung"],
            "adresse": intern["adresse"],
            "modell": intern["modell"],
            "breite": intern["breite"],
            "schluessel": intern.get("schluessel") or "",
        }
        roh = (json.dumps(inhalt, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        self._schreiben_roh(roh)

    def _schreiben_roh(self, roh: bytes | None) -> None:
        datei = self.datei
        if datei.is_symlink():
            raise EinstellungenFehler("Die Einstellungen dürfen kein Verweis sein.")
        if roh is None:
            if datei.exists():
                try:
                    datei.unlink()
                except OSError:
                    raise EinstellungenFehler(
                        "Die Einstellungen konnten nicht geschrieben werden.",
                        status=500,
                    ) from None
            return
        try:
            datei.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise EinstellungenFehler(
                "Die Einstellungen konnten nicht geschrieben werden.",
                status=500,
            ) from None
        fd, tmp_name = tempfile.mkstemp(
            prefix=".einstellungen-",
            suffix=".teil",
            dir=datei.parent,
        )
        try:
            os.write(fd, roh)
            os.fchmod(fd, 0o600)
            os.fsync(fd)
        except Exception:
            os.close(fd)
            os.unlink(tmp_name)
            raise EinstellungenFehler(
                "Die Einstellungen konnten nicht geschrieben werden.",
                status=500,
            ) from None
        os.close(fd)
        try:
            os.replace(tmp_name, datei)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise EinstellungenFehler(
                "Die Einstellungen konnten nicht geschrieben werden.",
                status=500,
            ) from None
        os.chmod(datei, 0o600)


def vektoren_neu_schreiben(pfad: Path, einbettung: object) -> None:
    """Ersetzt alle Frage-, Formulierungs- und Gegenbeispiel-Vektoren."""
    conn = _verbinden(pfad)
    try:
        meta = {
            row["schluessel"]: row["wert"]
            for row in conn.execute("SELECT schluessel, wert FROM meta")
        }
        try:
            alt_breite = int(meta["breite"])
        except (KeyError, TypeError, ValueError):
            raise _neuaufbau() from None
        auftraege = _auftraege(conn)
        texte = [text for _art, _kennung, text in auftraege]
        vektoren = _einbetten(einbettung, texte)
        breite = int(einbettung.breite)
        if breite != alt_breite:
            _vec_neu(conn, breite)
        else:
            for tabelle in ("eintrag_vec", "frage_vec", "gegen_vec"):
                conn.execute(f"DELETE FROM {tabelle}")
        for (art, kennung, _text), vektor in zip(auftraege, vektoren, strict=True):
            _vec_einfuegen(conn, art, kennung, vektor)
        _meta_setzen(conn, "modell", str(einbettung.modell))
        _meta_setzen(conn, "breite", str(breite))
        conn.commit()
    except EinstellungenFehler:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise _neuaufbau() from None
    finally:
        conn.close()


def _oeffentlich(intern: Mapping[str, object]) -> dict:
    return {
        "einbettung": intern["einbettung"],
        "adresse": intern["adresse"],
        "modell": intern["modell"],
        "breite": intern["breite"],
        "schluessel_gesetzt": bool(intern.get("schluessel")),
    }


def _ohne_datei(kern: object | None) -> dict:
    """Laufende Einbettung, solange noch keine Datei geschrieben wurde."""
    if kern is None:
        return _leer()
    einbettung = getattr(kern, "_einbettung", None)
    modell = getattr(einbettung, "modell", None)
    breite = getattr(einbettung, "breite", None)
    if not isinstance(modell, str) or modell == "":
        return _leer()
    if isinstance(breite, bool) or not isinstance(breite, int) or breite < 1:
        return _leer()
    from .einbettung_lokal import MODELL as lokales_modell

    if modell == lokales_modell:
        return {
            "einbettung": "lokal",
            "adresse": "",
            "modell": modell,
            "breite": breite,
            "schluessel": "",
        }
    return {
        "einbettung": "api",
        "adresse": "",
        "modell": modell,
        "breite": breite,
        "schluessel": "",
    }


def _leer() -> dict:
    return {
        "einbettung": "api",
        "adresse": ADRESSE_API,
        "modell": "",
        "breite": None,
        "schluessel": "",
    }


def _startbar(intern: dict | None) -> bool:
    if intern is None:
        return False
    if intern["einbettung"] == "lokal":
        return True
    return bool(intern["schluessel"] and intern["modell"] and intern["breite"])


def _lokale(cache: Path):
    from .einbettung_lokal import LokaleEinbettung

    return LokaleEinbettung(cache)


def _uebernehmen(neu: dict, einbettung: object) -> None:
    if neu["einbettung"] == "lokal":
        neu["modell"] = einbettung.modell
        neu["breite"] = einbettung.breite
        return
    if neu["modell"] != einbettung.modell or neu["breite"] != einbettung.breite:
        raise EinstellungenFehler("Die Einbettung passt nicht zur Einstellung.")


def _weicht(kern: object, einbettung: object) -> bool:
    speicher = getattr(kern, "_speicher", None)
    if speicher is None:
        return False
    pfad = Path(speicher.pfad)
    if not pfad.is_file():
        return False
    return speicher.modell != einbettung.modell or speicher.breite != einbettung.breite


def _sperre(kern: object | None):
    if kern is None:
        return None
    speicher = getattr(kern, "_speicher", None)
    lock = getattr(speicher, "_lock", None)
    if not callable(getattr(lock, "acquire", None)) or not callable(
        getattr(lock, "release", None)
    ):
        return None
    return lock


def _umhaengen(kern: object, einbettung: object) -> None:
    kern._einbettung = einbettung
    speicher = getattr(kern, "_speicher", None)
    if speicher is None:
        return
    speicher.modell = einbettung.modell
    speicher.breite = einbettung.breite


def _text(wert: object, name: str) -> str:
    if not isinstance(wert, str):
        raise EinstellungenFehler(f"{name} muss Text sein.")
    return wert.strip()


def _breite(wert: object) -> int:
    if isinstance(wert, bool) or not isinstance(wert, int) or wert < 1:
        raise EinstellungenFehler("Die Breite muss eine positive ganze Zahl sein.")
    return wert


def _schluessel_ok(schluessel: str) -> None:
    try:
        roh = schluessel.encode("latin-1")
    except UnicodeEncodeError:
        raise EinstellungenFehler("Der Schlüssel ist ungültig.") from None
    if any(byte < 32 or byte == 127 for byte in roh):
        raise EinstellungenFehler("Der Schlüssel ist ungültig.")


def _adresse_ok(adresse: str) -> None:
    teile = urlsplit(adresse.strip())
    if teile.scheme not in {"http", "https"} or not teile.hostname:
        raise EinstellungenFehler("Die Adresse muss eine http- oder https-Adresse sein.")


def _meta_weicht_ab(pfad: Path, einbettung: object) -> bool:
    meta = _meta_lesen(pfad)
    if not meta:
        return False
    if meta.get("modell") != einbettung.modell:
        return True
    return meta.get("breite") != str(einbettung.breite)


def _meta_lesen(pfad: Path) -> dict[str, str] | None:
    conn = sqlite3.connect(pfad, timeout=10)
    try:
        rows = conn.execute("SELECT schluessel, wert FROM meta").fetchall()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    if not rows:
        return None
    return {str(row[0]): str(row[1]) for row in rows}


def _verbinden(pfad: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(pfad, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def _auftraege(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    zeilen: list[tuple[str, str, str]] = []
    for row in conn.execute(
        """
        SELECT eintrag.id AS id, eintrag.frage AS text
        FROM eintrag_vec
        JOIN eintrag ON eintrag.id = eintrag_vec.eintrag_id
        """
    ):
        zeilen.append(("eintrag", row["id"], row["text"]))
    for row in conn.execute("SELECT id, text FROM frage"):
        zeilen.append(("frage", row["id"], row["text"]))
    for row in conn.execute("SELECT id, frage AS text FROM gegen"):
        zeilen.append(("gegen", row["id"], row["text"]))
    return zeilen


def _einbetten(einbettung: object, texte: list[str]) -> list[list[float]]:
    if not texte:
        return []
    try:
        roh = list(einbettung.vektoren(list(texte)))
    except EinstellungenFehler:
        raise
    except Exception:
        raise _neuaufbau() from None
    if len(roh) != len(texte):
        raise _neuaufbau()
    breite = int(einbettung.breite)
    return [_vektor(eintrag, breite) for eintrag in roh]


def _vektor(roh: object, breite: int) -> list[float]:
    if isinstance(roh, (str, bytes)) or not isinstance(roh, (list, tuple)):
        raise _neuaufbau()
    zahlen: list[float] = []
    for wert in roh:
        if isinstance(wert, bool) or not isinstance(wert, (int, float)):
            raise _neuaufbau()
        zahl = float(wert)
        if not math.isfinite(zahl):
            raise _neuaufbau()
        zahlen.append(zahl)
    if len(zahlen) != breite:
        raise _neuaufbau()
    return zahlen


def _vec_neu(conn: sqlite3.Connection, breite: int) -> None:
    for name in ("eintrag_vec", "frage_vec", "gegen_vec"):
        conn.execute(f"DROP TABLE IF EXISTS {name}")
    conn.execute(
        f"""
        CREATE VIRTUAL TABLE eintrag_vec USING vec0(
            eintrag_id TEXT PRIMARY KEY,
            embedding float[{breite}] distance_metric=cosine
        )
        """
    )
    conn.execute(
        f"""
        CREATE VIRTUAL TABLE frage_vec USING vec0(
            frage_id TEXT PRIMARY KEY,
            embedding float[{breite}] distance_metric=cosine
        )
        """
    )
    conn.execute(
        f"""
        CREATE VIRTUAL TABLE gegen_vec USING vec0(
            gegen_id TEXT PRIMARY KEY,
            embedding float[{breite}] distance_metric=cosine
        )
        """
    )


def _vec_einfuegen(
    conn: sqlite3.Connection,
    art: str,
    kennung: str,
    vektor: list[float],
) -> None:
    blob = sqlite_vec.serialize_float32(vektor)
    if art == "eintrag":
        conn.execute(
            "INSERT INTO eintrag_vec (eintrag_id, embedding) VALUES (?, ?)",
            (kennung, blob),
        )
        return
    if art == "frage":
        conn.execute(
            "INSERT INTO frage_vec (frage_id, embedding) VALUES (?, ?)",
            (kennung, blob),
        )
        return
    conn.execute(
        "INSERT INTO gegen_vec (gegen_id, embedding) VALUES (?, ?)",
        (kennung, blob),
    )


def _meta_setzen(conn: sqlite3.Connection, schluessel: str, wert: str) -> None:
    conn.execute(
        """
        INSERT INTO meta (schluessel, wert) VALUES (?, ?)
        ON CONFLICT(schluessel) DO UPDATE SET wert = excluded.wert
        """,
        (schluessel, wert),
    )
