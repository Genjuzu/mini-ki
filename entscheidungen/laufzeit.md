# Laufzeit und Einbau in AVA

Stand: **entschieden** (2026-10-21)

## Vorschlag 2026-10-21

Vorschlag: Der Kern ist Python. AVA (TypeScript) nutzt Mini-KI als HTTP-Dienst im eigenen Compose-Stapel. Python-Projekte dürfen den Kern direkt importieren.

### Grund

- Der laufende Prototyp ist Python. fastembed und sqlite-vec sind dort erprobt. Die Schwellen sind mit genau diesem Modell gemessen.
- `plan.md` nennt die HTTP-API schon als einzige Einbindestelle. Jede Sprache kann sie rufen.
- Ein Dienst hält das Modell einmal im Speicher, auch wenn mehrere Projekte fragen.

### Alternative

Der Kern wird in TypeScript nachgebaut und in AVA als Bibliothek eingebaut, ohne zweiten Dienst. Bausteine dafür gibt es (sqlite-vec für Node, ONNX im Browser oder in Node). Nachteil: zwei Fassungen derselben Logik, neue Messung der Schwellen, doppelte Tests.

### Frage an den Menschen

HTTP-Dienst neben AVA, oder TypeScript-Bibliothek in AVA?

## Entscheidung 2026-10-21

Entschieden von Wudu im Chat, 2026-10-21.

- Mini-KI bleibt ein **Python-Dienst per HTTP neben AVA**. Kein Nachbau in TypeScript.
- **Skalierung:** Ein gemeinsamer Mini-KI-Dienst pro Server für alle Kunden. Das Modell liegt nur einmal im RAM.
- **Daten strikt pro Kunde getrennt:** eigener Ordner je Mandant mit eigener SQLite-Cache-Datei und eigenen Audio-Dateien.
- **Zugriff per Kunden-Schlüssel**, daraus folgt die Mandanten-ID. Ein AVA-Container sieht nur die eigenen Daten.
- Mehr Kunden heißt weitere Server. Ein Mandant liegt immer auf genau einem Server.
- **Anfangs** (nur Wudu) läuft Mini-KI als zweiter Container neben AVA im selben Compose-Stapel, mit einem Mandanten `standard`.

Umsetzung: #15 (Mandanten-Trennung). Aufbau: `docs/architektur.md`, Abschnitt „Mandanten und Skalierung“.
