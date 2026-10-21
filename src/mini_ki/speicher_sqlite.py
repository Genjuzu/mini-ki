"""SQLite-Speicher mit sqlite-vec. Eine Datei, kein globaler Zustand."""

from __future__ import annotations

import sqlite3
import threading
import uuid
from pathlib import Path

import sqlite_vec

_SCHEMA = "1"


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


class SqliteSpeicher:
    """Tabellen `eintrag`, `frage`, `gegen` und ihre Vektoren, plus `meta`."""

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
        def fn(conn: sqlite3.Connection) -> bool:
            cur = conn.execute(
                """
                UPDATE eintrag
                SET antwort = ?
                WHERE id = ? AND (bewertung IS NULL OR bewertung = 'gut')
                """,
                (antwort, eintrag_id),
            )
            return cur.rowcount == 1

        return self._laufen(fn)

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
        def fn(conn: sqlite3.Connection) -> bool:
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
                "DELETE FROM eintrag_vec WHERE eintrag_id = ?",
                (eintrag_id,),
            )
            cur = conn.execute("DELETE FROM eintrag WHERE id = ?", (eintrag_id,))
            return cur.rowcount == 1

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
            zeilen = list(conn.execute(_FRAGE, (gepackt,)))
            abgedeckt = {row["id"] for row in zeilen}
            for row in conn.execute(_ALT, (gepackt,)):
                if row["id"] not in abgedeckt:
                    zeilen.append(row)
            zeilen.sort(key=lambda row: float(row["distance"]))
            kandidaten = [
                (row["id"], row["antwort"], float(row["distance"])) for row in zeilen
            ]
            return gegen, kandidaten

        return self._laufen(fn)

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
                erstellt TEXT DEFAULT (datetime('now'))
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


_GEGEN = """
SELECT gegen.eintrag_id AS id, gegen_vec.distance AS distance
FROM gegen_vec
JOIN gegen ON gegen.id = gegen_vec.gegen_id
WHERE gegen_vec.embedding MATCH ?
  AND k = 8
ORDER BY gegen_vec.distance
"""

_FRAGE = """
SELECT frage.eintrag_id AS id, frage_vec.distance AS distance, eintrag.antwort AS antwort
FROM frage_vec
JOIN frage ON frage.id = frage_vec.frage_id
JOIN eintrag ON eintrag.id = frage.eintrag_id
WHERE eintrag.bewertung = 'gut' AND frage_vec.embedding MATCH ?
  AND k = 8
ORDER BY frage_vec.distance
"""

_ALT = """
SELECT eintrag_vec.eintrag_id AS id, eintrag_vec.distance AS distance, eintrag.antwort AS antwort
FROM eintrag_vec
JOIN eintrag ON eintrag.id = eintrag_vec.eintrag_id
WHERE eintrag.bewertung = 'gut' AND eintrag_vec.embedding MATCH ?
  AND k = 5
ORDER BY eintrag_vec.distance
"""
