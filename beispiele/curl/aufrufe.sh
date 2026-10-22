#!/usr/bin/env bash
# Alle HTTP-Aufrufe einmal, gegen einen laufenden Mini-KI-Dienst.
# Ohne MINI_KI_URL startet das Skript den Beispieldienst (Fake-Einbettung).
# MINI_KI_ZUGANG wird, wenn gesetzt, als Bearer geschickt und nicht ausgegeben.
set -euo pipefail

wurzel="$(cd "$(dirname "$0")/../.." && pwd)"
py="${PYTHON:-python3}"
arbeit="$(mktemp -d)"
pid=""

aufraeumen() {
  if [[ -n "$pid" ]]; then
    kill "$pid" 2>/dev/null || true
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.1
    done
    kill -9 "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  fi
  rm -rf "$arbeit"
}
trap aufraeumen EXIT

if ! "$py" -c "import sqlite_vec" >/dev/null 2>&1; then
  echo "Der Python-Interpreter kann sqlite_vec nicht laden: $py" >&2
  exit 1
fi

satz() {
  "$py" "$wurzel/beispiele/python/texte.py" "$1"
}

basis="${MINI_KI_URL:-}"
basis="${basis%/}"
if [[ -z "$basis" ]]; then
  "$py" "$wurzel/beispiele/python/dienst.py" >"$arbeit/adresse" 2>"$arbeit/dienst.log" &
  pid="$!"
  for _ in $(seq 1 50); do
    if [[ -s "$arbeit/adresse" ]]; then
      break
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "Der Beispieldienst ist vor dem Start beendet." >&2
      cat "$arbeit/dienst.log" >&2 || true
      exit 1
    fi
    sleep 0.1
  done
  basis="$(head -n 1 "$arbeit/adresse" | tr -d '[:space:]')"
fi

