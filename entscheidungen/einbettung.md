# Einbettung: lokal oder API

Stand: **entschieden** (2026-10-21)

## Vorschlag 2026-10-21

Vorschlag: Voreinstellung lokal mit `paraphrase-multilingual-MiniLM-L12-v2` (384, Kosinus, Apache-2.0), wie im Prototyp gemessen. Als Einstellung daneben ein OpenAI-kompatibler Endpunkt mit Schlüssel, zum Beispiel OpenRouter.

### Was gilt, egal wie entschieden wird

- Vektoren zweier Modelle passen nicht zusammen. Ein Wechsel des Modells heißt Neuaufbau aller Vektoren aus den gespeicherten Fragen.
- Die Schwellen 0,80 und 0,93 sind für das lokale Modell gemessen. Ein API-Modell braucht eigene Messung.
- Der Schlüssel liegt nur auf dem Gerät. Nicht im Repository, nicht im Log, nie in einer Antwort der API.
- Mit API geht jede Frage zum Anbieter. Lokal verlässt die Frage das Gerät nicht.

### Fragen an den Menschen

1. Voreinstellung lokal oder API?
2. Welches API-Modell, falls API? `[Embedding-Modell]`
3. Wo trägt AVA den Schlüssel ein: AVA reicht ihn an `PUT /v1/einstellungen` weiter, oder er steht in der `.env` des Stapels?

## Entscheidung 2026-10-21

Entschieden von Wudu im Chat, 2026-10-21.

- **Voreinstellung: API.** OpenAI-kompatibler Endpunkt, zuerst OpenRouter. Der Schlüssel wird in **AVAs Einstellungen** eingetragen. AVA reicht ihn an `PUT /v1/einstellungen` weiter (pro Mandant). Er liegt danach nur im Daten-Volume des Mandanten, nie im Repository, nie im Log, nie in einer Antwort.
- **Lokal** mit `paraphrase-multilingual-MiniLM-L12-v2` (wie im Prototyp) ist per Umschalter wählbar. Dann verlässt die Frage den Server nicht.
- Welches API-Modell genau, ist noch offen `[Embedding-Modell]`. Die Schwellen 0,80 und 0,93 gelten nur für das lokale Modell; für das API-Modell wird mit #12 neu gemessen.
- Umschalten heißt Neuaufbau aller Vektoren (#9).

Umsetzung: #5 (API), #4 (lokal), #9 (Einstellungen und Wechsel).
