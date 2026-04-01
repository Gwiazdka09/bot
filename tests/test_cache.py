"""Testy utils/cache.py – RAM cache + budżet API-Football."""
import json
import tempfile
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import footstats.utils.cache as cache_mod
from footstats.utils.cache import (
    _cache_get, _cache_set, _RAM_CACHE,
    _af_budget_load, _af_budget_save, af_budget_status,
    AF_BUDGET_DAILY,
)
from footstats.config import CACHE_TTL_MIN


class TestCacheRAM:

    def setup_method(self):
        _RAM_CACHE.clear()

    def test_cache_miss(self):
        assert _cache_get("nieistnieje::klucz") is None

    def test_cache_set_i_get(self):
        dane = {"wynik": 42}
        _cache_set("test::klucz", dane)
        assert _cache_get("test::klucz") == dane

    def test_cache_ttl_wygasniecie(self):
        klucz = "test::ttl_expiry"
        _cache_set(klucz, {"v": 1})
        ts_stary = datetime.now() - timedelta(minutes=CACHE_TTL_MIN + 1)
        _RAM_CACHE[klucz]["ts"] = ts_stary
        assert _cache_get(klucz) is None

    def test_cache_ttl_wciaz_wazny(self):
        klucz = "test::ttl_valid"
        _cache_set(klucz, {"v": 2})
        assert _cache_get(klucz) is not None

    def test_nadpisanie_klucza(self):
        _cache_set("test::nadpisz", {"v": 1})
        _cache_set("test::nadpisz", {"v": 2})
        assert _cache_get("test::nadpisz")["v"] == 2

    def test_rozne_klucze_niezalezne(self):
        _cache_set("test::k1", {"v": 1})
        _cache_set("test::k2", {"v": 2})
        assert _cache_get("test::k1")["v"] == 1
        assert _cache_get("test::k2")["v"] == 2


class TestBudzetAF:

    def test_status_zwraca_dict(self):
        with tempfile.TemporaryDirectory() as td:
            plik = Path(td) / "budget.json"
            with patch.object(cache_mod, "AF_BUDGET_FILE", plik), \
                 patch.object(cache_mod, "CACHE_DIR", Path(td)):
                status = af_budget_status()
                assert isinstance(status, dict)

    def test_status_klucze(self):
        with tempfile.TemporaryDirectory() as td:
            plik = Path(td) / "budget.json"
            with patch.object(cache_mod, "AF_BUDGET_FILE", plik), \
                 patch.object(cache_mod, "CACHE_DIR", Path(td)):
                status = af_budget_status()
                wymagane = {"dzien", "uzyto", "pozostalo", "limit", "procent",
                            "krytyczny", "ostrzezenie"}
                assert wymagane.issubset(status.keys())

    def test_status_reset_nowego_dnia(self):
        z_wczoraj = {"dzien": "2000-01-01", "uzyto": 99, "historia": []}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                         delete=False, encoding="utf-8") as f:
            json.dump(z_wczoraj, f)
            tmp = Path(f.name)
        try:
            with patch.object(cache_mod, "AF_BUDGET_FILE", tmp), \
                 patch.object(cache_mod, "CACHE_DIR", tmp.parent):
                b = _af_budget_load()
                assert b.get("uzyto") == 0
        finally:
            tmp.unlink(missing_ok=True)

    def test_save_i_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            plik = Path(td) / "budget.json"
            with patch.object(cache_mod, "AF_BUDGET_FILE", plik), \
                 patch.object(cache_mod, "CACHE_DIR", Path(td)):
                dane = {
                    "dzien": datetime.now().strftime("%Y-%m-%d"),
                    "uzyto": 42,
                    "historia": [],
                }
                _af_budget_save(dane)
                assert plik.exists()
                zaladowane = _af_budget_load()
                assert zaladowane.get("uzyto") == 42

    def test_load_brak_pliku(self):
        nieistn = Path("/nieistniejacy_katalog_xyz/budget.json")
        with patch.object(cache_mod, "AF_BUDGET_FILE", nieistn), \
             patch.object(cache_mod, "CACHE_DIR", Path("/nieistniejacy_katalog_xyz")):
            b = _af_budget_load()
            assert isinstance(b, dict)
            assert b.get("uzyto") == 0

    def test_load_uszkodzony_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                          delete=False, encoding="utf-8") as f:
            f.write("{ BLAD BLAD }")
            tmp = Path(f.name)
        try:
            with patch.object(cache_mod, "AF_BUDGET_FILE", tmp), \
                 patch.object(cache_mod, "CACHE_DIR", tmp.parent):
                b = _af_budget_load()
                assert isinstance(b, dict)
                assert b.get("uzyto") == 0
        finally:
            tmp.unlink(missing_ok=True)
