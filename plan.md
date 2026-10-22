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
7. Gut: Anfrage, Vektor und Antwort werden gespeichert. Stammt die Antwort aus einem Buch, bleibt die Quellenangabe dabei. Nur `gut` wird wieder ausgeliefert.
8. Schlecht hängt davon ab, woher die Antwort kam. Eine neue Antwort, die nicht aus dem Speicher kam, wird als `schlecht` gespeichert. Sie zeigt die Lücke und wird nie ausgeliefert. Trifft die Antwort aus dem Speicher, gilt sie für diese Anfrage als unpassend: sie wird für diese Anfrage nicht mehr ausgeliefert, die Ablehnung wird mit Frage, Eintrag und Zeit festgehalten, und dieselbe Anfrage ist frei für eine neue Antwort. Für die Fragen, zu denen der Eintrag mit Daumen hoch bestätigt wurde, bleibt er gut. Ab drei Ablehnungen desselben Eintrags (die Zahl ist eine Einstellung) wird er zur Prüfung markiert, nicht gelöscht. Die Buchstelle bleibt im Buch, bis der Mensch das Buch entfernt. Dieselbe Stelle kann bei einer späteren, anderen Anfrage wieder erscheinen.

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

Auf einem Gerät startet der Stapel. Ein fremdes Projekt schickt eine Anfrage an `POST /v1/anfragen`. Eine bekannte gute Antwort kommt aus dem Speicher. Eine Buchstelle kommt offline, wenn sie innerhalb von `[Buchschwelle]` liegt. Nur `gut` wird ausgeliefert. Eine neue Antwort mit schlechter Bewertung bleibt als `schlecht` im Speicher und kommt nicht zurück. Eine schlechte Bewertung eines Treffers aus dem Speicher gilt nur für diese Anfrage; der Eintrag bleibt für seine bestätigten Fragen gut.

## Nicht in diesem Entwurf

Gewichtsanpassung. Eine zentrale gehostete API. Ein mitgeliefertes Buch. Eine gemessene Trefferquote. Ein lokales Sprachmodell als erste Offline-Antwort. Ein Eintrag in den Bausteinen von Watch.ai.

## 2026-10-07 Weboberfläche und KIWIX

Der Mensch will eine Weboberfläche, lokal oder über das Netz erreichbar, auf der ein Buch leicht zum Vektor wird. Später soll eine ganze KIWIX-Bibliothek Wissensquelle sein, über eine direkte Verbindung zu KIWIX. KIWIX bleibt die Bibliothek. Mini-KI beantwortet Fragen aus dieser Bibliothek und merkt sich die gute Antwort. Eine Änderung an der KIWIX-Software und ein eigenes Sprachmodell in KIWIX sind nicht dieser Entwurf.

### Weboberfläche

Die Oberfläche ist ein Client der HTTP-API, kein zweiter Dienst mit eigener Wahrheit. Sie liegt im selben Stapel. Voreingestellt hört sie nur auf dem Gerät. Erreichbar über das Netz wird sie erst, wenn der Mensch das öffnet. Vorher braucht es `[Zugang]`. Ein Schlüssel und ein Buch liegen nicht im Repository.

Auf der Oberfläche legt der Mensch ein Buch ab und sieht, wann die Vektorisierung zu Ende ist. Danach stellt er eine Frage und bewertet gut oder schlecht. Dieselben vier API-Aufrufe bleiben die Einbindung für andere Projekte. Die Oberfläche ist der einfache Weg für den Menschen, nicht ein Ersatz der API.

### KIWIX jetzt

Die Verbindung geht an eine laufende `kiwix-serve`-Instanz. Ihre Adresse bleibt `[KIWIX-Adresse]`. Die Dokumentation von kiwix-serve, Stand der gelesenen Seite https://kiwix-tools.readthedocs.io/en/stable/kiwix-serve.html, nennt als öffentliche Endpunkte den OPDS-Katalog unter `/catalog/v2`, `/raw` und `/search`. `/content` ist dort privat und wird nicht verwendet.

