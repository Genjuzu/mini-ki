# Recherche

Stand 2026-10-07. Keine Schwelle, kein Modell und keine API werden hier gesetzt. Kein Versuch auf einem Raspberry Pi. Zahlen aus fremden Texten sind Behauptungen dieser Texte und gelten hier nicht.

## 2026-10-07 Einbettung und Vektorspeicher

### Sentence Transformers

Bibliothek: Sentence Transformers. Context7-ID: `/huggingface/sentence-transformers`. Abruf ohne festgelegte Fassung.

Belegter Ausschnitt: Die README lädt ein vortrainiertes Modell mit `SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")`, ruft `encode` und danach `similarity`. Für drei Sätze nennt der Kommentar die Form `(3, 384)`. Die Diagonale der Ähnlichkeit ist in demselben Kommentar `1.0`. Ein zweites Beispiel lädt `sentence-transformers/multi-qa-mpnet-base-cos-v1`.

Getrennt davon beschreibt eine Trainingsnotiz die Feinabstimmung über die Kosinus-Ähnlichkeit. Das ist ein anderer Weg als `encode` auf einem schon geladenen Modell.

Nicht belegt: eine Fassung, ein Lauf auf einem Raspberry Pi, Deutsch. Beide Modellnamen sind Beispiele der Bibliothek, keine Wahl. Die Weite 384 gilt im Kommentar nur für das erste Beispiel.

### sqlite-vec

Bibliothek: sqlite-vec. Context7-ID: `/asg017/sqlite-vec`. Abruf ohne festgelegte Fassung. `/sqliteai/sqlite-vector` ist eine andere Bibliothek.

Belegter Ausschnitt: Eine virtuelle Tabelle `vec0` trägt eine Spalte mit fester Weite, im Beispiel `float[768]`. Die Suche filtert mit `match` und ordnet nach `distance`. Die README nennt reines C und dass es läuft, wo SQLite läuft, darunter Raspberry Pi. `distance_metric=cosine` stellt Kosinus ein. Der Text zum Beispiel sagt, die Voreinstellung sei L2. Skalarfunktionen `vec_distance_L2`, `vec_distance_L1` und `vec_distance_cosine` rechnen den Abstand auch ohne `vec0`.

Nicht belegt: ein Lauf auf dem Gerät des Menschen. Die Weite 768 ist die des Beispiels. Die Spaltenweite muss die Weite des gewählten Einbettungsmodells sein. Ein Schwellenwert steht in diesem Abruf nicht.

### GPTCache

Bibliothek: GPTCache. Context7-ID: `/zilliztech/gptcache`. Seite: https://github.com/zilliztech/gptcache

Belegter Ausschnitt: GPTCache macht aus der Anfrage eine Einbettung und sucht ähnliche Anfragen. Einbettung über ONNX, Hugging Face oder Sentence Transformers ist in der Usage-Seite genannt, Speicherung in SQLite, MySQL oder PostgreSQL, Vektoren in FAISS oder Milvus. `put` speichert Anfrage und Antwort. Die Beispiele-Seite beschreibt einen eigenen Server in wenigen Zeilen und einen `LlmVerifier`, der eine abgerufene Antwort von einem Modell prüfen lässt.

Nicht belegt: dass `put` auf eine Bewertung gut oder schlecht wartet. `Config(similarity_threshold=0.75)` und Abstände `2.0` und `4.0` sind Beispiele der Bibliothek. Werbeaussagen zu Kosten und Geschwindigkeit werden nicht übernommen.

## 2026-10-07 Was es schon gibt

Gesucht am 2026-10-07. Die gelesenen Seiten belegen die Teile. Sie belegen nicht den fertigen Stapel aus `plan.md`.

### Semantischer Cache als Dienst

Redis LangCache, https://redis.io/docs/latest/develop/ai/context-engine/langcache/ : semantischer Cache mit REST. Suche und Ablegen sind zwei Aufrufe. Die Übersicht nennt eine verwaltete Fassung auf Redis Cloud und eine eigene Fassung auf Kubernetes als private Vorschau mit Lizenzschlüssel. Die Voraussetzungen nennen Einbettung über einen OpenAI-kompatiblen Anbieter und Container-Images, ausgerollt über Helm, nicht als einzelner Compose-Stapel. Bücher und eine Gut-Schlecht-Sperre stehen in den gelesenen Seiten nicht.

Reverb, https://github.com/intuitai/reverb : die README beschreibt einen HTTP-Dienst, Docker, einen genauen und einen semantischen Cache, und das Entfernen von Einträgen, wenn eine Wissensquelle sich ändert. Eine Sperre, die erst nach der Bewertung gut schreibt, steht in dem gelesenen Text nicht.

semantic-cache, https://github.com/uncle-voh-max/semantic-cache : die README beschreibt Docker Compose, genauen und semantischen Cache, und dass Antworten, die eine Prüfung verfehlen, nicht geschrieben werden. Eine Bewertung durch den Menschen steht in dem gelesenen Text nicht.

semanticmemo, https://pypi.org/project/semanticmemo/ : die Projektseite beschreibt eine Bibliothek, die schlechte Treffer meldet und daraus Paare für ein späteres Training eines Klassifikators schreibt. Eine Prozentangabe auf dieser Seite wird nicht übernommen. Ein Docker-Stapel mit Büchern steht dort nicht.

