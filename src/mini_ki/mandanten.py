"""Mandanten. Ein Kern pro Kunde, eine lokale Einbettung für alle.

Die Mandanten-ID passt auf `[a-z0-9-]{1,64}`. Der Ordner liegt unter
`<daten>/mandanten/<id>/` und kommt nie außerhalb dieses Stamms.
Kunden-Schlüssel stehen nur als HMAC-SHA-256 mit eigenem Salt in
`mandanten-zugang.json`, nie im Klartext.

Anlegen, Sperren und Vergessen gehören zur Verwaltung
(`python -m mini_ki.mandanten`), nicht zur Kunden-API.
Ohne Einträge in der Zugangsdatei gibt es genau den Mandanten `standard`.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import tempfile
import threading
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from pathlib import Path

from .einstellungen import Einstellungen, standard_fabrik
from .kern import MiniKI

STANDARD = "standard"
ZUGANG_DATEI = "mandanten-zugang.json"
_ID = re.compile(r"^[a-z0-9-]{1,64}$")
_HEX = re.compile(r"^[0-9a-f]+$")
_SALT_LAENGE = 32
_HASH_LAENGE = 64


class MandantenFehler(Exception):
    """ID, Ordner oder Zugangsdatei sind ungültig. Der Text nennt keinen Schlüssel."""


class MandantUnbekannt(MandantenFehler):
    """Kein Mandant zu diesem Schlüssel, oder der Mandant ist nicht angelegt."""

    def __init__(self) -> None:
        super().__init__("Der Mandant ist unbekannt.")


class MandantGesperrt(MandantenFehler):
    """Der Schlüssel stimmt, der Mandant ist gesperrt."""

    def __init__(self, mandant_id: str) -> None:
        self.mandant_id = mandant_id
        super().__init__("Der Mandant ist gesperrt.")


def id_gueltig(mandant_id: object) -> bool:
    """Nur Kleinbuchstaben, Ziffern und Bindestrich. Kein `..`, kein Pfad."""
    if not isinstance(mandant_id, str) or not _ID.fullmatch(mandant_id):
        return False
    if ".." in mandant_id or "/" in mandant_id or "\\" in mandant_id:
        return False
    return True


def _digest(salt: bytes, schluessel: str) -> str:
    return hmac.new(salt, schluessel.encode("utf-8"), hashlib.sha256).hexdigest()


def _einbettung_ok(einbettung: object) -> None:
    modell = getattr(einbettung, "modell", None)
    breite = getattr(einbettung, "breite", None)
    if not isinstance(modell, str) or modell.strip() == "":
        raise MandantenFehler("Die Einbettung lässt sich nicht bauen.")
    if isinstance(breite, bool) or not isinstance(breite, int) or breite < 1:
        raise MandantenFehler("Die Einbettung lässt sich nicht bauen.")
    if not callable(getattr(einbettung, "vektoren", None)):
        raise MandantenFehler("Die Einbettung lässt sich nicht bauen.")


def _hex_feld(wert: object, laenge: int) -> str:
    if not isinstance(wert, str) or len(wert) != laenge or not _HEX.fullmatch(wert):
        raise MandantenFehler("Die Zugangsdatei ist unlesbar.")
    return wert


def _parsen(roh: bytes) -> dict:
    try:
        daten = json.loads(roh.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise MandantenFehler("Die Zugangsdatei ist unlesbar.") from None
    if not isinstance(daten, dict) or not isinstance(daten.get("eintraege"), list):
        raise MandantenFehler("Die Zugangsdatei ist unlesbar.")
    eintraege: list[dict] = []
    gesehen: set[str] = set()
    for eintrag in daten["eintraege"]:
        if not isinstance(eintrag, dict):
            raise MandantenFehler("Die Zugangsdatei ist unlesbar.")
        mandant_id = eintrag.get("id")
        if not id_gueltig(mandant_id) or mandant_id in gesehen:
            raise MandantenFehler("Die Zugangsdatei ist unlesbar.")
        gesehen.add(mandant_id)
        eintraege.append(
            {
                "id": mandant_id,
                "salt": _hex_feld(eintrag.get("salt"), _SALT_LAENGE),
                "hash": _hex_feld(str(eintrag.get("hash", "")).lower(), _HASH_LAENGE)
                if isinstance(eintrag.get("hash"), str)
                else _hex_feld(eintrag.get("hash"), _HASH_LAENGE),
                "gesperrt": eintrag.get("gesperrt") is True,
            }
        )
    return {"fassung": 1, "eintraege": eintraege}


def _baum_loeschen(ziel: Path, basis: Path) -> None:
    """Löscht den Ordner. Verweise werden entfernt, ihr Ziel bleibt stehen."""
    for kind in list(ziel.iterdir()):
        if kind.is_symlink() or not kind.is_dir():
            kind.unlink()
            continue
        try:
            kind.resolve().relative_to(basis)
        except ValueError:
            raise MandantenFehler("Der Mandanten-Ordner liegt außerhalb.") from None
        _baum_loeschen(kind, basis)
    ziel.rmdir()


class Mandanten:
    """Registry. Ein `MiniKI` pro Mandant, die lokale Einbettung nur einmal."""

    def __init__(
        self,
        wurzel: str | Path,
        *,
        einbettung: object | None = None,
        fabrik: Callable[[], object] | None = None,
    ) -> None:
        if einbettung is not None and fabrik is not None:
            raise TypeError("Einbettung und Fabrik schließen sich aus.")
        angegeben = Path(wurzel).expanduser()
        if angegeben.is_symlink():
            raise MandantenFehler("Der Datenordner darf kein Verweis sein.")
        self.wurzel = angegeben.resolve()
        if self.wurzel.exists() and not self.wurzel.is_dir():
            raise MandantenFehler("Der Datenordner muss ein Ordner sein.")
        if einbettung is not None:
            _einbettung_ok(einbettung)
        self._geteilt = einbettung
        self._fabrik = fabrik
        self.ladungen = 0
        self._kerne: dict[str, MiniKI] = {}
        self._einstellungen: dict[str, Einstellungen] = {}
        self._lock = threading.RLock()
        self._einstellungs_fabrik = self._bau_fabrik()

    def __repr__(self) -> str:
        return f"Mandanten(wurzel={self.wurzel.name!r})"

    @property
    def cache(self) -> Path:
        return self.wurzel / "modell-cache"

    @property
    def _datei(self) -> Path:
        return self.wurzel / ZUGANG_DATEI

    def konfiguriert(self) -> bool:
        """Wahr, sobald mindestens ein Mandant einen Schlüssel hat."""
        if not self._datei.exists() and not self._datei.is_symlink():
            return False
        return bool(self._snapshot())

    def ordner(self, mandant_id: str) -> Path:
        """Ordner des Mandanten. Legt ihn nicht an und folgt keinem Verweis."""
        return self._pfad(mandant_id, anlegen=False)

    def anlegen(self, mandant_id: str) -> str:
        """Neuer Mandant. Der Schlüssel wird nur hier zurückgegeben."""
        if not id_gueltig(mandant_id):
            raise MandantenFehler("Die Mandanten-ID ist ungültig.")
        schluessel = secrets.token_urlsafe(32)
        salt = secrets.token_bytes(16)
        digest = _digest(salt, schluessel)
        with self._lock:
            self._pfad(mandant_id, anlegen=True)

            def hinzu(daten: dict) -> None:
                if any(eintrag["id"] == mandant_id for eintrag in daten["eintraege"]):
                    raise MandantenFehler("Der Mandant ist schon da.")
                daten["eintraege"].append(
                    {
                        "id": mandant_id,
                        "salt": salt.hex(),
                        "hash": digest,
                        "gesperrt": False,
                    }
                )

            self._aendern(hinzu)
        return schluessel

    def sperren(self, mandant_id: str) -> None:
        self._flag(mandant_id, True)

    def freigeben(self, mandant_id: str) -> None:
        self._flag(mandant_id, False)

    def vergessen(self, mandant_id: str) -> bool:
        """Löscht genau den Ordner dieses Mandanten und seinen Schlüssel."""
        if not id_gueltig(mandant_id):
            raise MandantenFehler("Die Mandanten-ID ist ungültig.")
        with self._lock:
            self._kerne.pop(mandant_id, None)
            self._einstellungen.pop(mandant_id, None)
            entfernt = False

            def weg(daten: dict) -> None:
                nonlocal entfernt
                vorher = len(daten["eintraege"])
                daten["eintraege"] = [
                    eintrag for eintrag in daten["eintraege"] if eintrag["id"] != mandant_id
                ]
                entfernt = len(daten["eintraege"]) != vorher

            if self._datei.exists() or self._datei.is_symlink():
                self._aendern(weg)
            ordner_weg = self._ordner_weg(mandant_id)
            return entfernt or ordner_weg

    def zuordnen(self, schluessel: str) -> str:
        """Mandanten-ID zum Schlüssel. Gesperrt ist ein eigener Fehler."""
        if not isinstance(schluessel, str) or schluessel == "" or len(schluessel) > 256:
            raise MandantUnbekannt()
        try:
            roh = schluessel.encode("utf-8")
        except UnicodeEncodeError:
            raise MandantUnbekannt() from None
        getroffen: str | None = None
        gesperrt = False
        for eintrag in self._snapshot():
            salt = bytes.fromhex(eintrag["salt"])
            digest = hmac.new(salt, roh, hashlib.sha256).hexdigest()
            if hmac.compare_digest(digest, eintrag["hash"]) and getroffen is None:
                getroffen = eintrag["id"]
                gesperrt = eintrag["gesperrt"]
        if getroffen is None:
            raise MandantUnbekannt()
        if gesperrt:
            raise MandantGesperrt(getroffen)
        return getroffen

    def kern(self, mandant_id: str) -> MiniKI:
        """Kern zum Mandanten, beim ersten Zugriff angelegt."""
        if not id_gueltig(mandant_id):
            raise MandantenFehler("Die Mandanten-ID ist ungültig.")
        with self._lock:
            self._erlaubt(mandant_id)
            vorhanden = self._kerne.get(mandant_id)
            if vorhanden is not None:
                return vorhanden
            kern, einstellungen = self._oeffnen(mandant_id)
            self._erlaubt(mandant_id)
            self._kerne[mandant_id] = kern
            self._einstellungen[mandant_id] = einstellungen
            return kern

    def einstellungen(self, mandant_id: str) -> Einstellungen:
        self.kern(mandant_id)
        with self._lock:
            einstellungen = self._einstellungen.get(mandant_id)
            if einstellungen is None:
                raise MandantUnbekannt()
            return einstellungen

    def gemeinsam(self) -> object:
        """Die eine lokale Einbettung. Die Fabrik läuft höchstens einmal."""
        if self._geteilt is not None:
            return self._geteilt
        with self._lock:
            if self._geteilt is None:
                neu = self._neue_einbettung()
                _einbettung_ok(neu)
                self._geteilt = neu
                self.ladungen += 1
            return self._geteilt

    def _erlaubt(self, mandant_id: str) -> None:
        if self._hat_eintraege():
            eintrag = self._finde(mandant_id)
            if eintrag is None:
                raise MandantUnbekannt()
            if eintrag["gesperrt"]:
                raise MandantGesperrt(mandant_id)
            return
        if mandant_id != STANDARD:
            raise MandantUnbekannt()

    def _hat_eintraege(self) -> bool:
        if not self._datei.exists() and not self._datei.is_symlink():
            return False
        return bool(self._snapshot())

    def _finde(self, mandant_id: str) -> dict | None:
        for eintrag in self._snapshot():
            if eintrag["id"] == mandant_id:
                return eintrag
        return None

    def _oeffnen(self, mandant_id: str) -> tuple[MiniKI, Einstellungen]:
        ordner = self._pfad(mandant_id, anlegen=True)
        anhaenge = ordner / "anhaenge"
        if anhaenge.is_symlink():
            raise MandantenFehler("Der Anhang-Ordner darf kein Verweis sein.")
        anhaenge.mkdir(exist_ok=True)
        sqlite = ordner / "mini-ki.sqlite"
        if sqlite.is_symlink():
            raise MandantenFehler("Die Datenbank darf kein Verweis sein.")
        einstellungen = Einstellungen(
            ordner / "einstellungen.json",
            fabrik=self._einstellungs_fabrik,
            cache=self.cache,
        )
        einbettung = self._einbettung_waehlen(einstellungen, sqlite)
        return MiniKI(sqlite, einbettung), einstellungen

    def _einbettung_waehlen(self, einstellungen: Einstellungen, sqlite: Path) -> object:
        datei = einstellungen.datei
        if not datei.exists():
            return self.gemeinsam()
        if datei.is_symlink():
            raise MandantenFehler("Die Einstellungen dürfen kein Verweis sein.")
        sicht = einstellungen.lesen()
        api = (
            sicht.get("einbettung") == "api"
            and sicht.get("schluessel_gesetzt")
            and sicht.get("modell")
            and sicht.get("breite")
        )
        if api or sicht.get("einbettung") == "lokal":
            return einstellungen.fuer_start(sqlite)
        return self.gemeinsam()

    def _neue_einbettung(self) -> object:
        if self._fabrik is not None:
            return self._fabrik()
        from .einbettung_lokal import LokaleEinbettung

        return LokaleEinbettung(self.cache)

    def _bau_fabrik(self):
        basis = standard_fabrik(self.cache)

        def bauen(daten: Mapping[str, object]):
            if daten.get("einbettung") == "lokal":
                return self.gemeinsam()
            return basis(daten)

        return bauen

    def _flag(self, mandant_id: str, gesperrt: bool) -> None:
        if not id_gueltig(mandant_id):
            raise MandantenFehler("Die Mandanten-ID ist ungültig.")

        def setzen(daten: dict) -> None:
            for eintrag in daten["eintraege"]:
                if eintrag["id"] == mandant_id:
                    eintrag["gesperrt"] = gesperrt
                    return
            raise MandantenFehler("Der Mandant fehlt.")

        with self._lock:
            self._aendern(setzen)

    def _snapshot(self) -> list[dict]:
        with self._lock:
            if not self._datei.exists() and not self._datei.is_symlink():
                return []
            with self._exklusiv():
                return [dict(eintrag) for eintrag in self._lesen()["eintraege"]]

    def _aendern(self, fn: Callable[[dict], None]) -> None:
        with self._exklusiv():
            daten = self._lesen()
            fn(daten)
            self._schreiben(daten)

    @contextmanager
    def _exklusiv(self):
        self.wurzel.mkdir(parents=True, exist_ok=True)
        if self.wurzel.is_symlink() or not self.wurzel.is_dir():
            raise MandantenFehler("Der Datenordner muss ein Ordner sein.")
        fh = open(self.wurzel / ".mandanten-zugang.lock", "a+")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            fh.close()

    def _lesen(self) -> dict:
        datei = self._datei
        if not datei.exists() and not datei.is_symlink():
            return {"fassung": 1, "eintraege": []}
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(datei, flags)
        except OSError:
            raise MandantenFehler("Die Zugangsdatei ist unlesbar.") from None
        try:
            teile: list[bytes] = []
            while True:
                block = os.read(fd, 1024 * 1024)
                if not block:
                    break
                teile.append(block)
        finally:
            os.close(fd)
        return _parsen(b"".join(teile))

    def _schreiben(self, daten: dict) -> None:
        datei = self._datei
        if datei.is_symlink():
            raise MandantenFehler("Die Zugangsdatei darf kein Verweis sein.")
        roh = (json.dumps(daten, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        fd, tmp_name = tempfile.mkstemp(
            prefix=".mandanten-zugang-",
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
            raise MandantenFehler("Die Zugangsdatei konnte nicht geschrieben werden.") from None
        os.close(fd)
        try:
            os.replace(tmp_name, datei)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise MandantenFehler("Die Zugangsdatei konnte nicht geschrieben werden.") from None
        os.chmod(datei, 0o600)

    def _basis(self) -> Path:
        if self.wurzel.is_symlink() or (self.wurzel.exists() and not self.wurzel.is_dir()):
            raise MandantenFehler("Der Datenordner muss ein Ordner sein.")
        self.wurzel.mkdir(parents=True, exist_ok=True)
        basis = self.wurzel / "mandanten"
        if basis.is_symlink():
            raise MandantenFehler("Der Mandanten-Ordner darf kein Verweis sein.")
        basis.mkdir(exist_ok=True)
        if basis.is_symlink() or not basis.is_dir():
            raise MandantenFehler("Der Mandanten-Ordner darf kein Verweis sein.")
        aufgeloest = basis.resolve()
        try:
            aufgeloest.relative_to(self.wurzel.resolve())
        except ValueError:
            raise MandantenFehler("Der Mandanten-Ordner liegt außerhalb.") from None
        if aufgeloest.parent != self.wurzel.resolve():
            raise MandantenFehler("Der Mandanten-Ordner liegt außerhalb.")
        return aufgeloest

    def _pfad(self, mandant_id: str, *, anlegen: bool) -> Path:
        if not id_gueltig(mandant_id):
            raise MandantenFehler("Die Mandanten-ID ist ungültig.")
        basis = self._basis()
        ziel = basis / mandant_id
        if ziel.is_symlink():
            raise MandantenFehler("Der Mandanten-Ordner darf kein Verweis sein.")
        if ziel.exists() and not ziel.is_dir():
            raise MandantenFehler("Der Mandanten-Ordner muss ein Ordner sein.")
        if anlegen:
            ziel.mkdir(exist_ok=True)
            if ziel.is_symlink() or not ziel.is_dir():
                raise MandantenFehler("Der Mandanten-Ordner darf kein Verweis sein.")
        aufgeloest = ziel.resolve()
        try:
            relativ = aufgeloest.relative_to(basis)
        except ValueError:
            raise MandantenFehler("Der Mandanten-Ordner liegt außerhalb.") from None
        if relativ.parts != (mandant_id,):
            raise MandantenFehler("Der Mandanten-Ordner liegt außerhalb.")
        return aufgeloest

    def _ordner_weg(self, mandant_id: str) -> bool:
        ziel = self._pfad(mandant_id, anlegen=False)
        if ziel.is_symlink():
            ziel.unlink()
            return True
        if not ziel.exists():
            return False
        if not ziel.is_dir():
            raise MandantenFehler("Der Mandanten-Ordner muss ein Ordner sein.")
        _baum_loeschen(ziel, ziel.parent)
        return True


def _wurzel_aus(daten: str | None) -> Path:
    from mini_ki.stapel import daten_wurzel

    return daten_wurzel(daten)


def haupt(argv: list[str] | None = None) -> int:
    """Verwaltung im Container. `anlegen` gibt den Schlüssel einmal auf stdout aus."""
    parser = argparse.ArgumentParser(
        prog="mini-ki-mandanten",
        description="Mandanten anlegen, sperren oder vergessen. Nicht die Kunden-API.",
    )
    parser.add_argument("--daten", default=None, help="Datenordner, sonst MINI_KI_DATA oder /data")
    befehle = parser.add_subparsers(dest="befehl", required=True)
    for name, hilfe in (
        ("anlegen", "Mandant anlegen und den Schlüssel einmal ausgeben"),
        ("sperren", "Mandant sperren"),
        ("freigeben", "Mandant wieder freigeben"),
        ("vergessen", "Mandant und genau seinen Ordner löschen"),
    ):
        teil = befehle.add_parser(name, help=hilfe)
        teil.add_argument("mandant")
    args = parser.parse_args(argv)
    try:
        mandanten = Mandanten(_wurzel_aus(args.daten))
        if args.befehl == "anlegen":
            sys.stdout.write(mandanten.anlegen(args.mandant) + "\n")
            return 0
        if args.befehl == "sperren":
            mandanten.sperren(args.mandant)
            return 0
        if args.befehl == "freigeben":
            mandanten.freigeben(args.mandant)
            return 0
        if not mandanten.vergessen(args.mandant):
            sys.stderr.write("Der Mandant fehlt.\n")
            return 1
        return 0
    except (MandantenFehler, ValueError, OSError) as fehler:
        sys.stderr.write(f"{fehler}\n")
        return 1


if __name__ == "__main__":
    sys.exit(haupt())
