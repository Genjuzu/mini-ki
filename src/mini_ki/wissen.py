"""Wissensspeicher. Dokumente und Abschnitte in einer eigenen SQLite-Datei.

Der Pfad und die Einbettung kommen beim Erzeugen herein. Die Einbettung hat
dieselbe Schnittstelle wie im Kern: Modellname, Breite, `vektoren`.
Passt Modell oder Breite nicht zu `meta`, bricht das Öffnen ab.
"""

from __future__ import annotations

import re
import sqlite3
import threading
import uuid
from pathlib import Path

import sqlite_vec

from .einbettung import Einbettung
from .speicher_sqlite import ModellPasstNicht

_SCHEMA = "1"
_STATUS_NEU = "neu"
_STAPEL = 32
# So viele Kandidaten je Verfahren, mindestens aber `anzahl`.
# sqlite-vec wendet `k` vor einem Filter an. Der Kosinusabstand über die
# Abschnitte und ein Limit danach lässt `dokumente` korrekt eingrenzen.
_SUCH_FENSTER = 20
# Reciprocal Rank Fusion, Rangkonstante wie bei Cormack, Clarke und Büttcher.
_RRF_K = 60
_TOKEN_MAX = 32
_NAME_MAX = 500
_TYP_MAX = 200
_STATUS_MAX = 64
_STELLE_MAX = 500
_FEHLER_MAX = 2000
_GROESSE_MAX = 2**63 - 1

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_UNVERAENDERT = object()


def _pack(vektor: list[float]) -> bytes:
    return sqlite_vec.serialize_float32(vektor)


def _kennung(wert: object) -> str:
    if not isinstance(wert, str):
        raise TypeError("Die Kennung muss Text sein.")
    text = wert.strip()
    if not text:
        raise ValueError("Die Kennung fehlt.")
    return text


def _kurztext(wert: object, name: str, grenze: int) -> str:
    if not isinstance(wert, str):
        raise TypeError(f"{name} muss Text sein.")
    text = wert.strip()
    if not text or len(text) > grenze:
        raise ValueError(f"{name} fehlt oder ist zu lang.")
    if any(ord(zeichen) < 32 or zeichen == "\x7f" for zeichen in text):
        raise ValueError(f"{name} enthält ungültige Zeichen.")
    return text


def _groesse(wert: object) -> int:
    if isinstance(wert, bool) or not isinstance(wert, int) or wert < 0:
        raise ValueError("Die Größe muss eine ganze Zahl ab 0 sein.")
    if wert > _GROESSE_MAX:
        raise ValueError("Die Größe ist zu groß.")
    return wert


def _fortschritt_pruefen(wert: object) -> int:
    if isinstance(wert, bool) or not isinstance(wert, int) or not 0 <= wert <= 100:
        raise ValueError("Der Fortschritt muss eine ganze Zahl von 0 bis 100 sein.")
    return wert


def _fehlertext(wert: object) -> str | None:
    if wert is None:
        return None
    if not isinstance(wert, str):
        raise TypeError("Der Fehler muss Text sein.")
    text = wert.strip()
    if not text:
        return None
    if len(text) > _FEHLER_MAX:
        raise ValueError("Der Fehlertext ist zu lang.")
    if any(
        (ord(zeichen) < 32 and zeichen not in "\n\t") or zeichen == "\x7f"
        for zeichen in text
    ):
        raise ValueError("Der Fehler enthält ungültige Zeichen.")
    return text


def _stelle_lesen(roh: dict, nr: int) -> str:
    if "stelle" not in roh or roh["stelle"] is None:
        return str(nr)
    stelle = roh["stelle"]
    if not isinstance(stelle, str):
        raise TypeError("Die Stelle muss Text sein.")
    text = stelle.strip()
    if not text:
        return str(nr)
    if len(text) > _STELLE_MAX:
        raise ValueError("Die Stelle ist zu lang.")
    if any(ord(zeichen) < 32 or zeichen == "\x7f" for zeichen in text):
        raise ValueError("Die Stelle enthält ungültige Zeichen.")
    return text


