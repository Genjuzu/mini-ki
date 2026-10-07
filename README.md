# Mini-KI

Status: Entwurf. Ein laufender Stapel liegt hier nicht.

Mini-KI ist ein Antwortspeicher für das eigene Gerät. Ein Projekt schickt eine Anfrage an eine HTTP-API auf diesem Gerät. Liegt eine ähnliche Anfrage schon mit einer als gut bewerteten Antwort im Speicher, kommt diese Antwort zurück. Sonst kann eine Stelle aus einem mitgebrachten Buch antworten, oder ein Treffer aus einer angebundenen KIWIX-Bibliothek. Trifft keines davon, geht die Anfrage an eine KI-API, sofern ein Schlüssel gesetzt ist. Der Mensch bewertet die Antwort. Nur eine gute Antwort bleibt im Speicher.

Eine Weboberfläche im selben Stapel soll das Buch ablegen und die Vektorisierung zu Ende zeigen. Voreingestellt bleibt sie auf dem Gerät. Über das Netz ist sie erst mit `[Zugang]` erreichbar. KIWIX bleibt die Bibliothek. Mini-KI stellt die Frage davor. Eine ganze Bibliothek wird nicht vorab in Vektoren kopiert.

Eine schlechte Bewertung bietet eine neue Antwort an. Bei Buch und KIWIX geht Weiter und Zurück die nächsten Stellen durch, ohne die abgelehnte Stelle zu wiederholen. Eine Android-Anwendung ist ein späterer Client. Die Uhr rechnet die Einbettung im ersten Weg nicht selbst. Das tut ein Begleiter in der Nähe.

Geteilt wird das Vorhaben in diesem Repository. Jede Installation läuft auf dem Gerät des Menschen. Eine zentrale API, die wir betreiben, ist nicht Teil des Entwurfs.

Die Installation soll später ein Docker-Compose-Stapel sein. Er ist noch nicht gebaut.

Ausarbeitung: `plan.md`. Belege: `recherche.md`.

Lizenz: `[Lizenz]`.
