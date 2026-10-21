# Was Daumen runter speichert

Stand: **entschieden** (2026-10-21)

## Vorschlag 2026-10-21

Zwei Wege, beide erfüllen dieselbe Regel: nur `gut` wird wieder ausgegeben.

1. **Nichts speichern.** So steht es in `plan.md` und so hat es der Mensch am 2026-10-21 gesagt. `merken` erst bei Daumen hoch.
2. **Als `schlecht` markieren.** So läuft der Prototyp. Der Eintrag wird nie ausgegeben, aber er zeigt Lücken im Prompt und fehlendes Wissen.

Der Kern kann beides. Die Frage ist die Voreinstellung der API.

Vorschlag: Weg 1 als Voreinstellung, Weg 2 als Schalter `schlechte_merken`.

## Entscheidung 2026-10-21

Entschieden von Wudu im Chat, 2026-10-21.

Keiner der beiden Vorschläge allein. Es kommt auf die Herkunft der Antwort an:

- **Neue Antwort** (nicht aus dem Cache) + Daumen runter: Sie wird als `schlecht` gespeichert, damit man Lücken sieht. Ausgeliefert wird sie nie.
- **Antwort aus einem Cache-Treffer** + Daumen runter: Der Treffer gilt als unpassend **für diese Anfrage**. Er wird für diese Anfrage nicht mehr ausgeliefert, die Ablehnung wird als schlecht festgehalten, und die Anfrage ist frei für eine neue Antwort („neu generieren“). Für seine eigenen, mit Daumen hoch bestätigten Fragen bleibt der Eintrag gut.
- Daumen hoch legt wie bisher als `gut` ab. Nur `gut` wird ausgeliefert.

Der Satz in `plan.md` („Schlecht: es entsteht kein Speichereintrag“) ist damit überholt.

Abweichung im Kern: `bewerten(id, "schlecht")` kennt die Herkunft nicht und würde bei einem Cache-Treffer den ganzen Eintrag sperren. Umsetzung als eigener Aufruf `ablehnen` in #17. Die API (#8) nutzt ihn.