def _abschnitte_lesen(abschnitte: object) -> list[tuple[int, str, str]]:
    if isinstance(abschnitte, (str, bytes)) or not isinstance(abschnitte, (list, tuple)):
        raise TypeError("Abschnitte sind eine Liste.")
    zeilen: list[tuple[int, str, str]] = []
    gesehen: set[int] = set()
    for index, roh in enumerate(abschnitte):
        if not isinstance(roh, dict):
            raise TypeError("Ein Abschnitt ist ein Wörterbuch.")
        if "nr" in roh and roh["nr"] is not None:
            nr = roh["nr"]
            if isinstance(nr, bool) or not isinstance(nr, int) or nr < 0:
                raise ValueError(
                    "Die Abschnittsnummer muss eine ganze Zahl ab 0 sein."
                )
        else:
            nr = index + 1
        if nr in gesehen:
            raise ValueError("Die Abschnittsnummer ist doppelt.")
        gesehen.add(nr)
        text = roh.get("text")
        if not isinstance(text, str):
            raise TypeError("Der Abschnittstext muss Text sein.")
        if "\x00" in text:
            raise ValueError("Der Abschnittstext enthält ein Nullzeichen.")
        text = text.strip()
        if not text:
            raise ValueError("Der Abschnittstext fehlt.")
        zeilen.append((nr, _stelle_lesen(roh, nr), text))
    return zeilen


def _suchausdruck(frage: str) -> str | None:
    """Wörter der Frage als sichere FTS5-Oder-Verknüpfung. Bindestriche trennen."""
    gesehen: set[str] = set()
    teile: list[str] = []
    for token in _TOKEN.findall(frage):
        schluessel = token.casefold()
        if schluessel in gesehen:
            continue
        gesehen.add(schluessel)
        teile.append('"' + token.replace('"', '""') + '"')
        if len(teile) == _TOKEN_MAX:
            break
    if not teile:
        return None
    return " OR ".join(teile)


def _dokumente_lesen(dokumente: object) -> list[str] | None:
    if dokumente is None:
        return None
    if isinstance(dokumente, (str, bytes)) or not isinstance(dokumente, (list, tuple)):
        raise TypeError("dokumente ist eine Liste von Kennungen.")
    return [_kennung(eintrag) for eintrag in dokumente]


def _platz(spalte: str, anzahl: int) -> str:
    return f"{spalte} IN ({', '.join('?' * anzahl)})"


def _zeile(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "typ": row["typ"],
        "bytes": int(row["bytes"]),
        "status": row["status"],
        "fortschritt": int(row["fortschritt"]),
        "fehler": row["fehler"],
        "erstellt": row["erstellt"],
    }


def _abschnitte_weg(conn: sqlite3.Connection, dokument_id: str) -> None:
    conn.execute(
        """
        DELETE FROM abschnitt_vec
        WHERE abschnitt_id IN (
            SELECT id FROM abschnitt WHERE dokument_id = ?
        )
        """,
        (dokument_id,),
    )
    conn.execute(
        "DELETE FROM abschnitt_fts WHERE dokument_id = ?",
        (dokument_id,),
    )
    conn.execute("DELETE FROM abschnitt WHERE dokument_id = ?", (dokument_id,))


