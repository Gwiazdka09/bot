"""Smierc calego kanalu team-news nie moze byc widoczna tylko na DEBUG.

STAN ZASTANY (2026-09-07). `_wzbogac_team_news` konczylo sie tak:

    dane = _pobierz_team_news(...)
    if not dane:
        log.debug("team-news: zrodlo oddalo pusta liste")
        return

Docstring tlumaczyl to zdaniem „Powod zglosil juz adapter, na ERROR" — ale
adapter krzyczy WYLACZNIE gdy padnie zapytanie o liste dnia. Gdy lista przyjdzie
poprawnie i po prostu ZERO meczow pasuje do naszych kandydatow, jedynym sladem
jest `log.debug` w `fotmob.fetch_dla`. Na produkcji (poziom INFO) nie ma wiec
zadnego sladu, a przebieg konczy sie sukcesem.

Zmierzone: 06.09 job `footstats-final` przeszedl cala faze final i w 258 liniach
stdout NIE MA ani jednej wzmianki o team-news. Kanal byl martwy od wlaczenia
flagi i nikt nie mial jak tego zobaczyc.

To ten sam wzorzec, ktory opisuje `test_ciche_except_audit`: cisza znaczaca
„wszystko gra", gdy nic nie gra.
"""
from __future__ import annotations

import logging

import pytest

from footstats.core import daily_phases as dp


@pytest.fixture(autouse=True)
def flaga_wlaczona(monkeypatch):
    monkeypatch.setenv(dp.FLAGA_TEAM_NEWS, "1")


def _kandydaci() -> list[dict]:
    return [{"gospodarz": "Legia", "goscie": "Lech", "pw": 45.0, "pr": 27.0,
             "pp": 28.0, "o25": 52.0}]


def test_pusta_lista_ze_zrodla_jest_glosna(caplog, monkeypatch):
    monkeypatch.setattr(dp, "_pobierz_team_news", lambda *a, **kw: [])
    with caplog.at_level(logging.WARNING):
        dp._wzbogac_team_news(_kandydaci())
    assert "team-news" in caplog.text
    assert "1" in caplog.text, "komunikat ma podac, ilu kandydatow zostalo bez danych"


def test_zero_dopasowan_mimo_niepustej_listy_jest_glosne(caplog, monkeypatch):
    """Najgrozniejszy wariant: zrodlo dziala, a i tak nie mamy nic."""
    class _TN:
        home, away = "Zupelnie Inny", "Klub"
        source, sklad_jest_prognoza = "fotmob", False
        xi_home = xi_away = ()
        absencje_home = absencje_away = ()
        sedzia, sedzia_stats = None, {}

    monkeypatch.setattr(dp, "_pobierz_team_news", lambda *a, **kw: [_TN()])
    monkeypatch.setattr(dp, "_dopasuj_team_news", lambda *a, **kw: None)
    with caplog.at_level(logging.WARNING):
        dp._wzbogac_team_news(_kandydaci())
    assert "ZADEN" in caplog.text or "zaden" in caplog.text.lower()


def test_wylaczona_flaga_milczy(caplog, monkeypatch):
    """Wylaczona flaga to swiadomy wybor, nie awaria — tu cisza jest poprawna."""
    monkeypatch.setenv(dp.FLAGA_TEAM_NEWS, "0")
    monkeypatch.setattr(dp, "_pobierz_team_news", lambda *a, **kw: [])
    with caplog.at_level(logging.DEBUG):
        dp._wzbogac_team_news(_kandydaci())
    assert "team-news" not in caplog.text


def test_brak_kandydatow_milczy(caplog, monkeypatch):
    """Zero kandydatow to nie awaria zrodla."""
    monkeypatch.setattr(dp, "_pobierz_team_news", lambda *a, **kw: [])
    with caplog.at_level(logging.WARNING):
        dp._wzbogac_team_news([])
    assert "team-news" not in caplog.text
