# Mini-KI

Status: Entwurf. Freigabe durch den Menschen steht aus. Kein laufender Dienst, kein Docker-Stapel, keine Bibliotheksfassung zum Einbau.

Entstanden am 2026-10-07 neben Watch.ai. Watch.ai bleibt der Agent am Armgelenk. Dieses Repository ist das Seitenprojekt.

## Ziel

Ein Mensch installiert Mini-KI auf einem eigenen Gerät, vom Menschen als Raspberry Pi oder etwas Vergleichbares genannt, und bindet sie in beliebige Projekte ein. Die Projekte sprechen nur mit der API dieses Geräts. Wiederkehrende Anfragen kommen aus dem lokalen Speicher. Neue Anfragen gehen an `[KI-API]`, solange ein Schlüssel gesetzt ist. Bücher auf dem Gerät sind eine zweite Antwortquelle und brauchen dafür das Netz nicht.

Welches Gerät das ist, bleibt `[Rechner]`.

## Einbindung

Die einzige Einbindestelle ist eine HTTP-API auf dem eigenen Gerät. Ein Projekt in einer beliebigen Sprache schickt die Anfrage dorthin. Eine Programmbibliothek pro Sprache ist nicht die erste Form. Der Stapel, der diese API startet, soll später Docker Compose sein. Dieser Stapel ist nicht Teil dieses Stands.

Geteilt wird der Stapel über dieses öffentliche Repository. Die laufende API bleibt auf dem Gerät. Eine von uns betriebene zentrale API gibt es nicht.

Vorgesehene Aufrufe, noch ohne Implementierung:

1. `POST /v1/anfragen` mit dem Text. Die Antwort nennt eine Kennung, die Herkunft `speicher`, `buch` oder `fehltreffer`, den Text und bei einem Buch die Quelle.
2. `POST /v1/anfragen/{id}/bewertung` mit `gut` oder `schlecht`.
3. `POST /v1/buecher` mit einer Datei, die der Mensch mitbringt.
4. `GET /v1/gesundheit`.

Ist `[KI-API]` gesetzt und die Herkunft `fehltreffer`, holt der Stapel die Antwort selbst und legt sie zur Bewertung vor. Ohne Schlüssel und ohne Buchtreffer bleibt die Herkunft `fehltreffer`. Das einbindende Projekt entscheidet dann selbst.

## Ablauf

1. Die Anfrage wird mit einem vortrainierten Einbettungsmodell zum Vektor. Die Gewichte dieses Modells bleiben stehen.
2. Der Vektor sucht die nächsten gespeicherten Anfragen.
3. Liegt der beste Abstand innerhalb von `[Schwelle]`, geht die gespeicherte Antwort zurück. Herkunft: `speicher`.
4. Sonst sucht derselbe Vektor in den Buchstellen. Liegt der beste Abstand innerhalb von `[Buchschwelle]`, geht diese Stelle zurück. Herkunft: `buch`. Das ist die Offline-Antwort. Ein lokales Sprachmodell formuliert sie in diesem Entwurf nicht um.
5. Sonst, mit gesetzter `[KI-API]`, kommt die Antwort von dort. Herkunft zur Bewertung: die API. Ohne Schlüssel: `fehltreffer`.
6. Der Mensch bewertet gut oder schlecht. Der Weg bleibt `[Bewertung]`.
7. Gut: Anfrage, Vektor und Antwort werden gespeichert. Stammt die Antwort aus einem Buch, bleibt die Quellenangabe dabei.
8. Schlecht: es entsteht kein Speichereintrag. Die Buchstelle bleibt im Buch, bis der Mensch das Buch entfernt. Dieselbe Stelle kann bei einer späteren Anfrage wieder erscheinen.

Der Abstand des Speichers und die Ähnlichkeit des Modells sind dieselbe Entscheidung. Sie wird nicht aus zwei verschiedenen Maßen gemischt. `[Schwelle]` und `[Buchschwelle]` bleiben offen, bis sie am gefüllten Speicher geprüft sind.

Nahe Formulierungen mit anderem Inhalt können falsch treffen, etwa dieselbe Frage mit einer anderen Zahl. Eine Trefferquote steht hier nicht.

## Bücher

Ein Buch ist eine Datei, die der Mensch auf das Gerät legt. Dieses Repository enthält kein Buch. Das Urheberrecht an der Datei bleibt beim Menschen, der sie einbringt.

Die Datei wird in Stellen zerlegt. Jede Stelle bekommt einen Vektor. Eine Anfrage kann offline die nahe Stelle als Antwort bekommen. Bewertet der Mensch diese Antwort als gut, wird das Paar aus Anfrage und Stelle zum Speichereintrag. Die nächste ähnliche Anfrage kann aus dem Speicher kommen, ohne die Stelle neu zu suchen und ohne `[KI-API]`.

Das ist der Lernweg offline. Er füllt den Speicher. Er ändert die Gewichte der Einbettung nicht. Eine Feinabstimmung aus den guten Paaren wäre ein eigenes Vorhaben.

Ein kleines Sprachmodell, das Buchstellen zu einem freien Satz umschreibt, ist nicht die erste Installation. `[Rechner]` ist nicht festgelegt. Der erste Offline-Weg muss ohne dieses Modell fertig sein.

Welche Dateiarten angenommen werden, bleibt `[Bucharten]`. PDF, EPUB und reiner Text sind Kandidaten und keine Wahl.

## Was die Teile schon sind

Semantische Caches, Dokumentensuche und Docker-Installationen gibt es getrennt. Die Kombination aus diesem Plan ist dort nicht als fertiger Stapel belegt: eine API, Docker Compose, Aufnahme nur nach der Bewertung gut, Bücher als Offline-Antwort, die nach der guten Bewertung in denselben Speicher wandern. Die Belege stehen in `recherche.md`. Zahlen aus fremden Readmes werden nicht übernommen.

## Offen

- `[Rechner]`
- `[Embedding-Modell]`, einschließlich der Sprache. Deutsch ist nicht belegt.
- `[Schwelle]`
- `[Buchschwelle]`
- `[Bucharten]`
- `[KI-API]`
- `[Bewertung]`
- `[Lizenz]`

## Fertig-Satz

Gilt erst nach Freigabe und nach dem Bau:

Auf einem Gerät startet der Stapel. Ein fremdes Projekt schickt eine Anfrage an `POST /v1/anfragen`. Eine bekannte gute Antwort kommt aus dem Speicher. Eine Buchstelle kommt offline, wenn sie innerhalb von `[Buchschwelle]` liegt. Nur die Bewertung gut legt Anfrage und Antwort in den Speicher. Eine schlechte Bewertung legt nichts ab.

## Nicht in diesem Entwurf

Gewichtsanpassung. Eine zentrale gehostete API. Ein mitgeliefertes Buch. Eine gemessene Trefferquote. Ein lokales Sprachmodell als erste Offline-Antwort. Ein Eintrag in den Bausteinen von Watch.ai.