class Wissensspeicher:
    """Dokumente, ihre Abschnitte und die Suche darüber.

    `abschnitte_ablegen` bettet in Stapeln ein und ersetzt die bisherigen
    Abschnitte des Dokuments. `suchen` mischt Vektor- und FTS5-Rangliste.
    """

    def __init__(
        self,
        pfad: str | Path,
        einbettung: Einbettung,
        *,
        stapelgroesse: int = _STAPEL,
    ) -> None:
        modell = getattr(einbettung, "modell", None)
        breite = getattr(einbettung, "breite", None)
        if not isinstance(modell, str):
            raise TypeError("Der Modellname muss Text sein.")
        if isinstance(breite, bool) or not isinstance(breite, int) or breite < 1:
            raise ValueError("Die Breite muss eine positive ganze Zahl sein.")
        if not callable(getattr(einbettung, "vektoren", None)):
            raise TypeError("Die Einbettung braucht vektoren.")
        if (
            isinstance(stapelgroesse, bool)
            or not isinstance(stapelgroesse, int)
            or stapelgroesse < 1
        ):
            raise ValueError("Die Stapelgröße muss eine positive ganze Zahl sein.")
        self.pfad = Path(pfad)
        self.modell = modell
        self.breite = breite
        self._einbettung = einbettung
        self._stapelgroesse = stapelgroesse
        self._lock = threading.Lock()
        self._bereitstellen()

    def dokument_anlegen(self, name: str, typ: str, bytes: int) -> str:
        """Neue Dokumentzeile. Status `neu`, Fortschritt 0, ohne Fehler."""
        name = _kurztext(name, "Der Name", _NAME_MAX)
        typ = _kurztext(typ, "Der Typ", _TYP_MAX)
        groesse = _groesse(bytes)
        dokument_id = uuid.uuid4().hex

        def fn(conn: sqlite3.Connection) -> str:
            conn.execute(
                """
                INSERT INTO dokument (
                    id, name, typ, "bytes", status, fortschritt, fehler
                )
                VALUES (?, ?, ?, ?, ?, 0, NULL)
                """,
                (dokument_id, name, typ, groesse, _STATUS_NEU),
            )
            return dokument_id

        return self._laufen(fn)

    def abschnitte_ablegen(self, dokument_id: str, abschnitte: list) -> int:
        """Ersetzt die Abschnitte. Der Text wird in Stapeln eingebettet.

        Jeder Eintrag ist ein Wörterbuch mit `text`. `nr` und `stelle` sind
        optional. Fehlt das Dokument, bleibt der Speicher unverändert.
        """
        dokument_id = _kennung(dokument_id)
        zeilen = _abschnitte_lesen(abschnitte)
        if self.holen(dokument_id) is None:
            raise ValueError("Das Dokument fehlt.")
        blobs = self._einbetten([text for _, _, text in zeilen])

        def fn(conn: sqlite3.Connection) -> int:
            if not _dokument_da(conn, dokument_id):
                raise ValueError("Das Dokument fehlt.")
            _abschnitte_weg(conn, dokument_id)
            for (nr, stelle, text), blob in zip(zeilen, blobs):
                abschnitt_id = uuid.uuid4().hex
                conn.execute(
                    """
                    INSERT INTO abschnitt (id, dokument_id, nr, stelle, text)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (abschnitt_id, dokument_id, nr, stelle, text),
                )
                conn.execute(
                    """
                    INSERT INTO abschnitt_vec (abschnitt_id, embedding)
                    VALUES (?, ?)
                    """,
                    (abschnitt_id, blob),
                )
                conn.execute(
                    """
                    INSERT INTO abschnitt_fts (abschnitt_id, dokument_id, text)
                    VALUES (?, ?, ?)
                    """,
                    (abschnitt_id, dokument_id, text),
                )
            return len(zeilen)

        return self._laufen(fn)

    def status_setzen(
        self,
        dokument_id: str,
        status: str,
        *,
        fortschritt: int | None = None,
        fehler: object = _UNVERAENDERT,
    ) -> bool:
        """Setzt den Status. Ohne Fortschritt oder Fehler bleiben sie stehen.

        `fehler=None` löscht den Fehlertext. Fehlt das Dokument, kommt False
        zurück.
        """
        dokument_id = _kennung(dokument_id)
        status = _kurztext(status, "Der Status", _STATUS_MAX)
        if fortschritt is not None:
            fortschritt = _fortschritt_pruefen(fortschritt)
        fehler_setzen = fehler is not _UNVERAENDERT
        if fehler_setzen:
            fehler = _fehlertext(fehler)

        def fn(conn: sqlite3.Connection) -> bool:
            felder = ["status = ?"]
            werte: list = [status]
            if fortschritt is not None:
                felder.append("fortschritt = ?")
                werte.append(fortschritt)
            if fehler_setzen:
                felder.append("fehler = ?")
                werte.append(fehler)
            werte.append(dokument_id)
            cur = conn.execute(
                f"UPDATE dokument SET {', '.join(felder)} WHERE id = ?",
                werte,
            )
            return cur.rowcount == 1

        return self._laufen(fn)

    def liste(self) -> list[dict]:
        """Alle Dokumente in der Reihenfolge des Anlegens."""

        def fn(conn: sqlite3.Connection) -> list[dict]:
            rows = conn.execute(
                """
                SELECT id, name, typ, "bytes", status, fortschritt, fehler, erstellt
                FROM dokument
                ORDER BY rowid
                """
            ).fetchall()
            return [_zeile(row) for row in rows]

        return self._laufen(fn)

    def holen(self, dokument_id: str) -> dict | None:
        """Eine Dokumentzeile, oder None."""
        dokument_id = _kennung(dokument_id)

        def fn(conn: sqlite3.Connection) -> dict | None:
            row = conn.execute(
                """
                SELECT id, name, typ, "bytes", status, fortschritt, fehler, erstellt
                FROM dokument
                WHERE id = ?
                """,
                (dokument_id,),
            ).fetchone()
            if row is None:
                return None
            return _zeile(row)

        return self._laufen(fn)

    def loeschen(self, dokument_id: str) -> bool:
        """Dokument, Abschnitte, Vektoren und FTS-Einträge. False, wenn es fehlt."""
        dokument_id = _kennung(dokument_id)

        def fn(conn: sqlite3.Connection) -> bool:
            if not _dokument_da(conn, dokument_id):
                return False
            _abschnitte_weg(conn, dokument_id)
            cur = conn.execute("DELETE FROM dokument WHERE id = ?", (dokument_id,))
            return cur.rowcount == 1

        return self._laufen(fn)

    def suchen(
        self,
        frage: str,
        anzahl: int = 5,
        dokumente: list[str] | None = None,
    ) -> list[dict]:
        """Mischt Vektor- und FTS5-Treffer. Leer, wenn die Frage leer ist.

        Rückgabe: `dokument_id`, `dokument`, `stelle`, `text`, `aehnlichkeit`.
        """
        if not isinstance(frage, str):
            raise TypeError("Die Frage muss Text sein.")
        frage = frage.strip()
        if not frage:
            return []
        if isinstance(anzahl, bool) or not isinstance(anzahl, int) or anzahl < 1:
            raise ValueError("Die Anzahl muss eine positive ganze Zahl sein.")
        ids = _dokumente_lesen(dokumente)
        if ids is not None and not ids:
            return []
        blob = self._einbetten([frage])[0]
        fenster = max(anzahl, _SUCH_FENSTER)

        def fn(conn: sqlite3.Connection) -> list[dict]:
            vektoren = self._vektor_treffer(conn, blob, fenster, ids)
            volltext = self._fts_treffer(conn, frage, fenster, ids)
            return _mischen(vektoren, volltext, anzahl)

        return self._laufen(fn)

    def _bereitstellen(self) -> None:
        self._laufen(lambda conn: None)

    def _einbetten(self, texte: list[str]) -> list[bytes]:
        if not texte:
            return []
        blobs: list[bytes] = []
        schritt = self._stapelgroesse
        for start in range(0, len(texte), schritt):
            teil = texte[start : start + schritt]
            roh = self._einbettung.vektoren(teil)
            try:
                vektoren = list(roh)
            except TypeError:
                raise ValueError(
                    "Einbettung lieferte nicht einen Vektor pro Text."
                ) from None
            if len(vektoren) != len(teil):
                raise ValueError("Einbettung lieferte nicht einen Vektor pro Text.")
            for vektor in vektoren:
                self._pruefe_vektor(vektor)
                blobs.append(_pack(vektor))
        return blobs

    def _pruefe_vektor(self, vektor: object) -> None:
        if isinstance(vektor, (str, bytes)):
            raise TypeError("Ein Vektor ist eine Liste von Zahlen.")
        try:
            laenge = len(vektor)  # type: ignore[arg-type]
        except TypeError:
            raise TypeError("Ein Vektor ist eine Liste von Zahlen.") from None
        if laenge != self.breite:
            raise ValueError(
                f"Vektor hat Breite {laenge}, der Speicher erwartet {self.breite}."
            )

    def _vektor_treffer(
        self,
        conn: sqlite3.Connection,
        blob: bytes,
        fenster: int,
        ids: list[str] | None,
    ) -> list[sqlite3.Row]:
        sql = _VEKTOR
        werte: list = [blob]
        if ids:
            sql += f" WHERE {_platz('abschnitt.dokument_id', len(ids))}"
            werte.extend(ids)
        sql += " ORDER BY distance LIMIT ?"
        werte.append(fenster)
        return list(conn.execute(sql, werte))

    def _fts_treffer(
        self,
        conn: sqlite3.Connection,
        frage: str,
        fenster: int,
        ids: list[str] | None,
    ) -> list[sqlite3.Row]:
        ausdruck = _suchausdruck(frage)
        if ausdruck is None:
            return []
        sql = _FTS
        werte: list = [ausdruck]
        if ids:
            sql += f" AND {_platz('abschnitt.dokument_id', len(ids))}"
            werte.extend(ids)
        sql += " ORDER BY gewicht LIMIT ?"
        werte.append(fenster)
        return list(conn.execute(sql, werte))

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
            CREATE TABLE IF NOT EXISTS dokument (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                typ TEXT NOT NULL,
                "bytes" INTEGER NOT NULL,
                status TEXT NOT NULL,
                fortschritt INTEGER NOT NULL,
                fehler TEXT,
                erstellt TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS abschnitt (
                id TEXT PRIMARY KEY,
                dokument_id TEXT NOT NULL,
                nr INTEGER NOT NULL,
                stelle TEXT NOT NULL,
                text TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS abschnitt_dokument
            ON abschnitt (dokument_id)
            """
        )
        conn.execute(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS abschnitt_vec USING vec0(
                abschnitt_id TEXT PRIMARY KEY,
                embedding float[{breite}] distance_metric=cosine
            )
            """
        )
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS abschnitt_fts USING fts5(
                abschnitt_id UNINDEXED,
                dokument_id UNINDEXED,
                text,
                tokenize = 'unicode61'
            )
            """
        )