`kiwix-serve --library` liest eine XML-Bibliothek mit mehreren ZIM-Dateien. `/catalog/v2/entries` listet und filtert diese Dateien, unter anderem über `lang`, `category`, `tag`, `q`, `name` und `maxsize`. `/search` sucht im Volltext, mit `pattern`, `books.name` oder `books.id`, und `format=xml`. Die Seite nennt als Voreinstellung 25 Treffer und eine Obergrenze von 140 für `pageLength`. Eine Suche über mehrere ZIM-Dateien verlangt dieselbe Sprache. Durchsucht werden nur ZIM-Dateien, die eine Volltextsuche mitbringen. `/raw/ZIMNAME/content/PFAD` liefert den Eintrag ohne serverseitige Aufbereitung.

Der Ablauf von oben bekommt eine weitere Herkunft `kiwix`, nach dem Speicher und nach den vektorisierten Büchern:

1. Treffer im Speicher: gespeicherte Antwort.
2. Treffer in einem vektorisierten Buch: die Stelle.
3. Ist `[KIWIX-Adresse]` gesetzt, fragt Mini-KI `/search` und nimmt den Treffer als Antwort. Die Quellenangabe nennt die ZIM-Datei und den Pfad. Der Artikel selbst kommt bei Bedarf über `/raw`.
4. Sonst die `[KI-API]`, oder `fehltreffer`.

Bewertung gut schreibt Anfrage, Vektor und diese Antwort in denselben Speicher, mit der KIWIX-Quelle. Bewertung schlecht an einer neuen Antwort speichert sie als `schlecht` und liefert sie nicht wieder aus. Die ZIM-Datei bleibt bei KIWIX.

Eine ganze Bibliothek wird auf diesem Weg nicht vorab in Vektoren kopiert. Die Volltextsuche von KIWIX bleibt der Zugriff. Die Größe einer kompletten Bibliothek ist hier nicht gemessen.

### KIWIX später

Dieselbe Oberfläche soll später eine gewählte ZIM-Datei oder eine ganze Bibliothek so vektorisieren wie ein Buch. Das bleibt ein späterer Schritt. Der Katalogfilter `maxsize` ist belegt, ein konkreter Umfang nicht. Solange der Umfang offen ist, ist die direkte Suche der Weg, und die Vektorisierung der ganzen Bibliothek ist nicht der erste Bau.

### Offen dazu

- `[KIWIX-Adresse]`
- `[Zugang]`, sobald die Oberfläche das Gerät verlässt
- `[Port]` der Mini-KI. Der Port 80 ist die Voreinstellung von `kiwix-serve`, nicht die von Mini-KI.

## 2026-10-07 Neue Antwort, Android, Begleiter

### Schlechte Bewertung

Eine schlechte Bewertung hängt an der Herkunft. Eine neue Antwort wird als `schlecht` gespeichert und nicht wieder ausgeliefert. Dieselbe Frage bietet danach eine neue Antwort an. Kam die Antwort aus dem Speicher, bleibt der Eintrag für seine bestätigten Fragen gut. Für die abgelehnte Anfrage wird er ausgelassen, die Ablehnung wird festgehalten, und die Anfrage ist frei für eine neue Antwort.

Bei einem Buch und bei KIWIX liegt die neue Antwort in der schon gereihten Liste. Die abgelehnte Stelle ist für diese Frage ausgelassen. Weiter und Zurück, auf der Weboberfläche die Pfeiltasten, gehen die übrigen Stellen der Reihe nach durch. Dieselbe Stelle kommt dabei nicht als Nächstes wieder. Eine versteckte Änderung einer Schwelle gibt es nicht. Die Auslassung ist die ganze Anpassung. Eine spätere, andere Frage darf dieselbe Stelle wieder finden, solange sie im Buch oder in der ZIM-Datei bleibt.

Bei gesetzter `[KI-API]` holt die neue Antwort einen weiteren Versuch von dort. Kommt derselbe Text zurück, ist das die Antwort des Dienstes. Eine Temperatur oder ein anderer Abfrageparameter wird hier nicht erfunden.

### Android, später

