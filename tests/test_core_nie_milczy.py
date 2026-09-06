"""J1 w rdzeniu: awaria bazy i awaria cache'u udawały „po prostu brak danych".

Trzy moduły, jeden kształt: funkcja zwraca pustą kolekcję albo `None`, a to samo
oznacza dwie zupełnie różne rzeczy —

    "tej drużyny nie ma w bazie"        stan NORMALNY
    "baza jest niedostępna/uszkodzona"  AWARIA

Bez logu są nie do odróżnienia, a skutki są odwrotne: pierwsze nie wymaga
niczego, drugie cicho wyłącza korektę λ za kontuzje, pali dzienny budżet
API-Football albo zostawia Groqa bez danych o skuteczności rynków.

Najgroźniejszy przypadek: `except Exception: pass` obejmujący CAŁY blok
auto-treningu w `backtest`. Kalibracja mogła nigdy się nie przeliczyć, a
`save_result` i tak kończył się sukcesem.
"""
from __future__ import annotations

import logging
import sqlite3

import pytest

from footstats.core import backtest as bt
from footstats.core import player_db as pdb
from footstats.utils import cache as uc


# ── backtest: auto-trening i kalibracja do promptu ──────────────────────────

def test_przerwany_blok_auto_treningu_jest_glosny(caplog, monkeypatch):
    """`except Exception: pass` obejmował cały blok. Cicho znaczyło: kalibracja
    może nigdy się nie przeliczyć, a zapis wyniku i tak melduje sukces."""
    def _wybuch(*_a, **_k):
        raise RuntimeError("baza padla w srodku bloku auto-treningu")

    # `_connect` jest pierwsza rzecza w bloku — jego padniecie odtwarza dokladnie
    # ten scenariusz, ktory straznik `except Exception: pass` polykal.
    monkeypatch.setattr(bt, "_connect", _wybuch)

    with caplog.at_level(logging.WARNING):
        bt._sprawdz_auto_trening()

    assert "kalibracja NIE" in caplog.text


def test_brak_kalibracji_do_promptu_jest_glosny(caplog, monkeypatch):
    """Pusty string wstrzykuje się do promptu bez śladu — Groq typuje tak,
    jakby danych o skuteczności rynków nie było. Wygląda identycznie jak
    „za mało próbek", które jest stanem normalnym."""
    def _wybuch(*_a, **_k):
        raise RuntimeError("baza niedostepna")

    monkeypatch.setattr(bt, "get_stats", _wybuch)

    with caplog.at_level(logging.WARNING):
        assert bt.pobierz_kalibracje_backtest() == ""

    assert "BEZ danych o skutecznosci" in caplog.text


# ── cache API-Football: cisza kosztuje budżet ───────────────────────────────

@pytest.fixture(autouse=True)
def _zeruj_flagi_jednorazowe():
    """Ostrzeżenia w `utils.cache` lecą RAZ NA PROCES — bez zerowania testy
    zależałyby od kolejności."""
    uc._zgloszono_brak_katalogu = False
    uc._zgloszono_uszkodzony_plik = False
    yield
    uc._zgloszono_brak_katalogu = False
    uc._zgloszono_uszkodzony_plik = False


def test_uszkodzony_plik_cache_mowi_ze_budzet_bedzie_ginal(caplog, monkeypatch, tmp_path):
    """`{}` znaczy „cache pusty", czyli to samo co pierwszy przebieg. Różnica
    jest zasadnicza: uszkodzony plik NIE naprawi się sam i każde zapytanie
    poleci do sieci, aż ktoś go skasuje."""
    zly = tmp_path / "af_cache.json"
    zly.write_text("{to nie jest json", encoding="utf-8")
    monkeypatch.setattr(uc, "AF_CACHE_FILE", zly)
    monkeypatch.setattr(uc, "CACHE_DIR", tmp_path)

    with caplog.at_level(logging.WARNING):
        assert uc._af_load_disk_cache() == {}

    assert "budzet API bedzie ginal" in caplog.text


def test_ostrzezenie_o_cache_leci_RAZ_a_nie_przy_kazdym_zapytaniu(caplog, monkeypatch, tmp_path):
    """Budżet to 100 zapytań dziennie, a uszkodzony plik jest stanem TRWAŁYM —
    setna kopia tej samej linii topi resztę logu."""
    zly = tmp_path / "af_cache.json"
    zly.write_text("{zepsute", encoding="utf-8")
    monkeypatch.setattr(uc, "AF_CACHE_FILE", zly)
    monkeypatch.setattr(uc, "CACHE_DIR", tmp_path)

    with caplog.at_level(logging.WARNING):
        for _ in range(5):
            uc._af_load_disk_cache()

    assert caplog.text.count("budzet API bedzie ginal") == 1


