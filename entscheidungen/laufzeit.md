# Laufzeit und Einbau in AVA

Stand: **offen**

## 2026-10-21

Vorschlag: Der Kern ist Python. AVA (TypeScript) nutzt Mini-KI als HTTP-Dienst im eigenen Compose-Stapel. Python-Projekte dürfen den Kern direkt importieren.

### Grund

- Der laufende Prototyp ist Python. fastembed und sqlite-vec sind dort erprobt. Die Schwellen sind mit genau diesem Modell gemessen.
- `plan.md` nennt die HTTP-API schon als einzige Einbindestelle. Jede Sprache kann sie rufen.
- Ein Dienst hält das Modell einmal im Speicher, auch wenn mehrere Projekte fragen.

### Alternative

Der Kern wird in TypeScript nachgebaut und in AVA als Bibliothek eingebaut, ohne zweiten Dienst. Bausteine dafür gibt es (sqlite-vec für Node, ONNX im Browser oder in Node). Nachteil: zwei Fassungen derselben Logik, neue Messung der Schwellen, doppelte Tests.

### Frage an den Menschen

HTTP-Dienst neben AVA, oder TypeScript-Bibliothek in AVA?

`entschieden` setzt nur der Mensch.