if [[ "$basis" != http://* && "$basis" != https://* ]]; then
  echo "Die Dienst-Adresse fehlt oder ist ungültig." >&2
  [[ -f "$arbeit/dienst.log" ]] && cat "$arbeit/dienst.log" >&2 || true
  exit 1
fi

auth=()
if [[ -n "${MINI_KI_ZUGANG:-}" ]]; then
  auth=(-H "Authorization: Bearer ${MINI_KI_ZUGANG}")
fi

frage="$(satz FRAGE)"
andere="$(satz ANDERE)"
buero="$(satz BUERO)"
antwort="$(satz ANTWORT)"
buero_antwort="$(satz BUERO_ANTWORT)"
umschrieben="$(satz UMSCHRIEBEN)"
verweis="$(satz VERWEIS)"
audio="$arbeit/audio.ogg"
printf 'OggS\x00mini-ki-curl' >"$audio"

rufen() {
  local methode="$1"
  local pfad="$2"
  local daten="${3:-}"
  local typ="${4:-}"
  local extra=()
  if [[ -n "$typ" ]]; then
    extra+=(-H "Content-Type: $typ")
  fi
  if [[ -n "$daten" ]]; then
    curl -sS -D "$arbeit/kopf" -o "$arbeit/koerper" -w "%{http_code}" \
      -X "$methode" "${auth[@]}" "${extra[@]}" --data-binary @"$daten" \
      "$basis$pfad"
  else
    curl -sS -D "$arbeit/kopf" -o "$arbeit/koerper" -w "%{http_code}" \
      -X "$methode" "${auth[@]}" \
      "$basis$pfad"
  fi
}

json_schreiben() {
  "$py" -c 'import json,sys; json.dump(json.loads(sys.argv[1]), open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False)' \
    "$1" "$arbeit/anfrage.json"
}

erwarte() {
  local ist="$1"
  local soll="$2"
  local name="$3"
  if [[ "$ist" != "$soll" ]]; then
    echo "$name: Status $ist, erwartet $soll" >&2
    cat "$arbeit/koerper" >&2 || true
    exit 1
  fi
}

feld() {
  "$py" -c 'import json,sys; d=json.load(open(sys.argv[1], encoding="utf-8"));
p=sys.argv[2].split(".")
v=d
for t in p:
    v=v[int(t)] if t.isdigit() else v[t]
print(v)' "$arbeit/koerper" "$1"
}

feld_fehlt() {
  "$py" -c 'import json,sys; d=json.load(open(sys.argv[1], encoding="utf-8"));
sys.exit(0 if sys.argv[2] not in d else 1)' "$arbeit/koerper" "$1"
}

# Gesundheit
status="$(rufen GET /v1/gesundheit)"
erwarte "$status" 200 "Gesundheit"
[[ "$(feld einbettung_bereit)" == "True" ]]

# Suche ohne Treffer
json_schreiben "$(printf '{"text": %s, "nur_suchen": true}' "$("$py" -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$frage")")"
status="$(rufen POST /v1/anfragen "$arbeit/anfrage.json" application/json)"
erwarte "$status" 200 "Suche leer"
[[ "$(feld herkunft)" == "fehltreffer" ]]

# Eintrag, Daumen hoch, Audio
json_schreiben "$("$py" -c 'import json,sys; print(json.dumps({"frage": sys.argv[1], "antwort": sys.argv[2]}))' "$frage" "$antwort")"
status="$(rufen POST /v1/eintraege "$arbeit/anfrage.json" application/json)"
erwarte "$status" 201 "Eintrag"
kennung="$(feld id)"

json_schreiben '{"bewertung": "gut"}'
status="$(rufen POST "/v1/anfragen/$kennung/bewertung" "$arbeit/anfrage.json" application/json)"
erwarte "$status" 200 "Daumen hoch"
[[ "$(feld ok)" == "True" ]]

status="$(rufen PUT "/v1/anfragen/$kennung/anhaenge/audio" "$audio")"
erwarte "$status" 200 "Audio setzen"
[[ "$(feld art)" == "audio" ]]
[[ "$(feld groesse)" == "$(wc -c <"$audio" | tr -d ' ')" ]]

json_schreiben "$("$py" -c 'import json,sys; print(json.dumps({"text": sys.argv[1]}))' "$andere")"
status="$(rufen POST /v1/anfragen "$arbeit/anfrage.json" application/json)"
erwarte "$status" 200 "Formulierung"
[[ "$(feld herkunft)" == "speicher" ]]
[[ "$(feld id)" == "$kennung" ]]
[[ "$(feld text)" == "$antwort" ]]
[[ "$(feld anhaenge.0.art)" == "audio" ]]
[[ "$(feld anhaenge.0.medientyp)" == "audio/ogg; codecs=opus" ]]

status="$(rufen GET "/v1/anfragen/$kennung/anhaenge/audio")"
erwarte "$status" 200 "Audio lesen"
grep -qi 'audio/ogg' "$arbeit/kopf"
cmp -s "$audio" "$arbeit/koerper"

# Verweis wird vor der Suche zur bekannten Frage
json_schreiben "$("$py" -c 'import json,sys; print(json.dumps({"text": sys.argv[1], "verlauf": "Gast: " + sys.argv[2]}))' "$verweis" "$frage")"
status="$(rufen POST /v1/anfragen "$arbeit/anfrage.json" application/json)"
erwarte "$status" 200 "Verweis"
[[ "$(feld herkunft)" == "speicher" ]]
[[ "$(feld id)" == "$kennung" ]]

# Text ändern, Audio fällt weg
json_schreiben "$("$py" -c 'import json,sys; print(json.dumps({"text": sys.argv[1]}))' "$umschrieben")"
status="$(rufen PUT "/v1/anfragen/$kennung/text" "$arbeit/anfrage.json" application/json)"
erwarte "$status" 200 "Text"
[[ "$(feld text)" == "$umschrieben" ]]
status="$(rufen GET "/v1/anfragen/$kennung/anhaenge/audio")"
erwarte "$status" 404 "Audio nach Textänderung"

# Neu erzeugen, ohne die Suche zu benutzen
json_schreiben '{"zusatz": "Bitte kürzer."}'
status="$(rufen POST "/v1/anfragen/$kennung/neu" "$arbeit/anfrage.json" application/json)"
erwarte "$status" 200 "Neu"
[[ "$(feld id)" == "$kennung" ]]
neu_text="$(feld text)"
[[ -n "$neu_text" ]]
json_schreiben "$("$py" -c 'import json,sys; print(json.dumps({"text": sys.argv[1]}))' "$frage")"
status="$(rufen POST /v1/anfragen "$arbeit/anfrage.json" application/json)"
erwarte "$status" 200 "Suche nach Neu"
[[ "$(feld text)" == "$neu_text" ]]
feld_fehlt anhaenge

# Daumen runter auf den Treffer der anderen Formulierung
json_schreiben "$("$py" -c 'import json,sys; print(json.dumps({"text": sys.argv[1]}))' "$andere")"
status="$(rufen POST /v1/anfragen "$arbeit/anfrage.json" application/json)"
erwarte "$status" 200 "Treffer vor Daumen runter"
[[ "$(feld id)" == "$kennung" ]]
json_schreiben "$("$py" -c 'import json,sys; print(json.dumps({"bewertung": "schlecht", "frage": sys.argv[1], "herkunft": "speicher"}))' "$andere")"
status="$(rufen POST "/v1/anfragen/$kennung/bewertung" "$arbeit/anfrage.json" application/json)"
erwarte "$status" 200 "Daumen runter"
json_schreiben "$("$py" -c 'import json,sys; print(json.dumps({"text": sys.argv[1]}))' "$andere")"
status="$(rufen POST /v1/anfragen "$arbeit/anfrage.json" application/json)"
erwarte "$status" 200 "Getrennte Formulierung"
[[ "$(feld herkunft)" == "fehltreffer" ]]
json_schreiben "$("$py" -c 'import json,sys; print(json.dumps({"text": sys.argv[1]}))' "$frage")"
status="$(rufen POST /v1/anfragen "$arbeit/anfrage.json" application/json)"
erwarte "$status" 200 "Ursprüngliche Frage bleibt"
[[ "$(feld id)" == "$kennung" ]]

# Trennen der ursprünglichen Frage
json_schreiben "$("$py" -c 'import json,sys; print(json.dumps({"frage": sys.argv[1]}))' "$frage")"
status="$(rufen POST "/v1/anfragen/$kennung/trennen" "$arbeit/anfrage.json" application/json)"
erwarte "$status" 200 "Trennen"
json_schreiben "$("$py" -c 'import json,sys; print(json.dumps({"text": sys.argv[1]}))' "$frage")"
status="$(rufen POST /v1/anfragen "$arbeit/anfrage.json" application/json)"
erwarte "$status" 200 "Nach dem Trennen"
[[ "$(feld herkunft)" == "fehltreffer" ]]

# Vergessen
status="$(rufen DELETE "/v1/anfragen/$kennung")"
erwarte "$status" 204 "Vergessen"
status="$(rufen DELETE "/v1/anfragen/$kennung")"
erwarte "$status" 404 "Schon vergessen"

# Neue Antwort, Daumen runter, wird nie geliefert
json_schreiben "$("$py" -c 'import json,sys; print(json.dumps({"frage": sys.argv[1], "antwort": sys.argv[2]}))' "$buero" "$buero_antwort")"
status="$(rufen POST /v1/eintraege "$arbeit/anfrage.json" application/json)"
erwarte "$status" 201 "Zweiter Eintrag"
zweite="$(feld id)"
json_schreiben '{"bewertung": "schlecht"}'
status="$(rufen POST "/v1/anfragen/$zweite/bewertung" "$arbeit/anfrage.json" application/json)"
erwarte "$status" 200 "Daumen runter auf neue Antwort"
json_schreiben "$("$py" -c 'import json,sys; print(json.dumps({"text": sys.argv[1]}))' "$buero")"
status="$(rufen POST /v1/anfragen "$arbeit/anfrage.json" application/json)"
erwarte "$status" 200 "Schlechte Antwort"
[[ "$(feld herkunft)" == "fehltreffer" ]]
status="$(rufen DELETE "/v1/anfragen/$zweite")"
erwarte "$status" 204 "Zweiten Eintrag vergessen"

echo "curl: alle Aufrufe gegen $basis sind durchgelaufen."
