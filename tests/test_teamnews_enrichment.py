"""Wpiecie FotMoba w faze enrichmentu (`core/daily_phases.py`).

Ta faza jest na goracej sciezce: `footstats-final` odpala `daily_agent --faza
final` codziennie o 11:00. Potwierdzone pomiarem na prod 30.08 — 9 z 38 nog
fazy final ma decision_score > 80, a to wymaga punktow za sklad albo sedziego.

Trzy rzeczy pod ochrona:
  1. flaga dziala w OBIE strony (wylaczona = zero wywolan zrodla),
  2. pokrycie jest RAPORTOWANE, a zerowe pokrycie jest ALARMEM — to jedyny
     sposob wykrycia zmiany schematu FotMoba, ktora nie rzuca wyjatkiem,
  3. zdrowy przebieg nie halasuje (szum zabija alarmy tak samo jak cisza).
"""
from __future__ import annotations

import logging

import pytest

from footstats.core import daily_phases as dp
from footstats.scrapers.teamnews.base import Absencja, TeamNews


def _tn(home="Chelsea", away="Brighton", typ="predicted"):
    return TeamNews(
        source="fotmob", home=home, away=away, date="2026-08-30", typ_skladu=typ,
        xi_home=tuple(f"Gospodarz {i}" for i in range(11)),
        xi_away=tuple(f"Gosc {i}" for i in range(11)),
        absencje_home=(Absencja("Enzo Fernandez", "injury", "Doubtful", False),),
        absencje_away=(Absencja("Kaoru Mitoma", "injury", "Mid September 2026", True),),
        sedzia="Michael Oliver",
        sedzia_stats={"avg_yellow": 3.8, "n_matches": 54},
    )


@pytest.fixture
def kandydat():
    return {"gospodarz": "Chelsea", "goscie": "Brighton", "o25": 50.0, "bt": 50.0}


# ── flaga ───────────────────────────────────────────────────────────────────

def test_flaga_wylaczona_nie_wola_zrodla(monkeypatch, kandydat):
    """Domyslnie OFF do czasu smoke'a na zywym potoku."""
    monkeypatch.delenv(dp.FLAGA_TEAM_NEWS, raising=False)

    def _nie_wolno(*a, **k):
        raise AssertionError("zrodlo wolane mimo wylaczonej flagi")

    monkeypatch.setattr(dp, "_pobierz_team_news", _nie_wolno)
    dp._wzbogac_team_news([kandydat])
    assert "team_news_source" not in kandydat


def test_flaga_wlaczona_wzbogaca_kandydata(monkeypatch, kandydat):
    monkeypatch.setenv(dp.FLAGA_TEAM_NEWS, "1")
    monkeypatch.setattr(dp, "_pobierz_team_news", lambda data, pary: [_tn()])

    dp._wzbogac_team_news([kandydat])

    assert kandydat["team_news_source"] == "fotmob"
    assert kandydat["lineup_ok"] is True
    assert kandydat["referee_name"] == "Michael Oliver"
    assert kandydat["referee_stats"]["n_matches"] == 54
    assert len(kandydat["startXI_home"]) == 11


def test_do_lambdy_ida_TYLKO_absencje_pewne(monkeypatch, kandydat):
    """"Doubtful" i brak danych nie moga wchodzic do korekty — inaczej model
    liczy strate zawodnika, ktory zagra."""
    monkeypatch.setenv(dp.FLAGA_TEAM_NEWS, "1")
    monkeypatch.setattr(dp, "_pobierz_team_news", lambda data, pary: [_tn()])

    dp._wzbogac_team_news([kandydat])

    assert kandydat["absencje_pewne_home"] == 0   # jedyna to "Doubtful"
    assert kandydat["absencje_pewne_away"] == 1   # "Mid September 2026"


def test_lastStarting11_oznaczony_jako_slabszy(monkeypatch, kandydat):
    """Ostatni sklad to nie prognoza — odbiorca musi to widziec."""
    monkeypatch.setenv(dp.FLAGA_TEAM_NEWS, "1")
    monkeypatch.setattr(dp, "_pobierz_team_news",
                        lambda data, pary: [_tn(typ="lastStarting11")])

    dp._wzbogac_team_news([kandydat])
    assert kandydat["team_news_prognoza"] is False


def test_nazwy_druzyn_dopasowywane_mimo_roznej_pisowni(monkeypatch):
    """FotMob pisze "Brighton & Hove Albion", Bzzoiro "Brighton"."""
    monkeypatch.setenv(dp.FLAGA_TEAM_NEWS, "1")
    monkeypatch.setattr(dp, "_pobierz_team_news",
                        lambda data, pary: [_tn(away="Brighton & Hove Albion")])
    k = {"gospodarz": "Chelsea", "goscie": "Brighton"}

    dp._wzbogac_team_news([k])
    assert k.get("team_news_source") == "fotmob"


# ── pokrycie i glosnosc ─────────────────────────────────────────────────────