Eine Handy-Anwendung für Android ist ein späterer Client derselben HTTP-API. Sie ist nicht der erste Bau. Das Telefon hat Netz. Solange das Netz da ist, füllt eine gute Bewertung den Speicher. Ohne Netz antwortet der Speicher, und was an Büchern oder einer KIWIX-Bibliothek auf dem Telefon liegt. Ein Framework, ein Laden und eine Fassung bleiben `[Android]`.

### Begleiter der Uhr

Für Watch.ai bleibt die Uhr der Agent. Die Einbettung liegt auf einem Begleiter in der Nähe. Der Mensch nennt dafür das Handy oder einen kleinen Rechner, als Beispiel einen Pi Zero 2W an einer Powerbank im Rucksack. Das Beispiel wählt `[Rechner]` nicht. Die Sprachaufnahme geht an diesen Begleiter. Dort läuft die Mini-KI. Eine bekannte gute Antwort kommt aus dem Speicher, ohne `[KI-API]`. Zurück an die Uhr geht kurzer Text.

Die Strecke zwischen Uhr und Begleiter bleibt offen, wie in B7 zwischen BLE und WLAN. Dieser Abschnitt schreibt B7 nicht um und legt keinen Baustein an.

Ob der ESP32-S3 der Uhr die Einbettung selbst rechnet, ist nicht belegt. ESP-SR erkennt Weckwort und feste Befehle, keine Satzvektoren. Die Beispiele von `esp-tflite-micro` 1.3.1 sind `hello_world`, `micro_speech` und `person_detection`, kein Satz-Einbettungsmodell. Eine TFLite-Fassung von `all-MiniLM-L6-v2` nennt Telefone, Raspberry Pi und eingebettete Systeme, nicht den ESP32, und wurde hier nicht ausgeführt. Ein anderes öffentliches Vorhaben lässt ein kleines Sprachmodell auf einem ESP32-S3 Text erzeugen. Das ist kein Speicher aus bewerteten Antworten. `[Einbettung auf der Uhr]` bleibt offen und ist nicht der erste Weg. Die Belege stehen in `recherche.md`.

## 2026-10-21 Baustein aus dem Live-Avatar-Prototyp

Der Antwortspeicher läuft schon im Live-Avatar-Prototyp (Repo `avatari-live`, `agent/cache.py`), mit gemessenem Modell und gemessenen Schwellen. Mini-KI baut nicht neu, sondern löst diese Logik heraus. Der Mensch will Mini-KI als Baustein, den er in jedes Projekt stecken kann.

Pipeline: aus dem Prototyp herauslösen, hier als Baustein bauen, danach in AVA (Repo `avataribot`) einbauen, später den Live-Avatar mit AVA als Backend verbinden.

Neu gegenüber dem Entwurf vom 2026-10-07:

- Jede Antwort bekommt Daumen hoch oder Daumen runter. Daumen runter auf eine neue Antwort speichert sie als `schlecht`. Daumen runter auf einen Speicher-Treffer gilt nur für diese Anfrage, hält die Ablehnung fest und bietet danach eine neue Antwort an.
- Ein Eintrag kann Anhänge tragen, zuerst Audio. Eine gecachte Antwort kostet dann auch keine neue Sprachsynthese.
- Die Einbettung ist austauschbar: lokal ohne Schlüssel, oder über einen OpenAI-kompatiblen Endpunkt mit Schlüssel, zum Beispiel OpenRouter. Das einbindende Projekt braucht dafür eine Einstellung.
- Ein Projekt, das selbst antwortet (AVA), legt die Antwort mit `POST /v1/eintraege` ab und nutzt Mini-KI nur zum Suchen.
- Später werden auch Abläufe (Workflows) wiederverwendet, nicht nur Texte.

`[Embedding-Modell]` hat damit einen gemessenen Kandidaten: `paraphrase-multilingual-MiniLM-L12-v2`, Deutsch, Apache-2.0. `[Schwelle]` hat einen gemessenen Kandidaten: 0,80, Gegenbeispiel 0,93. Beides gilt erst mit Freigabe.

Aufbau: `docs/architektur.md`. Weichen: `entscheidungen/`.
