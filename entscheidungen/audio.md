# Audio im Speicher

Stand: **entschieden** (2026-10-21)

## Vorschlag 2026-10-21

Vorschlag: Mini-KI speichert Anhänge pro Eintrag, auch Audio. Die Bytes liegen als Datei im Volume neben der SQLite-Datei. Ändert sich der Text, fällt das Audio weg. Mini-KI erzeugt keine Stimme. Das Projekt liefert das Audio nach Daumen hoch.

### Alternative

Wie im Entwurf des Prototyps: Mini-KI speichert nur Text, das Audio liegt beim Avatar unter der Kennung des Eintrags.

### Fragen an den Menschen

1. Audio in Mini-KI oder beim Projekt?
2. Format für den Live-Avatar: PCM 16-bit mono 24 kHz wie im Prototyp, oder ein komprimiertes Format? Eine Minute PCM sind etwa 2,9 MB.

## Entscheidung 2026-10-21

Entschieden von Wudu im Chat, 2026-10-21.

- **Audio liegt in Mini-KI** als Anhang der gecachten Antwort, pro Kunde (Mandant) getrennt. Der Live-Avatar spielt nur ab.
- **Format Opus** (Ogg) statt PCM 24 kHz: etwa 0,1 statt 2,9 MB pro Minute.
- Ändert sich der Text, fällt das Audio weg (so wie im Kern geplant).
- Mini-KI erzeugt weiter keine Stimme. Das Projekt liefert das Audio nach Daumen hoch.

Umsetzung: #6 (Anhänge), #16 (Opus), #15 (Trennung pro Mandant).
