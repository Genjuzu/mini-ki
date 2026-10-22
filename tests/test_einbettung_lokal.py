"""Lokale Einbettung. Der Lauf mit Gewichten trägt den Marker `modell`."""

import math

import pytest

from mini_ki.einbettung_lokal import LokaleEinbettung

MODELL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def _kosinus(links: list[float], rechts: list[float]) -> float:
    skalar = sum(x * y for x, y in zip(links, rechts, strict=True))
    norm_links = math.sqrt(sum(x * x for x in links))
    norm_rechts = math.sqrt(sum(y * y for y in rechts))
    return skalar / (norm_links * norm_rechts)


def test_schnittstelle_ohne_gewichte(monkeypatch, tmp_path):
    def oeffnen(modell, cache):
        raise AssertionError((modell, cache))

    monkeypatch.setattr("mini_ki.einbettung_lokal._fastembed_oeffnen", oeffnen)
    einbettung = LokaleEinbettung(tmp_path / "cache")
    assert einbettung.modell == MODELL
    assert einbettung.breite == 384
    assert einbettung.vektoren([]) == []


def test_laedt_einmal_pro_objekt(monkeypatch, tmp_path):
    aufrufe = []

    class Attrappe:
        def embed(self, texte):
            return [[float(len(text))] * 384 for text in texte]

    def oeffnen(modell, cache):
        assert modell == MODELL
        aufrufe.append(cache)
        return Attrappe()

    monkeypatch.setattr("mini_ki.einbettung_lokal._fastembed_oeffnen", oeffnen)
    cache = tmp_path / "cache"
    einbettung = LokaleEinbettung(cache)
    erste = einbettung.vektoren(["Pool"])
    zweite = einbettung.vektoren(["Pool", "Schwimmbad"])
    assert len(erste) == 1 and len(erste[0]) == 384
    assert len(zweite) == 2
    assert aufrufe == [cache]

    anderer_cache = tmp_path / "anderer"
    anderer = LokaleEinbettung(anderer_cache)
    anderer.vektoren(["Frühstück"])
    assert aufrufe == [cache, anderer_cache]


@pytest.mark.modell
def test_pool_gegen_schwimmbad_und_fruehstueck(tmp_path):
    pytest.importorskip("fastembed")
    cache = tmp_path / "cache"
    einbettung = LokaleEinbettung(cache)
    pool, bad, frueh = einbettung.vektoren(["Pool", "Schwimmbad", "Frühstück"])
    geladen = einbettung._geladen
    nochmal = einbettung.vektoren(["Pool"])
    assert einbettung._geladen is geladen
    assert len(pool) == 384
    assert _kosinus(pool, bad) >= 0.80
    assert _kosinus(pool, frueh) < 0.5
    assert nochmal[0] == pytest.approx(pool)
