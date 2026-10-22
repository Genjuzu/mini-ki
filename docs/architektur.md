# Architektur

Stand: 2026-10-21. Die vier Weichen unter `entscheidungen/` (Laufzeit, Einbettung, Daumen runter, Audio) sind entschieden von Wudu im Chat, 2026-10-21.

## Wozu

Mini-KI ist ein Baustein, den man in jedes Projekt stecken kann. Jede Antwort bekommt Daumen hoch oder Daumen runter. Daumen hoch legt Frage, Vektor und Antwort ab. Kommt später eine ähnliche Frage, kommt die Antwort aus dem lokalen Speicher. Sprachmodell und Stimme werden für diesen Turn nicht gerufen.

## Pipeline

1. **Extraktion.** Der Antwortspeicher läuft schon im Live-Avatar-Prototyp (Repo `avatari-live`, Ordner `agent/`). Die Logik wird von dort herausgelöst. Messwerte und Fehler aus dem Bau kommen mit (`LEARNING.md` dort).
2. **Baustein.** In diesem Repository entsteht daraus ein Kern ohne Projekt-Kopplung, eine dünne HTTP-API und ein Docker-Compose-Stapel.
3. **AVA.** AVA (Repo `avataribot`, TypeScript) bindet Mini-KI ein. Daumen in der Oberfläche, Einstellung für den Embedding-Schlüssel.
4. **Live-Avatar.** Später spricht der Live-Avatar mit AVA als Backend. Gecachte Antworten bringen ihr Audio mit. Die Stimme wird für sie nicht neu bezahlt.

## Was im Prototyp schon läuft

Gemessen und gebaut im Prototyp, Stand 2026-10-08:

- Speicher: eine SQLite-Datei pro Avatar, Vektorsuche in derselben Datei mit sqlite-vec, Kosinus.
- Modell: `paraphrase-multilingual-MiniLM-L12-v2`, 384 Dimensionen, Deutsch, Apache-2.0, lokal über fastembed. Die Gewichte liegen in einem Cache-Ordner, nicht im Image.
- Schwelle 0,80 für einen Treffer. Gegenbeispiel 0,93, enger als der Treffer.
- Eine Antwort, viele Formulierungen. Jede Formulierung hat einen eigenen Vektor.
- Kurze Verweise („Ja, dazu …“) schreibt ein kleines Sprachmodell vor der Suche in eine allein stehende Frage um.
- Gleiche Antwort trotz anderer Frage: mindestens zwei Drittel gleiche Wörter gilt als derselbe Eintrag.
- Sperre: E-Mail, Telefonnummer und IBAN kommen nie in den Speicher.
- Bewertung, Stift (Text ändern), Neu erzeugen mit Zusatz, Entkoppeln (Gegenbeispiel), Vergessen.

Nicht gebaut im Prototyp: das Audio im Speicher. Der Plan dort sagt, das PCM wird abgelegt, sobald die Stimme an ist.

## Wo der Prototyp gekoppelt ist

Das bleibt beim Avatar und kommt nicht in den Kern:

- LiveKit: Datenthemen `ava.regen`, `ava.formen`, `ava.memory`, `ava.cut`, das Paket `buttons`, der Agent-Hook vor dem Sprachmodell mit 0,4 Sekunden Limit.
- Globale Zustände: Pfad aus `CACHE_PATH`, Modell als Prozess-Singleton, eine globale Sperre.
- Feste Werte im Code: Modellname, Breite 384, Schwellen.
- Sprachmodell für Formulierungen und Umschreiben: fest OpenRouter mit einem festen Modell.
- Stimme: KugelAudio-Schalter in der kleinen Webseite.

## Schichten

```text
Projekt (AVA, Live-Avatar, ...)
   |  HTTP  oder  Python-Import
   v
api      dünne HTTP-API, Einstellungen, Schlüssel
   v
kern     finden, merken, bewerten, umschreiben, neu, trennen, formen, vergessen, anhaenge
   |-- einbettung   Schnittstelle: lokal (ONNX/fastembed) | API (OpenAI-kompatibel, z. B. OpenRouter) | Test
   |-- speicher     Schnittstelle: SQLite + sqlite-vec (erste Fassung) | später andere
   |-- wissen       Dokumente und Abschnitte, eigene Datei, Vektor und FTS5
   |-- sperre       Musterfilter vor jedem Schreiben und Suchen
   '-- sprachmodell optional: Formulierungen, Verweis umschreiben, neue Antwort
```

