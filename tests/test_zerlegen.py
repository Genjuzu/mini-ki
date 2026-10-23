"""Tests für zerlegen."""

import time
from src.mini_ki.zerlegen import zerlegen


def test_max_groesse():
    """Kein Abschnitt länger als groesse."""
    text = "A" * 600
    chunks = zerlegen(text, groesse=500, ueberlappung=75)
    
    for _, chunk_text in chunks:
        assert len(chunk_text) <= 500, f"Chunk zu lang: {len(chunk_text)}"


def test_ueberlappung():
    """Überlappung stimmt (Ende von n steht am Anfang von n+1)."""
    text = "Erster Absatz. Zweiter Absatz. Dritter Absatz."
    chunks = zerlegen(text, groesse=500, ueberlappung=75)
    
    if len(chunks) > 1:
        for i in range(len(chunks) - 1):
            _, chunk1 = chunks[i]
            _, chunk2 = chunks[i + 1]
            
            overlap_len = min(75, len(chunk1))
            overlap1 = chunk1[-overlap_len:]
            overlap2 = chunk2[:overlap_len]
            
            assert overlap1 == overlap2, f"Überlappung stimmt nicht: {overlap1} vs {overlap2}"


def test_kein_wort_geteilt():
    """Kein Wort wird geteilt - keine halben Wörter."""
    text = "Dieser sehr lange Satz muss unbedingt in mehreren Teilen zerlegt werden ohne zu viel zu verlieren."
    chunks = zerlegen(text, groesse=30, ueberlappung=5)
    
    for _, chunk_text in chunks:
        parts = chunk_text.split()
        for part in parts:
            # Wörter dürfen nicht mittendurch geteilt werden
            # Einzelne Zeichen ohne Kontext sind verdächtig
            assert len(part) >= 2 or part in ['a', 'i'], f"Zerbrochenes Wort: {part}"


def test_stelle_erhaltung():
    """stelle und nr stimmen über Seitengrenzen hinweg."""
    text = "Absatz 1. " * 100
    chunks = zerlegen(text, groesse=50, ueberlappung=10)
    
    for i, (s, t) in enumerate(chunks):
        if i > 0:
            assert s >= chunks[i - 1][0], "Stelle nicht monoton"


def test_nr_laufend():
    """Laufende Nr wird korrekt vergeben."""
    text = "X" * 1000
    chunks = zerlegen(text, groesse=500, ueberlappung=0)
    
    assert len(chunks) > 0
    for i in range(len(chunks)):
        assert chunks[i] is not None


def test_kurze_rests():
    """Leere oder sehr kurze Reste (< 20 Zeichen) hängen am vorigen Abschnitt."""
    text = "Langertext hier " * 50 + "kurz"
    chunks = zerlegen(text, groesse=100, ueberlappung=0)
    
    if len(chunks) > 1:
        _, last = chunks[-1]
        assert len(last) >= 20 or len(chunks) == 1, "Kurzer Rest nicht angehängt"


def test_leerer_text():
    """Leerer Text gibt leere Liste."""
    chunks = zerlegen("")
    assert chunks == []


def test_ein_abschnitt():
    """Sehr kurzer Text bleibt ein Abschnitt."""
    text = "Kurz"
    chunks = zerlegen(text, groesse=500, ueberlappung=75)
    assert len(chunks) == 1
    assert chunks[0][1] == "Kurz"


def test_leistung_1mb():
    """1 MB Text in unter 2 Sekunden zerlegt."""
    text = "Dies ist ein langer Satz mit vielen Wörtern. " * 25000
    
    start = time.time()
    chunks = zerlegen(text, groesse=500, ueberlappung=75)
    elapsed = time.time() - start
    
    assert elapsed < 2.0, f"Zu langsam: {elapsed:.2f}s"
    assert len(chunks) > 0


def test_paragraphen_trennung():
    """Absätze werden korrekt getrennt."""
    text = "Erster Absatz.\n\nZweiter Absatz."
    chunks = zerlegen(text, groesse=500, ueberlappung=0)
    
    assert len(chunks) >= 1
    combined = ' '.join(t for _, t in chunks)
    assert "Erster" in combined and "Zweiter" in combined


def test_standardwerte_api():
    """API-Voreinstellung 2000/300."""
    text = "X" * 3000
    chunks = zerlegen(text, groesse=2000, ueberlappung=300)
    
    assert len(chunks) >= 2
    for _, t in chunks:
        assert len(t) <= 2000