ChatBrain, https://github.com/elmstreetshawn/chatbrain : die in der Suche gelieferte README beschreibt einen Chat mit Einbettung, ähnlichen Fragen, Ollama und einer Bewertung gut oder schlecht. Das ist ein Chatprogramm. Eine Buch-API zum Einbinden steht in diesem Ausschnitt nicht. Zahlen aus dieser README werden nicht übernommen. Das Repository wurde nicht geklont und das genannte Image nicht gestartet.

### Bücher und Dokumente offline

AnythingLLM, https://docs.anythingllm.com/installation-docker/local-docker : Docker-Image `mintplexlabs/anythingllm`, im Text Port 3001, Dokumente in einem Arbeitsbereich. Eine Aufnahme in einen Antwortspeicher erst nach der Bewertung gut steht auf der Installationsseite nicht.

bookrack, https://github.com/Collegium-Siderum/bookrack : die README beschreibt eine lokale Suche über EPUB, TXT und PDF, mit Quellenangabe, über MCP. Sie nennt den Stand Vorveröffentlichung. Eine Bewertung gut oder schlecht steht in dem gelesenen Text nicht.

local-rag, https://github.com/SirajSpark/local-rag : die README beschreibt Docker Compose, Dokumente, Antworten mit Quellenangabe und lokale Modelle. Eine Bewertung gut oder schlecht steht in dem gelesenen Text nicht.

Pleias, https://github.com/Pleias/pi-cache-augmented-generation : die README beschreibt Cache-Augmented Generation. Das ist der vorberechnete Kontext eines festen Dokuments in einem kleinen Sprachmodell, nicht die Suche nach einer früher bewerteten Antwort. Docker, arm64 und Raspberry Pi 4 als Untergrenze stehen dort. Gemessene Tokengeschwindigkeiten dieser README gelten nur für jenen Versuch und werden nicht übernommen. Die Obergrenze der Dokumentlänge und die Bibliotheksgröße von 20 sind Angaben dieser README, keine Vorgabe für Mini-KI.

### Schluss

Die Teile liegen getrennt vor: Einbettung, Vektorsuche, semantischer Cache, Dokumentensuche, Docker. Der Entwurf in `plan.md` setzt daraus eine andere Form: eine API auf dem eigenen Gerät, Schreiben nur nach der Bewertung gut, Buchstellen als Offline-Antwort, die nach der guten Bewertung in denselben Speicher wandern.

## 2026-10-07 kiwix-serve

Bibliothek: kiwix-serve, Teil von kiwix-tools. Context7 lieferte auf die Namen `kiwix-serve` und `libkiwix` keine passende Bibliothek. Beleg ist die gelesene Dokumentationsseite https://kiwix-tools.readthedocs.io/en/stable/kiwix-serve.html. Keine Fassung festgelegt. Kein eigener Lauf.

Frage: Wie spricht ein Client eine KIWIX-Bibliothek an, um ZIM-Dateien zu finden, darin zu suchen und einen Artikel zu lesen?

Belegter Ausschnitt: `kiwix-serve` liefert ZIM-Inhalt über HTTP und kann eine Bibliothek aus mehreren ZIM-Dateien führen. Der Aufruf `kiwix-serve --library` nimmt eine XML-Datei, mehrere Dateien getrennt durch Semikolon. Voreingestellter Port ist 80. `--address` wählt die Adresse, Voreinstellung sind alle vorhandenen Adressen.

Öffentlich sind laut dieser Seite nur der OPDS-Katalog, `/raw` und `/search` einschließlich `/search/searchdescription.xml`. `/content` ist privat. `/catalog` ohne `v2` ist veraltet.

`/catalog/v2/entries` liefert die ZIM-Dateien, seitenweise, Filter `lang`, `category`, `tag`, `notag`, `maxsize`, `q` und `name`. `maxsize` ist eine Größe in Byte. Ein Beispielwert für eine ganze Bibliothek steht dort nicht.

`/search` macht eine Volltextsuche und kann HTML oder XML liefern. Parameter im gelesenen Text: `pattern`, `books.name`, `books.id`, `books.filter.{Kriterium}`, `pageLength` mit Voreinstellung 25 und Obergrenze 140, `start`, `format` mit den Werten html und xml. Mehrere ZIM-Dateien in einer Suche müssen dieselbe Sprache haben. Die Einleitung sagt, die Fernsuche gelte für ZIM-Dateien, die eine Volltextdatenbank enthalten.

`/raw/ZIMNAME/content/PFAD` liefert den Eintrag. Die Seite sagt, `/raw` garantiere keine serverseitige Aufbereitung, im Unterschied zu `/content`.

Nicht belegt: eine Context7-Fassung. Nicht belegt: dass jede ZIM-Datei eine Volltextsuche hat. Nicht belegt: der Umfang einer Wikipedia-Bibliothek. Nicht belegt: ein Vektorindex in kiwix-serve. Die Suche dieser Seite ist Volltext, keine Einbettung.

Ein GitHub-Kommentar in https://github.com/kiwix/libkiwix/issues/480 nennt `http://library.kiwix.org/catalog/` als einen Katalog und sagt, jede `kiwix-serve` könne einen Katalog ausliefern, die Adresse müsse einstellbar sein. Dieser Kommentar ist keine Prüfung, ob die Adresse am 2026-10-07 antwortet. `[KIWIX-Adresse]` bleibt offen.