def test_zdrowy_cache_nie_generuje_szumu(caplog, monkeypatch, tmp_path):
    dobry = tmp_path / "af_cache.json"
    dobry.write_text('{"klucz": {"ts": "2026-08-29T10:00:00", "data": {}}}',
                     encoding="utf-8")
    monkeypatch.setattr(uc, "AF_CACHE_FILE", dobry)
    monkeypatch.setattr(uc, "CACHE_DIR", tmp_path)

    with caplog.at_level(logging.WARNING):
        assert uc._af_load_disk_cache()

    assert caplog.text == ""


# ── player_db: awaria bazy ≠ nieznana drużyna ───────────────────────────────

def _baza_padnie(monkeypatch):
    def _wybuch(*_a, **_k):
        raise sqlite3.Error("baza zablokowana")
    monkeypatch.setattr(pdb, "_connect", _wybuch)


def test_awaria_bazy_przy_goal_share_mowi_o_skutku_dla_lambdy(caplog, monkeypatch, tmp_path):
    """Pusty wynik zeruje `goal_share`, przez co korekta λ za kontuzje przestaje
    działać — a wygląda to jak drużyna bez zapisanych strzelców.

    ZAWĘŻONE 07.09.2026. Od kiedy istnieje zrzut `data/player_stats.json`, sama
    awaria bazy NIE zeruje już goal_share — w kontenerze baza nie istnieje
    w ogóle i to jest stan normalny. Ostrzeżenie należy się dopiero, gdy padnie
    RÓWNIEŻ zrzut, bo dopiero wtedy korekta λ faktycznie umiera. Wcześniej ten
    komunikat leciał 105 razy w jednym przebiegu i był czystym szumem.
    """
    _baza_padnie(monkeypatch)
    monkeypatch.setattr(pdb, "SCIEZKA_ZRZUTU", tmp_path / "nie_ma.json")
    pdb._zrzut_goli.cache_clear()

    with caplog.at_level(logging.WARNING):
        assert pdb.team_goal_shares("Arsenal", 2026) == {}

    assert "korekta lambda" in caplog.text
    assert "Arsenal" in caplog.text
    pdb._zrzut_goli.cache_clear()


def test_awaria_bazy_ze_zrzutem_NIE_hałasuje(caplog, monkeypatch, tmp_path):
    """Kontrola do powyższego: gdy zrzut ratuje sytuację, alarmu nie ma.

    Szum niszczy alarmy tak samo skutecznie jak cisza — a to jest ścieżka,
    którą kontener przechodzi przy KAŻDYM odczycie.
    """
    import json

    _baza_padnie(monkeypatch)
    plik = tmp_path / "player_stats.json"
    plik.write_text(json.dumps([
        {"name": "Saka", "team_norm": "arsenal", "season": 2026, "goals": 8}]),
        encoding="utf-8")
    monkeypatch.setattr(pdb, "SCIEZKA_ZRZUTU", plik)
    pdb._zrzut_goli.cache_clear()

    with caplog.at_level(logging.WARNING):
        assert pdb.team_goal_shares("Arsenal", 2026) == {"Saka": 1.0}

    assert "korekta lambda" not in caplog.text
    pdb._zrzut_goli.cache_clear()


def test_awaria_bazy_przy_skladzie_jest_glosna(caplog, monkeypatch):
    _baza_padnie(monkeypatch)

    with caplog.at_level(logging.WARNING):
        assert pdb.get_team_players("Arsenal", 2026) == []

    assert "nie do odroznienia" in caplog.text


def test_awaria_bazy_przy_statystykach_jest_glosna(caplog, monkeypatch):
    _baza_padnie(monkeypatch)

    with caplog.at_level(logging.WARNING):
        assert pdb.get_team_stats("Arsenal", 2026) is None

    assert "bez nich" in caplog.text


def test_konwertery_pol_opcjonalnych_milcza(caplog):
    """Kontrola: `_optional_float`/`_optional_int` lecą dla każdego pola każdego
    zawodnika, a puste pole w danych źródłowych to stan normalny."""
    with caplog.at_level(logging.WARNING):
        assert pdb._optional_float("bzdura") is None
        assert pdb._optional_int("bzdura") is None
        assert pdb._optional_float(None) is None
        assert pdb._optional_float("1.5") == 1.5

    assert caplog.text == ""