Der Kern kennt kein LiveKit, keine Umgebungsvariable und keinen festen Pfad. Alles kommt beim Erzeugen herein.

## Kern

Ein Objekt pro Speicher. Sprache der Aufrufe wie im Blueprint des Prototyps.

| Aufruf | Wirkung |
| --- | --- |
| `finden(frage)` | nur `gut`, Gegenbeispiele überspringen, erster Treffer ab `schwelle`. Rückgabe Kennung, Antwort, Ähnlichkeit, Anhänge |
| `merken(frage, antwort, bewertung=None)` | neuer Eintrag, Vektor nur aus der Frage |
| `bewerten(id, gut\|schlecht)` | setzt die Bewertung |
| `ablehnen(id, frage, herkunft)` | Daumen runter nach Entscheidung: neue Antwort → `schlecht`; Cache-Treffer → nur für diese Anfrage gesperrt, Ablehnung protokolliert (#17) |
| `umschreiben(id, antwort)` | neuer Text, Vektor bleibt. Anhänge zu diesem Text verfallen |
| `neu(id, zusatz)` | Sprachmodell schreibt dieselbe Antwort neu, `finden` bleibt aus |
| `trennen(frage, id)` | Gegenbeispiel: diese Frage trifft diesen Eintrag nicht mehr |
| `formen(id, fragen)` | mehrere Formulierungen, je ein Vektor |
| `gleiche_antwort(text)` | derselbe `gut`-Eintrag trotz anderer Frage |
| `vergessen(id)` | Eintrag, Formulierungen, Vektoren und Anhänge weg |
| `anhang_setzen(id, art, daten)` / `anhang_lesen(id, art)` | beliebige Anhänge pro Eintrag, zum Beispiel Audio |

Schwellen sind Einstellungen mit den gemessenen Werten als Voreinstellung. Sie gehören zum Modell. Wer das Modell wechselt, misst neu.

## Einbettung

Eine Schnittstelle: Modellname, Breite, Texte rein, Vektoren raus.

- **Lokal**: das Modell aus dem Prototyp über fastembed (ONNX, CPU). Kein Schlüssel, kein Netz nach dem ersten Laden. Gewichte im Volume, nie im Repository oder Image.
- Entschieden: **Voreinstellung API** (OpenRouter-Schlüssel, eingetragen in AVAs Einstellungen), **lokal per Umschalter**.
- **API**: OpenAI-kompatibler Endpunkt `/embeddings`. OpenRouter bietet ihn unter `https://openrouter.ai/api/v1/embeddings` an. Adresse, Modell und Schlüssel sind Einstellungen. Der Schlüssel wird nie zurückgegeben und nie geloggt.
- **Test**: feste Vektoren, damit Tests ohne Modell und ohne Netz laufen.

Vektoren zweier Modelle passen nicht zusammen. Der Speicher merkt sich Modell und Breite. Passt das nicht zur Einstellung, startet der Kern nicht still weiter. Er meldet den Wechsel. Weil Fragen als Text gespeichert sind, kann ein Neuaufbau alle Vektoren mit dem neuen Modell neu rechnen.

## Speicher

Erste Fassung wie im Prototyp: eine SQLite-Datei pro Mandant (#15), sqlite-vec in derselben Datei. Tabellen `eintrag` (Antwort, Bewertung, Art), `frage` + `frage_vec`, `gegen` + `gegen_vec`, `meta` (Modell, Breite, Schema-Fassung), `anhang`.

`art` ist zuerst `antwort`. Später kommt `ablauf` dazu, für wiederverwendbare Workflows. Ein Ablauf trägt seine Schritte als JSON in einem eigenen Feld. Das ist nicht die erste Fassung.

## Wissensspeicher

Neben dem Antwortspeicher liegt eine eigene Datei `wissen.sqlite`. Der Pfad kommt beim Erzeugen herein. Vorgesehen ist sie im Mandanten-Ordner neben `mini-ki.sqlite`. Die Einbettung ist dasselbe Objekt wie beim Kern. Ein Projekt erzeugt den Speicher selbst, mit Pfad und Einbettung.

| Tabelle | Inhalt |
| --- | --- |
| `dokument` | Kennung, Name, Typ, Größe (`bytes`), Status, Fortschritt, Fehler, Zeitpunkt |
| `abschnitt` | Kennung, Dokument, Nummer, Stelle, Text |
| `abschnitt_vec` | sqlite-vec, Kosinus, ein Vektor pro Abschnitt |
| `abschnitt_fts` | FTS5 über den Abschnittstext |
| `meta` | Modell, Breite, Schema-Fassung |

Ein neues Dokument startet mit Status `neu`, Fortschritt 0 und ohne Fehler. `abschnitte_ablegen` ersetzt die Abschnitte dieses Dokuments und bettet den Text in Stapeln ein. `status_setzen` schreibt den Status, optional den Fortschritt von 0 bis 100 und den Fehler. `liste` und `holen` lesen die Dokumentzeile. `loeschen` entfernt das Dokument, seine Abschnitte, die Vektoren und die FTS-Einträge.

`suchen(frage, anzahl=5, dokumente=None)` mischt die nächsten Vektoren und die FTS5-Treffer. Die Mischung ist Reciprocal Rank Fusion: Rang `r` zählt `1 / (60 + r)`, die Summe bestimmt die Reihenfolge. Ein Treffer trägt `dokument_id`, `dokument` (der Name), `stelle`, `text` und `aehnlichkeit`. Die Ähnlichkeit ist der Kosinus, oder 0, wenn der Abschnitt nicht unter den Vektor-Kandidaten war. `dokumente` ist eine Liste von Kennungen und grenzt beide Ranglisten ein. Ohne Liste gilt der ganze Speicher.

Passt Modell oder Breite in `meta` nicht zur Einbettung, bricht das Öffnen mit `ModellPasstNicht` ab.

Zerlegen, Hochladen und die Buch-Schnittstelle sind nicht dieser Speicher. Er nimmt Abschnitte entgegen, die der Aufrufer schon geschnitten hat.

## Anhänge

Ein Eintrag kann Anhänge haben. Ein Anhang hat eine Art (`audio`, später andere), einen Medientyp (Audio: `audio/ogg; codecs=opus`), eine Größe und einen Schlüssel zum Text, aus dem er entstand. Die Bytes liegen als Datei neben der SQLite-Datei, nicht in der Datenbank.

Regel: Ändert sich der Text, passt das Audio nicht mehr. `umschreiben` und `neu` entfernen die Anhänge. Ein Treffer liefert die Anhänge mit. Audio wird als Opus (Ogg) gespeichert, nicht als PCM: etwa 0,1 statt 2,9 MB pro Minute (#16). Der Live-Avatar spielt nur ab. Fehlt das Audio, entscheidet das Projekt, ob es die Stimme neu kauft. Mini-KI kauft keine Stimme.

## HTTP-API

Dünn über dem Kern. Voreingestellt nur auf dem Gerät erreichbar. Jeder Aufruf trägt einen Kunden-Schlüssel (`Authorization: Bearer …`), daraus folgt der Mandant. Ohne Schlüssel oder mit einem falschen Schlüssel antwortet der Dienst 401, bei einem gesperrten Mandanten 403. Eine Mandanten-ID aus dem Pfad oder dem Body gilt nicht. Ohne Mandanten-Konfiguration gilt der Mandant `standard`.

| Aufruf | Kern |
| --- | --- |
| `POST /v1/anfragen` `{text, verlauf?, nur_suchen?}` | `finden`. Ohne Treffer und mit `[KI-API]`: Antwort holen, unbewertet merken. Herkunft `speicher`, `ki` oder `fehltreffer` |
| `POST /v1/eintraege` `{frage, antwort, bewertung?}` | `merken`, wenn das Projekt die Antwort selbst erzeugt hat |
| `POST /v1/anfragen/{id}/bewertung` `{bewertung, frage?}` | Daumen hoch: `bewerten(gut)`. Daumen runter: `ablehnen` je nach Herkunft, danach ist „neu generieren“ frei |
| `POST /v1/anfragen/{id}/neu` `{zusatz?}` | `neu` |
| `PUT /v1/anfragen/{id}/text` `{text}` | `umschreiben` |
| `POST /v1/anfragen/{id}/trennen` `{frage}` | `trennen` |
| `DELETE /v1/anfragen/{id}` | `vergessen` |
| `PUT` / `GET /v1/anfragen/{id}/anhaenge/{art}` | Anhang setzen und lesen |
| `GET /v1/gesundheit` | Modell, Breite, Anzahl, Einbettung bereit |
| `GET` / `PUT /v1/einstellungen` | Einbettung lokal oder API, Adresse, Modell, Schlüssel (nur schreiben) |

Die vier Aufrufe aus `plan.md` bleiben. `POST /v1/buecher` und KIWIX bleiben im Plan und sind nicht diese Stufe.

## Laufzeit

Der Kern ist Python. Der Prototyp ist Python, fastembed und sqlite-vec sind dort erprobt, die Messwerte gelten für genau diesen Weg. Ein Neuschreiben in einer zweiten Sprache wäre am Anfang doppelte Arbeit ohne Messung.

AVA ist TypeScript. AVA spricht mit Mini-KI über die HTTP-API. Kein Nachbau des Kerns in TypeScript (entschieden, `entscheidungen/laufzeit.md`). Ein kleiner TypeScript-Client kommt als Beispiel in dieses Repository. Python-Projekte wie der Live-Avatar dürfen den Kern direkt importieren.

## Mandanten und Skalierung

Entschieden von Wudu im Chat, 2026-10-21. Umsetzung: #15.

- **Ein Dienst pro Server.** Ein gemeinsamer Mini-KI-Dienst bedient alle Kunden auf diesem Server. Das Embedding-Modell liegt nur einmal im RAM.
- **Daten strikt pro Kunde.** Jeder Kunde ist ein Mandant mit eigenem Ordner:

```text
/data/
  modell-cache/              geteilt, nur Gewichte (lokale Einbettung)
  mandanten-zugang.json      Salt, HMAC-SHA-256 und Sperre, nie der Schlüssel
  mandanten/
    <mandant-id>/
      mini-ki.sqlite         Cache, Vektoren, Bewertungen, Ablehnungen
      anhaenge/              Audio (Opus) zu den gecachten Antworten
      einstellungen.json     Einbettung API/lokal, Schlüssel (nur hier)
```

- **Kunden-Schlüssel.** Der Dienst leitet den Mandanten aus `Authorization: Bearer` ab, nie aus einer frei mitgeschickten ID. Gespeichert wird HMAC-SHA-256 mit eigenem Salt in `mandanten-zugang.json`. Der Schlüssel wird einmal beim Anlegen ausgegeben, danach nie geloggt und nie zurückgegeben. Ein AVA-Container bekommt genau einen Schlüssel und sieht nur seine eigenen Daten.
- **Ein Kern-Objekt pro Mandant** in `mandanten.py`, beim ersten Zugriff angelegt. Die lokale Einbettung wird einmal geladen und von allen Mandanten mit `lokal` geteilt. Ein Mandant mit eigener API-Einbettung hat seine Vektorbreite für sich.
- **Verwaltung.** Anlegen, Sperren, Freigeben und Vergessen laufen über `python -m mini_ki.mandanten` im Container, nicht über die Kunden-API. `anlegen` schreibt den Schlüssel einmal nach stdout. `vergessen` löscht genau den Ordner dieses Mandanten.
- **Mehr Kunden heißt weitere Server.** Ein Mandant liegt immer auf genau einem Server. Kein gemeinsamer Speicher über Server.
- **Anfang:** Solange nur Wudu AVA nutzt, läuft Mini-KI als zweiter Container neben AVA im selben Compose-Stapel, mit dem Mandanten `standard`. Ohne `mandanten-zugang.json` bleibt dieser eine Mandant, optional mit `MINI_KI_ZUGANG`.

```text
Server
  ava-kunde-1 ──┐
  ava-kunde-2 ──┼── HTTP + Kunden-Schlüssel ──> mini-ki (ein Dienst, Modell 1x im RAM)
  ava-kunde-n ──┘                                  └─ /data/mandanten/<id>/…
```

## Docker Compose

Ein Dienst `mini-ki`, ein Volume `/data` mit Modell-Cache und den Mandanten-Ordnern (siehe oben). Einstellungen über `.env` (nicht im Repository, nur `.env.example`). Port `[Port]`, voreingestellt nur `127.0.0.1`. Mandanten verwaltet man im Container mit `python -m mini_ki.mandanten`, nicht über die Kunden-API.

## Einbau-Beispiele

- Python: Kern direkt, so wie der Live-Avatar ihn später nutzt.
- TypeScript: kleiner Client für AVA, mit Daumen-Ablauf und Audio-Anhang.
- curl: alle Aufrufe einmal.

## Nicht in dieser Stufe

Hochladen und Zerlegen von Büchern, KIWIX, Android, Uhr, Gewichtsanpassung, eine öffentliche zentrale API für fremde Projekte. Der Wissensspeicher hält fertige Abschnitte, die Buch-Schnittstelle bleibt offen. (Der gemeinsame Dienst pro Server für AVA-Kunden oben ist davon getrennt.)
