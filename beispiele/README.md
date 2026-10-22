# Einbau-Beispiele

Mini-KI bleibt ein Python-Dienst. AVA spricht HTTP. Python-Projekte dürfen den Kern direkt importieren. Die Beispiele laufen ohne Modell, ohne Netz und ohne Schlüssel.

## Python, Kern direkt

So nutzt der Live-Avatar den Kern später: merken, Daumen hoch, finden, Audio, Daumen runter, vergessen. Die Einbettung ist ein Fake mit festen Vektoren.

```bash
python3 beispiele/python/kern_direkt.py
```

## TypeScript, Client für AVA

`client.ts` spricht die HTTP-API. `daumen.ts` ist der Ablauf: nur suchen, sonst selbst antworten, Daumen hoch, Opus-Audio anhängen. Daumen runter auf einen Treffer sperrt nur diese Frage.

```bash
tsc --noEmit -p beispiele/typescript
```

Keine Pakete. Der Client braucht nur `fetch`.

## curl, alle Aufrufe

Das Skript spricht einen laufenden Dienst. Ohne `MINI_KI_URL` startet es `beispiele/python/dienst.py` auf `127.0.0.1` mit derselben Fake-Einbettung. Ein gesetztes `MINI_KI_ZUGANG` geht als Bearer mit und wird nicht ausgegeben.

```bash
bash beispiele/curl/aufrufe.sh
```

Der Produktionsstart mit lokaler Einbettung bleibt `python -m mini_ki`. Der Beispieldienst ist nur der Weg ohne Gewichte.
