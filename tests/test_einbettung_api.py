"""API-Einbettung gegen einen lokalen Fake-Server. Kein echtes Netz, kein Schlüssel."""

import json
import logging
import sqlite3
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote

import pytest
import sqlite_vec

from mini_ki import MiniKI
from mini_ki.einbettung_api import ApiEinbettung, EinbettungApiFehler

SCHLUESSEL = "pruef/schluessel+wert"
MODELL = "pruef-modell"
BREITE = 4


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        laenge = int(self.headers.get("Content-Length") or "0")
        roh = self.rfile.read(laenge)
        eintrag = {
            "methode": "POST",
            "pfad": self.path,
            "authorization": self.headers.get("Authorization"),
            "content_type": self.headers.get("Content-Type"),
            "roh": roh,
            "koerper": json.loads(roh.decode("utf-8")),
        }
        self.server.empfangen.append(eintrag)
        status, ladung = self.server.antworten(eintrag)
        daten = json.dumps(ladung).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(daten)))
        self.end_headers()
        self.wfile.write(daten)

    def log_message(self, format, *args):
        return


class _Server(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address, handler):
        super().__init__(server_address, handler)
        self.empfangen: list[dict] = []
        self.antworten: Callable[[dict], tuple[int, dict]] | None = None
        self.bereit = threading.Event()

    def service_actions(self):
        self.bereit.set()


class _Fake:
    def __init__(self, antworten):
        self._httpd = _Server(("127.0.0.1", 0), _Handler)
        self._httpd.antworten = antworten
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            kwargs={"poll_interval": 0.05},
            daemon=True,
        )

    def __enter__(self):
        self._thread.start()
        if not self._httpd.bereit.wait(2):
            self._httpd.server_close()
            raise RuntimeError("Der Fake-Server ist nicht bereit.")
        host, port = self._httpd.server_address
        self.basis = f"http://{host}:{port}"
        self.empfangen = self._httpd.empfangen
        return self

    def __exit__(self, *args):
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=2)
        return False


def _umgekehrt(eintrag):
    texte = eintrag["koerper"]["input"]
    daten = [
        {"object": "embedding", "index": i, "embedding": [float(i + 1)] * BREITE}
        for i in range(len(texte))
    ]
    daten.reverse()
    return 200, {"object": "list", "data": daten, "model": MODELL}


def test_anfrage_traegt_modell_input_und_bearer():
    texte = ["Frühstück", "Pool"]
    with _Fake(_umgekehrt) as fake:
        basis = ApiEinbettung(fake.basis + "/api/v1", MODELL, SCHLUESSEL, BREITE)
        voll = ApiEinbettung(
            fake.basis + "/embeddings",
            MODELL,
            SCHLUESSEL,
            BREITE,
        )
        assert SCHLUESSEL not in repr(basis)
        erste = basis.vektoren(texte)
        zweite = voll.vektoren(["Pool"])
    assert erste[0] == [1.0] * BREITE
    assert erste[1] == [2.0] * BREITE
    assert zweite == [[1.0] * BREITE]
    assert [eintrag["pfad"] for eintrag in fake.empfangen] == [
        "/api/v1/embeddings",
        "/embeddings",
    ]
    anfrage = fake.empfangen[0]
    assert anfrage["methode"] == "POST"
    assert anfrage["authorization"] == f"Bearer {SCHLUESSEL}"
    assert anfrage["content_type"] == "application/json"
    assert anfrage["koerper"] == {"model": MODELL, "input": texte}
    assert SCHLUESSEL.encode("utf-8") not in anfrage["roh"]
    assert texte == ["Frühstück", "Pool"]


def test_reihenfolge_folgt_dem_index():
    def antworten(_eintrag):
        return 200, {
            "data": [
                {"index": 2, "embedding": [0.0, 0.0, 1.0, 0.0]},
                {"index": 0, "embedding": [1.0, 0.0, 0.0, 0.0]},
                {"index": 1, "embedding": [0.0, 1.0, 0.0, 0.0]},
            ]
        }

    with _Fake(antworten) as fake:
        einbettung = ApiEinbettung(fake.basis, MODELL, SCHLUESSEL, BREITE)
        vektoren = einbettung.vektoren(["a", "b", "c"])
    assert vektoren == [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
    ]


def test_unvollstaendiger_index():
    def antworten(_eintrag):
        return 200, {
            "data": [
                {"index": 0, "embedding": [1.0, 0.0, 0.0, 0.0]},
                {"index": 0, "embedding": [0.0, 1.0, 0.0, 0.0]},
            ]
        }

    with _Fake(antworten) as fake:
        einbettung = ApiEinbettung(fake.basis, MODELL, SCHLUESSEL, BREITE)
        with pytest.raises(ValueError, match="Indexfolge"):
            einbettung.vektoren(["a", "b"])


def test_falsche_breite():
    def antworten(_eintrag):
        return 200, {
            "data": [
                {"index": 0, "embedding": [1.0, 0.0, 0.0, 0.0]},
                {"index": 1, "embedding": [1.0, 0.0]},
            ]
        }

    with _Fake(antworten) as fake:
        einbettung = ApiEinbettung(fake.basis, MODELL, SCHLUESSEL, BREITE)
        with pytest.raises(ValueError, match="Breite 2, erwartet 4"):
            einbettung.vektoren(["a", "b"])


