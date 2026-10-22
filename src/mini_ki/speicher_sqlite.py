"""SQLite-Speicher mit sqlite-vec. Eine Datei, Anhänge als Dateien daneben."""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import tempfile
import threading
import uuid
from pathlib import Path

import sqlite_vec

_SCHEMA = "1"
# Art und Kennung werden Pfadteile. `..`, Schrägstriche und Steuerzeichen bleiben draußen.
_ART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_EINTRAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


class ModellPasstNicht(Exception):
    """Modell oder Breite der Einbettung passt nicht zum Speicher."""

    def __init__(
        self,
        modell: str,
        breite: int,
        gespeichert_modell: str | None,
        gespeichert_breite: str | None,
    ) -> None:
        self.modell = modell
        self.breite = breite
        self.gespeichert_modell = gespeichert_modell
        self.gespeichert_breite = gespeichert_breite
        super().__init__(
            f"Einbettung {modell} ({breite}) passt nicht zum Speicher "
            f"{gespeichert_modell} ({gespeichert_breite})."
        )


def _pack(vektor: list[float]) -> bytes:
    return sqlite_vec.serialize_float32(vektor)


def _medientyp_ok(medientyp: str) -> bool:
    if not isinstance(medientyp, str) or not medientyp or len(medientyp) > 200:
        return False
    return not any(zeichen in medientyp for zeichen in "\r\n\x00")


