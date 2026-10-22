"""Dieselben Sätze für das Python-Beispiel, den Beispieldienst und curl."""

FRAGE = "Wie erreiche ich Avatari?"
ANDERE = "Wie kann ich Avatari erreichen?"
BUERO = "Wo liegt das Büro von Avatari?"
ANTWORT = "Die Kontaktdaten stehen auf der Webseite von Avatari."
BUERO_ANTWORT = "Das Büro liegt im ersten Stock."
NEU = "Avatari erreichen Sie über die Webseite, dort stehen die Kontaktdaten."
UMSCHRIEBEN = "Wir sind über die Webseite von Avatari erreichbar."
VERWEIS = "Ja, dazu"

# Erste Formulierung einer Gruppe ist der Basis-Vektor. Weitere liegen dicht
# darüber, über der Treffer-Schwelle und unter der Gegenbeispiel-Schwelle.
# Der Fake hat kein Modell. Andere Texte bleiben weit auseinander.
GRUPPEN = {
    "kontakt": [FRAGE, ANDERE],
    "buero": [BUERO],
}


if __name__ == "__main__":
    import sys

    name = sys.argv[1]
    if name not in globals() or name.startswith("_"):
        raise SystemExit(f"Unbekannter Satz: {name}")
    wert = globals()[name]
    if not isinstance(wert, str):
        raise SystemExit(f"Kein Satz: {name}")
    sys.stdout.write(wert)