def test_http_fehler_ohne_schluessel_im_text(caplog, capsys):
    kodiert = quote(SCHLUESSEL, safe="")

    def antworten(eintrag):
        assert eintrag["authorization"] == f"Bearer {SCHLUESSEL}"
        meldung = f"ungueltig {SCHLUESSEL} {kodiert}"
        return 401, {"error": {"message": meldung}}

    caplog.set_level(logging.DEBUG)
    with _Fake(antworten) as fake:
        einbettung = ApiEinbettung(fake.basis + "/api/v1", MODELL, SCHLUESSEL, BREITE)
        with pytest.raises(EinbettungApiFehler) as info:
            einbettung.vektoren(["Hallo"])
    text = str(info.value)
    assert "401" in text
    assert SCHLUESSEL not in text
    assert kodiert not in text
    assert SCHLUESSEL not in repr(info.value)
    assert info.value.__cause__ is None
    assert info.value.__context__ is None
    assert SCHLUESSEL not in caplog.text
    assert kodiert not in caplog.text
    gefangen = capsys.readouterr()
    assert SCHLUESSEL not in gefangen.out
    assert SCHLUESSEL not in gefangen.err
    assert kodiert not in gefangen.out
    assert kodiert not in gefangen.err


def test_nicht_erreichbar_ohne_schluessel_im_text(caplog, capsys):
    caplog.set_level(logging.DEBUG)
    einbettung = ApiEinbettung(
        "http://127.0.0.1:1",
        MODELL,
        SCHLUESSEL,
        BREITE,
        wartezeit=1,
    )
    with pytest.raises(EinbettungApiFehler) as info:
        einbettung.vektoren(["Hallo"])
    text = str(info.value)
    assert SCHLUESSEL not in text
    assert quote(SCHLUESSEL, safe="") not in text
    assert info.value.__cause__ is None
    assert info.value.__context__ is None
    assert SCHLUESSEL not in caplog.text
    gefangen = capsys.readouterr()
    assert SCHLUESSEL not in gefangen.out
    assert SCHLUESSEL not in gefangen.err


def test_leere_liste_ohne_anfrage():
    einbettung = ApiEinbettung(
        "http://127.0.0.1:1",
        MODELL,
        SCHLUESSEL,
        BREITE,
        wartezeit=1,
    )
    assert einbettung.vektoren([]) == []


def test_parameter_ohne_schluessel_im_text():
    with pytest.raises(ValueError):
        ApiEinbettung("", MODELL, SCHLUESSEL, BREITE)
    with pytest.raises(ValueError):
        ApiEinbettung("ftp://example.test/v1", MODELL, SCHLUESSEL, BREITE)
    with pytest.raises(ValueError):
        ApiEinbettung("http://127.0.0.1", "  ", SCHLUESSEL, BREITE)
    with pytest.raises(ValueError):
        ApiEinbettung("http://127.0.0.1", MODELL, "", BREITE)
    with pytest.raises(ValueError):
        ApiEinbettung("http://127.0.0.1", MODELL, SCHLUESSEL, 0)
    geheim = "oben\nunten-schluessel"
    with pytest.raises(ValueError) as info:
        ApiEinbettung("http://127.0.0.1", MODELL, geheim, BREITE)
    assert geheim not in str(info.value)
    assert "unten-schluessel" not in str(info.value)
    einbettung = ApiEinbettung(
        f"http://127.0.0.1/{SCHLUESSEL}/v1",
        MODELL,
        SCHLUESSEL,
        BREITE,
    )
    assert SCHLUESSEL not in repr(einbettung)
    with pytest.raises(TypeError):
        einbettung.vektoren("kein text")


def test_kern_nutzt_api_einbettung(tmp_path):
    tabelle = {
        "Wie erreiche ich Avatari?": [1.0, 0.0, 0.0, 0.0],
        "Kontakt zu Avatari": [1.0, 0.0, 0.0, 0.0],
        "Pool": [0.0, 1.0, 0.0, 0.0],
        "Schwimmbad": [0.0, 0.0, 1.0, 0.0],
    }

    def antworten(eintrag):
        texte = eintrag["koerper"]["input"]
        daten = [
            {"index": i, "embedding": tabelle[text]}
            for i, text in enumerate(texte)
        ]
        daten.reverse()
        return 200, {"data": daten}

    pfad = tmp_path / "api.sqlite"
    with _Fake(antworten) as fake:
        einbettung = ApiEinbettung(
            fake.basis + "/api/v1",
            MODELL,
            SCHLUESSEL,
            BREITE,
        )
        kern = MiniKI(pfad, einbettung)
        kennung = kern.merken(
            "Wie erreiche ich Avatari?",
            "Die Kontaktdaten stehen auf der Webseite von Avatari.",
            bewertung="gut",
        )
        treffer = kern.finden("Kontakt zu Avatari")
        assert treffer is not None
        assert treffer["id"] == kennung
        assert treffer["aehnlichkeit"] == 1.0
        assert kern.formen(kennung, ["Pool", "Schwimmbad"]) == 2
        assert kern.finden("Pool")["id"] == kennung
        assert kern.finden("Schwimmbad")["id"] == kennung
        assert fake.empfangen[0]["koerper"]["input"] == [
            "Wie erreiche ich Avatari?"
        ]
        assert fake.empfangen[0]["koerper"]["model"] == MODELL
        assert fake.empfangen[0]["authorization"] == f"Bearer {SCHLUESSEL}"
        formulierungen = [
            eintrag["koerper"]["input"]
            for eintrag in fake.empfangen
            if eintrag["koerper"]["input"] == ["Pool", "Schwimmbad"]
        ]
        assert formulierungen == [["Pool", "Schwimmbad"]]
    conn = sqlite3.connect(pfad)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    meta = dict(conn.execute("SELECT schluessel, wert FROM meta"))
    conn.close()
    assert meta["modell"] == MODELL
    assert meta["breite"] == str(BREITE)
    for datei in tmp_path.iterdir():
        if datei.is_file():
            assert SCHLUESSEL.encode("utf-8") not in datei.read_bytes()