def test_pokrycie_jest_raportowane(monkeypatch, caplog, kandydat):
    monkeypatch.setenv(dp.FLAGA_TEAM_NEWS, "1")
    monkeypatch.setattr(dp, "_pobierz_team_news", lambda data, pary: [_tn()])

    with caplog.at_level(logging.INFO):
        dp._wzbogac_team_news([kandydat, {"gospodarz": "X", "goscie": "Y"}])

    assert "1/2" in caplog.text


def test_zerowe_pokrycie_to_ALARM_a_nie_cisza(monkeypatch, caplog, kandydat):
    """Zrodlo oddalo dane, ale zaden mecz sie nie dopasowal. Bez tego alarmu
    zmiana schematu FotMoba bylaby niewidoczna: zero wyjatkow, zero wzbogacen,
    przebieg konczy sie sukcesem."""
    monkeypatch.setenv(dp.FLAGA_TEAM_NEWS, "1")
    monkeypatch.setattr(dp, "_pobierz_team_news",
                        lambda data, pary: [_tn(home="Zupelnie", away="Inne")])

    with caplog.at_level(logging.WARNING):
        dp._wzbogac_team_news([kandydat])

    assert any(r.levelno >= logging.WARNING for r in caplog.records)
    assert "0/1" in caplog.text


def test_puste_zrodlo_alarmuje_ze_skutkiem(monkeypatch, caplog, kandydat):
    """ODWROCONE 07.09.2026 — poprzednia wersja opierala sie na nieprawdzie.

    Test nazywal sie `..._nie_alarmuje_drugi_raz` i tlumaczyl cisze tym, ze
    „powod zglosil juz adapter na ERROR". Adapter krzyczy jednak WYLACZNIE gdy
    padnie zapytanie o liste dnia. Gdy lista przyjdzie poprawnie i po prostu
    ZERO meczow pasuje do naszych kandydatow, `fetch_dla` loguje to na DEBUG —
    czyli na produkcji nie zostaje zaden slad, a `_wzbogac_team_news` konczy sie
    cicho i przebieg raportuje sukces.

    Zmierzone: job `footstats-final` z 06.09 przeszedl cala faze final i w 258
    liniach stdout nie ma ANI JEDNEJ wzmianki o team-news. Kanal byl martwy od
    wlaczenia flagi 05.09 i nie bylo jak tego zobaczyc — `model_log` mial
    1078 wierszy i zero z jakimkolwiek polem team-news.

    Przy twardej awarii adaptera powstana teraz dwie linie, i to jest w porzadku:
    adapter mowi CO padlo, ta linia mowi ILE nas to kosztowalo. To nie duplikat,
    tylko przyczyna i skutek.
    """
    monkeypatch.setenv(dp.FLAGA_TEAM_NEWS, "1")
    monkeypatch.setattr(dp, "_pobierz_team_news", lambda data, pary: [])

    with caplog.at_level(logging.WARNING):
        dp._wzbogac_team_news([kandydat])

    ostrzezenia = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert ostrzezenia, "smierc calego kanalu nie moze byc widoczna tylko na DEBUG"
    assert "team-news" in caplog.text
    assert "1" in caplog.text, "komunikat ma podac, ilu kandydatow zostalo bez danych"


def test_brak_kandydatow_nie_wola_zrodla(monkeypatch):
    """Pusta lista kandydatow = nie ma po co placic requestem."""
    monkeypatch.setenv(dp.FLAGA_TEAM_NEWS, "1")

    def _nie_wolno(*a, **k):
        raise AssertionError("zrodlo wolane dla pustej listy kandydatow")

    monkeypatch.setattr(dp, "_pobierz_team_news", _nie_wolno)
    dp._wzbogac_team_news([])


def test_enrichment_wola_team_news_przed_torem_api_football(monkeypatch, caplog):
    """FotMob ma pierwszenstwo i nie moze byc zablokowany brakiem klucza AF —
    konto jest zawieszone od 01.08, wiec guard `if not api_key` odcinalby
    rowniez dzialajace zrodlo."""
    wolane = {"team_news": False}
    monkeypatch.setattr(dp, "_wzbogac_team_news",
                        lambda k: wolane.__setitem__("team_news", True))

    dp._enrichuj_finalna_faza([{"gospodarz": "A", "goscie": "B"}], "")

    assert wolane["team_news"] is True


def test_zrodlo_dostaje_pary_kandydatow_a_nie_caly_dzien(monkeypatch):
    """Filtr musi zejsc do zrodla, inaczej potok placi 483 requestami dziennie
    za dane kilkudziesieciu meczow."""
    widziane = {}

    def _stub(data, pary):
        widziane["pary"] = pary
        return [_tn()]

    monkeypatch.setenv(dp.FLAGA_TEAM_NEWS, "1")
    monkeypatch.setattr(dp, "_pobierz_team_news", _stub)

    dp._wzbogac_team_news([{"gospodarz": "Chelsea", "goscie": "Brighton"},
                           {"gospodarz": "Leeds", "goscie": "Brentford"}])

    assert widziane["pary"] == [("Chelsea", "Brighton"), ("Leeds", "Brentford")]