def _dokument_da(conn: sqlite3.Connection, dokument_id: str) -> bool:
    row = conn.execute(
        "SELECT id FROM dokument WHERE id = ?",
        (dokument_id,),
    ).fetchone()
    return row is not None


def _aehnlichkeit(distanz: float) -> float:
    return min(1.0, max(0.0, round(1.0 - distanz, 3)))


def _mischen(
    vektoren: list[sqlite3.Row],
    volltext: list[sqlite3.Row],
    anzahl: int,
) -> list[dict]:
    sammlung: dict[str, dict] = {}

    def holen(row: sqlite3.Row) -> dict:
        eintrag = sammlung.get(row["id"])
        if eintrag is None:
            eintrag = {
                "dokument_id": row["dokument_id"],
                "dokument": row["dokument"],
                "stelle": row["stelle"],
                "text": row["text"],
                "aehnlichkeit": 0.0,
                "nr": int(row["nr"]),
                "score": 0.0,
            }
            sammlung[row["id"]] = eintrag
        return eintrag

    for rang, row in enumerate(vektoren, start=1):
        eintrag = holen(row)
        eintrag["score"] += 1.0 / (_RRF_K + rang)
        eintrag["aehnlichkeit"] = _aehnlichkeit(float(row["distance"]))
    for rang, row in enumerate(volltext, start=1):
        eintrag = holen(row)
        eintrag["score"] += 1.0 / (_RRF_K + rang)
    geordnet = sorted(
        sammlung.values(),
        key=lambda eintrag: (
            -eintrag["score"],
            -eintrag["aehnlichkeit"],
            eintrag["nr"],
            eintrag["dokument_id"],
        ),
    )
    return [
        {
            "dokument_id": eintrag["dokument_id"],
            "dokument": eintrag["dokument"],
            "stelle": eintrag["stelle"],
            "text": eintrag["text"],
            "aehnlichkeit": eintrag["aehnlichkeit"],
        }
        for eintrag in geordnet[:anzahl]
    ]


_VEKTOR = """
SELECT abschnitt.id AS id,
       abschnitt.dokument_id AS dokument_id,
       dokument.name AS dokument,
       abschnitt.stelle AS stelle,
       abschnitt.text AS text,
       abschnitt.nr AS nr,
       vec_distance_cosine(abschnitt_vec.embedding, ?) AS distance
FROM abschnitt_vec
JOIN abschnitt ON abschnitt.id = abschnitt_vec.abschnitt_id
JOIN dokument ON dokument.id = abschnitt.dokument_id
"""

_FTS = """
SELECT abschnitt.id AS id,
       abschnitt.dokument_id AS dokument_id,
       dokument.name AS dokument,
       abschnitt.stelle AS stelle,
       abschnitt.text AS text,
       abschnitt.nr AS nr,
       bm25(abschnitt_fts) AS gewicht
FROM abschnitt_fts
JOIN abschnitt ON abschnitt.id = abschnitt_fts.abschnitt_id
JOIN dokument ON dokument.id = abschnitt.dokument_id
WHERE abschnitt_fts MATCH ?
"""