def _text_pruefsumme(text: str) -> str:
    """Schlüssel zum Antworttext, aus dem ein Anhang entstand."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atomar_schreiben(ziel: Path, daten: bytes) -> None:
    """Schreibt über eine temporäre Datei im selben Ordner und benennt dann um."""
    if ziel.is_symlink():
        raise OSError("Anhang-Pfad ist ein Symlink.")
    ziel.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".", suffix=".teil", dir=ziel.parent)
    try:
        sichtbar = 0
        while sichtbar < len(daten):
            geschrieben = os.write(fd, daten[sichtbar:])
            if geschrieben <= 0:
                raise OSError("Anhang konnte nicht vollständig geschrieben werden.")
            sichtbar += geschrieben
        os.fsync(fd)
    except Exception:
        os.close(fd)
        os.unlink(tmp_name)
        raise
    os.close(fd)
    try:
        os.replace(tmp_name, ziel)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _sicher_lesen(ziel: Path) -> bytes | None:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(ziel, flags)
    except OSError:
        return None
    try:
        teile: list[bytes] = []
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            teile.append(block)
        return b"".join(teile)
    except OSError:
        return None
    finally:
        os.close(fd)


def _wiederherstellen(ziel: Path, alt: bytes | None, hatte_datei: bool) -> None:
    try:
        if ziel.is_symlink():
            return
        if hatte_datei and alt is not None:
            _atomar_schreiben(ziel, alt)
        elif ziel.is_file():
            ziel.unlink()
    except OSError:
        pass


class SqliteSpeicher:
    """Tabellen `eintrag`, `frage`, `gegen`, `ablehnung`, `anhang` und die Vektoren, plus `meta`."""

    def __init__(
        self,
        pfad: str | Path,
        modell: str,
        breite: int,
        lock: threading.Lock | None = None,
    ) -> None:
        if not isinstance(modell, str):
            raise TypeError("Der Modellname muss Text sein.")
        if isinstance(breite, bool) or not isinstance(breite, int) or breite < 1:
            raise ValueError("Die Breite muss eine positive ganze Zahl sein.")
        self.pfad = Path(pfad)
        self.modell = modell
        self.breite = breite
        self._lock = lock if lock is not None else threading.Lock()

    def bereitstellen(self) -> None:
        self._laufen(lambda conn: None)

    def einfuegen(
        self,
        eintrag_id: str,
        frage: str,
        antwort: str,
        bewertung: str | None,
        vektor: list[float],
    ) -> None:
        self._pruefe(vektor)
        gepackt = _pack(vektor)

        def fn(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                INSERT INTO eintrag (id, frage, antwort, bewertung)
                VALUES (?, ?, ?, ?)
                """,
                (eintrag_id, frage, antwort, bewertung),
            )
            conn.execute(
                "INSERT INTO eintrag_vec (eintrag_id, embedding) VALUES (?, ?)",
                (eintrag_id, gepackt),
            )

        self._laufen(fn)

    def bewertung_setzen(self, eintrag_id: str, bewertung: str) -> bool:
        def fn(conn: sqlite3.Connection) -> bool:
            cur = conn.execute(
                "UPDATE eintrag SET bewertung = ? WHERE id = ?",
                (bewertung, eintrag_id),
            )
            return cur.rowcount == 1

        return self._laufen(fn)

    def antwort_setzen(self, eintrag_id: str, antwort: str) -> bool:
        """Neuer Text. Anhänge zu diesem Eintrag fallen weg."""

        def fn(conn: sqlite3.Connection) -> list[Path] | None:
            cur = conn.execute(
                """
                UPDATE eintrag
                SET antwort = ?
                WHERE id = ? AND (bewertung IS NULL OR bewertung = 'gut')
                """,
                (antwort, eintrag_id),
            )
            if cur.rowcount != 1:
                return None
            return self._anhang_entfernen(conn, eintrag_id)

        ziele = self._laufen(fn)
        if ziele is None:
            return False
        self._dateien_weg(ziele)
        return True

    def lesen(self, eintrag_id: str) -> dict | None:
        def fn(conn: sqlite3.Connection) -> dict | None:
            row = conn.execute(
                "SELECT frage, antwort, bewertung FROM eintrag WHERE id = ?",
                (eintrag_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "frage": row["frage"],
                "antwort": row["antwort"],
                "bewertung": row["bewertung"],
            }

        return self._laufen(fn)

    def loeschen(self, eintrag_id: str) -> bool:
        def fn(conn: sqlite3.Connection) -> list[Path] | None:
            alt = conn.execute(
                "SELECT id FROM frage WHERE eintrag_id = ?",
                (eintrag_id,),
            ).fetchall()
            for row in alt:
                conn.execute(
                    "DELETE FROM frage_vec WHERE frage_id = ?",
                    (row["id"],),
                )
            conn.execute("DELETE FROM frage WHERE eintrag_id = ?", (eintrag_id,))
            conn.execute(
                "DELETE FROM ablehnung WHERE eintrag_id = ?",
                (eintrag_id,),
            )
            conn.execute(
                "DELETE FROM eintrag_vec WHERE eintrag_id = ?",
                (eintrag_id,),
            )
            cur = conn.execute("DELETE FROM eintrag WHERE id = ?", (eintrag_id,))
            if cur.rowcount != 1:
                return None
            return self._anhang_entfernen(conn, eintrag_id)

        ziele = self._laufen(fn)
        if ziele is None:
            return False
        self._dateien_weg(ziele)
        return True

    def anhang_setzen(
        self,
        eintrag_id: str,
        art: str,
        daten: bytes,
        medientyp: str,
    ) -> bool:
        """Legt die Bytes unter `anhaenge/<eintrag>/<art>` ab. Die Prüfsumme gehört zum Text."""
        if not isinstance(daten, bytes) or not _medientyp_ok(medientyp):
            return False
        ziel = self._anhang_ziel(eintrag_id, art)
        if ziel is None or ziel.is_symlink():
            return False

        def fn(conn: sqlite3.Connection) -> bool:
            row = conn.execute(
                "SELECT antwort FROM eintrag WHERE id = ?",
                (eintrag_id,),
            ).fetchone()
            if row is None:
                return False
            pruefsumme = _text_pruefsumme(row["antwort"])
            hatte_datei = ziel.is_file() and not ziel.is_symlink()
            alt = _sicher_lesen(ziel) if hatte_datei else None
            if hatte_datei and alt is None:
                return False
            try:
                _atomar_schreiben(ziel, daten)
                conn.execute(
                    """
                    INSERT INTO anhang (
                        eintrag_id, art, medientyp, groesse, pruefsumme
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(eintrag_id, art) DO UPDATE SET
                        medientyp = excluded.medientyp,
                        groesse = excluded.groesse,
                        pruefsumme = excluded.pruefsumme
                    """,
                    (eintrag_id, art, medientyp, len(daten), pruefsumme),
                )
            except Exception:
                _wiederherstellen(ziel, alt, hatte_datei)
                raise
            return True

        return self._laufen(fn)

    def anhang_lesen(self, eintrag_id: str, art: str) -> bytes | None:
        ziel = self._anhang_ziel(eintrag_id, art)
        if ziel is None:
            return None

        def fn(conn: sqlite3.Connection) -> bytes | None:
            row = conn.execute(
                """
                SELECT groesse FROM anhang
                WHERE eintrag_id = ? AND art = ?
                """,
                (eintrag_id, art),
            ).fetchone()
            if row is None:
                return None
            daten = _sicher_lesen(ziel)
            if daten is None or len(daten) != int(row["groesse"]):
                return None
            return daten

        return self._laufen(fn)

    def anhaenge_lesen(self, eintrag_id: str) -> list[dict]:
        if not isinstance(eintrag_id, str) or not _EINTRAG.fullmatch(eintrag_id):
            return []

        def fn(conn: sqlite3.Connection) -> list[dict]:
            rows = conn.execute(
                """
                SELECT art, medientyp, groesse, pruefsumme
                FROM anhang
                WHERE eintrag_id = ?
                ORDER BY art
                """,
                (eintrag_id,),
            ).fetchall()
            return [
                {
                    "art": row["art"],
                    "medientyp": row["medientyp"],
                    "groesse": int(row["groesse"]),
                    "pruefsumme": row["pruefsumme"],
                }
                for row in rows
            ]

        return self._laufen(fn)

    def gegen_merken(self, eintrag_id: str, frage: str, vektor: list[float]) -> None:
        self._pruefe(vektor)
        gepackt = _pack(vektor)
        gegen_id = uuid.uuid4().hex

        def fn(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO gegen (id, eintrag_id, frage) VALUES (?, ?, ?)",
                (gegen_id, eintrag_id, frage),
            )
            conn.execute(
                "INSERT INTO gegen_vec (gegen_id, embedding) VALUES (?, ?)",
                (gegen_id, gepackt),
            )

        self._laufen(fn)

    def ablehnung_merken(
        self,
        eintrag_id: str,
        frage: str,
        vektor: list[float],
        schwelle: int,
    ) -> dict | None:
        """Gegenbeispiel und Protokollzeile. None, wenn der Eintrag fehlt.

        Die Bewertung bleibt. Ab `schwelle` Zeilen wird `pruefung` gesetzt.
        """
        self._pruefe(vektor)
        if isinstance(schwelle, bool) or not isinstance(schwelle, int) or schwelle < 1:
            raise ValueError("Die Ablehnungs-Schwelle muss eine positive ganze Zahl sein.")
        gepackt = _pack(vektor)
        gegen_id = uuid.uuid4().hex
        ablehnung_id = uuid.uuid4().hex

        def fn(conn: sqlite3.Connection) -> dict | None:
            row = conn.execute(
                "SELECT id FROM eintrag WHERE id = ?",
                (eintrag_id,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "INSERT INTO gegen (id, eintrag_id, frage) VALUES (?, ?, ?)",
                (gegen_id, eintrag_id, frage),
            )
            conn.execute(
                "INSERT INTO gegen_vec (gegen_id, embedding) VALUES (?, ?)",
                (gegen_id, gepackt),
            )
            conn.execute(
                """
                INSERT INTO ablehnung (id, eintrag_id, frage)
                VALUES (?, ?, ?)
                """,
                (ablehnung_id, eintrag_id, frage),
            )
            zeit = conn.execute(
                "SELECT zeit FROM ablehnung WHERE id = ?",
                (ablehnung_id,),
            ).fetchone()["zeit"]
            anzahl = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM ablehnung WHERE eintrag_id = ?",
                    (eintrag_id,),
                ).fetchone()["n"]
            )
            pruefung = anzahl >= schwelle
            if pruefung:
                conn.execute(
                    "UPDATE eintrag SET pruefung = 1 WHERE id = ?",
                    (eintrag_id,),
                )
            return {"zeit": zeit, "anzahl": anzahl, "pruefung": pruefung}

        return self._laufen(fn)

    def ablehnungen_lesen(self, eintrag_id: str | None = None) -> list[dict]:
        def fn(conn: sqlite3.Connection) -> list[dict]:
            if eintrag_id is None:
                rows = conn.execute(_ABLEHNUNG_ALLE).fetchall()
            else:
                rows = conn.execute(_ABLEHNUNG_EINE, (eintrag_id,)).fetchall()
            return [
                {
                    "frage": row["frage"],
                    "eintrag": row["eintrag"],
                    "zeit": row["zeit"],
                    "pruefung": bool(row["pruefung"]),
                }
                for row in rows
            ]

        return self._laufen(fn)

    def formulierungen_ersetzen(
        self,
        eintrag_id: str,
        texte: list[str],
        vektoren: list[list[float]],
    ) -> int:
        if len(texte) != len(vektoren):
            raise ValueError("Je Formulierung braucht es einen Vektor.")
        for vektor in vektoren:
            self._pruefe(vektor)
        gepackt = [_pack(vektor) for vektor in vektoren]

        def fn(conn: sqlite3.Connection) -> int:
            row = conn.execute(
                "SELECT id FROM eintrag WHERE id = ?",
                (eintrag_id,),
            ).fetchone()
            if row is None:
                return 0
            conn.execute(
                "UPDATE eintrag SET frage = ? WHERE id = ?",
                (texte[0], eintrag_id),
            )
            alt = conn.execute(
                "SELECT id FROM frage WHERE eintrag_id = ?",
                (eintrag_id,),
            ).fetchall()
            for zeile in alt:
                conn.execute(
                    "DELETE FROM frage_vec WHERE frage_id = ?",
                    (zeile["id"],),
                )
            conn.execute("DELETE FROM frage WHERE eintrag_id = ?", (eintrag_id,))
            conn.execute(
                "DELETE FROM eintrag_vec WHERE eintrag_id = ?",
                (eintrag_id,),
            )
            for text, blob in zip(texte, gepackt):
                frage_id = uuid.uuid4().hex
                conn.execute(
                    "INSERT INTO frage (id, eintrag_id, text) VALUES (?, ?, ?)",
                    (frage_id, eintrag_id, text),
                )
                conn.execute(
                    "INSERT INTO frage_vec (frage_id, embedding) VALUES (?, ?)",
                    (frage_id, blob),
                )
            return len(texte)

        return self._laufen(fn)

    def gute_antworten(self) -> list[tuple[str, str]]:
        def fn(conn: sqlite3.Connection) -> list[tuple[str, str]]:
            rows = conn.execute(
                "SELECT id, antwort FROM eintrag WHERE bewertung = 'gut'"
            ).fetchall()
            return [(row["id"], row["antwort"]) for row in rows]

        return self._laufen(fn)

    def nahe(
        self, vektor: list[float]
    ) -> tuple[list[tuple[str, float]], list[tuple[str, str, float]]]:
        """Gegenbeispiele und Kandidaten, Kandidaten aufsteigend nach Abstand."""
        self._pruefe(vektor)
        gepackt = _pack(vektor)

        def fn(
            conn: sqlite3.Connection,
        ) -> tuple[list[tuple[str, float]], list[tuple[str, str, float]]]:
            gegen = [
                (row["id"], float(row["distance"]))
                for row in conn.execute(_GEGEN, (gepackt,))
            ]
            # Zuerst die Formulierungen, danach der Altfall ohne frage-Zeile.
            # Der Schnitt gilt nur für `gut`, nicht für die k nächsten Vektoren.
            zeilen = list(conn.execute(_FRAGE, (gepackt, _K_FRAGE)))
            abgedeckt = {row["id"] for row in zeilen}
            for row in conn.execute(_ALT, (gepackt, _K_ALT)):
                if row["id"] not in abgedeckt:
                    zeilen.append(row)
            zeilen.sort(key=lambda row: float(row["distance"]))
            kandidaten = [
                (row["id"], row["antwort"], float(row["distance"])) for row in zeilen
            ]
            return gegen, kandidaten

        return self._laufen(fn)

    def _anhang_wurzel(self) -> Path:
        return (self.pfad.resolve().parent / "anhaenge").resolve()

    def _anhang_ziel(self, eintrag_id: str, art: str) -> Path | None:
        """Nur `anhaenge/<eintrag>/<art>`. `..` und andere Ausbrüche sind kein Ziel."""
        if (
            not isinstance(eintrag_id, str)
            or not isinstance(art, str)
            or not _EINTRAG.fullmatch(eintrag_id)
            or not _ART.fullmatch(art)
        ):
            return None
        wurzel = self._anhang_wurzel()
        ziel = (wurzel / eintrag_id / art).resolve()
        try:
            relativ = ziel.relative_to(wurzel)
        except ValueError:
            return None
        if relativ.parts != (eintrag_id, art):
            return None
        return ziel

    def _anhang_entfernen(self, conn: sqlite3.Connection, eintrag_id: str) -> list[Path]:
        rows = conn.execute(
            "SELECT art FROM anhang WHERE eintrag_id = ?",
            (eintrag_id,),
        ).fetchall()
        conn.execute("DELETE FROM anhang WHERE eintrag_id = ?", (eintrag_id,))
        ziele: list[Path] = []
        for row in rows:
            ziel = self._anhang_ziel(eintrag_id, row["art"])
            if ziel is not None:
                ziele.append(ziel)
        return ziele

    def _dateien_weg(self, ziele: list[Path]) -> None:
        wurzel = self._anhang_wurzel()
        for ziel in ziele:
            try:
                ziel.resolve().relative_to(wurzel)
            except (ValueError, OSError):
                continue
            try:
                if ziel.is_symlink() or ziel.is_file():
                    ziel.unlink()
            except OSError:
                continue
            eltern = ziel.parent
            if eltern == wurzel:
                continue
            try:
                eltern.resolve().relative_to(wurzel)
                eltern.rmdir()
            except (ValueError, OSError):
                pass

    def _pruefe(self, vektor: list[float]) -> None:
        if len(vektor) != self.breite:
            raise ValueError(
                f"Vektor hat Breite {len(vektor)}, der Speicher erwartet {self.breite}."
            )

    def _laufen(self, fn):
        with self._lock:
            conn = self._verbinden()
            try:
                ergebnis = fn(conn)
                conn.commit()
                return ergebnis
            except Exception:
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
                raise
            finally:
                conn.close()

    def _verbinden(self) -> sqlite3.Connection:
        self.pfad.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.pfad, timeout=10)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL").fetchone()
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
            self._meta_und_tabellen(conn)
            conn.commit()
        except Exception:
            conn.close()
            raise
        return conn

    def _meta_und_tabellen(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                schluessel TEXT PRIMARY KEY,
                wert TEXT NOT NULL
            )
            """
        )
        vorhanden = {
            row["schluessel"]: row["wert"]
            for row in conn.execute("SELECT schluessel, wert FROM meta")
        }
        if not vorhanden:
            conn.executemany(
                "INSERT INTO meta (schluessel, wert) VALUES (?, ?)",
                (
                    ("modell", self.modell),
                    ("breite", str(self.breite)),
                    ("schema", _SCHEMA),
                ),
            )
        else:
            gespeichert_modell = vorhanden.get("modell")
            gespeichert_breite = vorhanden.get("breite")
            try:
                breite_zahl = (
                    int(gespeichert_breite) if gespeichert_breite is not None else None
                )
            except ValueError:
                breite_zahl = None
            if gespeichert_modell != self.modell or breite_zahl != self.breite:
                raise ModellPasstNicht(
                    self.modell,
                    self.breite,
                    gespeichert_modell,
                    gespeichert_breite,
                )
        self._tabellen(conn)

    def _tabellen(self, conn: sqlite3.Connection) -> None:
        breite = self.breite
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS eintrag (
                id TEXT PRIMARY KEY,
                frage TEXT NOT NULL,
                antwort TEXT NOT NULL,
                bewertung TEXT,
                art TEXT DEFAULT 'antwort',
                erstellt TEXT DEFAULT (datetime('now')),
                pruefung INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS eintrag_vec USING vec0(
                eintrag_id TEXT PRIMARY KEY,
                embedding float[{breite}] distance_metric=cosine
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS frage (
                id TEXT PRIMARY KEY,
                eintrag_id TEXT NOT NULL,
                text TEXT NOT NULL
            )
            """
        )
        conn.execute(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS frage_vec USING vec0(
                frage_id TEXT PRIMARY KEY,
                embedding float[{breite}] distance_metric=cosine
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS gegen (
                id TEXT PRIMARY KEY,
                eintrag_id TEXT NOT NULL,
                frage TEXT NOT NULL
            )
            """
        )
        conn.execute(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS gegen_vec USING vec0(
                gegen_id TEXT PRIMARY KEY,
                embedding float[{breite}] distance_metric=cosine
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS anhang (
                eintrag_id TEXT NOT NULL,
                art TEXT NOT NULL,
                medientyp TEXT NOT NULL,
                groesse INTEGER NOT NULL,
                pruefsumme TEXT NOT NULL,
                PRIMARY KEY (eintrag_id, art)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ablehnung (
                id TEXT PRIMARY KEY,
                eintrag_id TEXT NOT NULL,
                frage TEXT NOT NULL,
                zeit TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS ablehnung_eintrag
            ON ablehnung (eintrag_id)
            """
        )
        spalten = {row["name"] for row in conn.execute("PRAGMA table_info(eintrag)")}
        if "pruefung" not in spalten:
            conn.execute(
                "ALTER TABLE eintrag ADD COLUMN pruefung INTEGER NOT NULL DEFAULT 0"
            )


# So viele gute Nachbarn wie bisher. Der Schnitt liegt auf `gut`, nicht auf
# allen Vektoren: sqlite-vec wendet `k` vor dem Filter an und lässt höchstens
# 4096 zu. Nähere unbewertete oder schlechte Zeilen würden den Treffer sonst
# aus dem Fenster drücken. `vec_distance_cosine` ist derselbe Kosinusabstand
# wie `distance_metric=cosine` in den vec0-Tabellen.
_K_FRAGE = 8
_K_ALT = 5

_GEGEN = """
SELECT gegen.eintrag_id AS id, gegen_vec.distance AS distance
FROM gegen_vec
JOIN gegen ON gegen.id = gegen_vec.gegen_id
WHERE gegen_vec.embedding MATCH ?
  AND k = 8
ORDER BY gegen_vec.distance
"""

_FRAGE = """
SELECT frage.eintrag_id AS id,
       vec_distance_cosine(frage_vec.embedding, ?) AS distance,
       eintrag.antwort AS antwort
FROM frage_vec
JOIN frage ON frage.id = frage_vec.frage_id
JOIN eintrag ON eintrag.id = frage.eintrag_id
WHERE eintrag.bewertung = 'gut'
ORDER BY distance
LIMIT ?
"""

_ALT = """
SELECT eintrag_vec.eintrag_id AS id,
       vec_distance_cosine(eintrag_vec.embedding, ?) AS distance,
       eintrag.antwort AS antwort
FROM eintrag_vec
JOIN eintrag ON eintrag.id = eintrag_vec.eintrag_id
WHERE eintrag.bewertung = 'gut'
ORDER BY distance
LIMIT ?
"""

_ABLEHNUNG = """
SELECT ablehnung.frage AS frage,
       ablehnung.eintrag_id AS eintrag,
       ablehnung.zeit AS zeit,
       COALESCE(eintrag.pruefung, 0) AS pruefung
FROM ablehnung
LEFT JOIN eintrag ON eintrag.id = ablehnung.eintrag_id
"""

# `rowid` bleibt die Reihenfolge, auch wenn `datetime('now')` in derselben Sekunde liegt.
_ABLEHNUNG_ALLE = _ABLEHNUNG + "ORDER BY ablehnung.rowid"

_ABLEHNUNG_EINE = (
    _ABLEHNUNG + "WHERE ablehnung.eintrag_id = ? ORDER BY ablehnung.rowid"
)
