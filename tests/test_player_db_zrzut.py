"""`player_stats` nie istnieje w kontenerze — zrzut jest jedynym zrodlem goli.

STAN ZASTANY (2026-09-07, dowod z logow produkcji). `data/footstats_backtest.db`
jest wykluczony i z `.dockerignore` (linia 11), i z `.gcloudignore` (`/data/*`),
wiec w kontenerze jobow tej bazy NIE MA. sqlite3 tworzy pusty plik, a pierwszy
odczyt konczy sie `no such table: player_stats`. Jeden przebieg 06.09 zostawil
105 takich wpisow na stderr:

    player_db: nie moge odczytac goli AZ Alkmaar/2026
    (OperationalError: no such table: player_stats) — goal_share = 0,
    korekta lambda za kontuzje NIE zadziala

Skutek siega dalej niz sama korekta lambda: `_policz_edge_absencji` wychodzi
wtedy na `continue`, wiec `p_over_abs`, `edge_absencje` i `rynek_p_over` nie
powstaja NIGDY. Caly kanal team-news byl przez to martwy niezaleznie od tego,
czy FotMob odpowiada — a odpowiada, 121 meczow dziennie.

Zrzut `data/player_stats.json` (`scripts/eksport_player_stats.py`) jedzie
w obrazie jak `team_mappings.json` i sluzy WYLACZNIE do odczytu.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from footstats.core import player_db as pdb


@pytest.fixture(autouse=True)
def czysty_cache():
    pdb._zrzut_goli.cache_clear()
    yield
    pdb._zrzut_goli.cache_clear()


def _zrzut(tmp_path, wiersze):
    p = tmp_path / "player_stats.json"
    p.write_text(json.dumps(wiersze), encoding="utf-8")
    return p


def _pusta_baza(tmp_path):
    """Baza BEZ tabeli — dokladnie to, co sqlite3 tworzy w kontenerze."""
    p = tmp_path / "pusta.db"
    sqlite3.connect(p).close()
    return p


def test_brak_tabeli_siega_do_zrzutu(tmp_path, monkeypatch):
    monkeypatch.setattr(pdb, "SCIEZKA_ZRZUTU", _zrzut(tmp_path, [
        {"name": "Kowalski", "team_norm": "legia", "season": 2026, "goals": 6},
        {"name": "Nowak", "team_norm": "legia", "season": 2026, "goals": 2},
    ]))
    udzialy = pdb.team_goal_shares("Legia", 2026, db_path=_pusta_baza(tmp_path))
    assert udzialy == {"Kowalski": 0.75, "Nowak": 0.25}


def test_bez_zrzutu_dalej_zwraca_pusto_i_nie_wybucha(tmp_path, monkeypatch):
    monkeypatch.setattr(pdb, "SCIEZKA_ZRZUTU", tmp_path / "nie_ma.json")
    assert pdb.team_goal_shares("Legia", 2026, db_path=_pusta_baza(tmp_path)) == {}


def test_baza_wygrywa_ze_zrzutem(tmp_path, monkeypatch):
    """Zrzut to awaryjne zrodlo, nie nadpisanie swiezych danych."""
    baza = tmp_path / "pelna.db"
    pdb.init_player_table(baza)
    with sqlite3.connect(baza) as con:
        con.execute(
            "INSERT INTO player_stats (name, team_norm, team_display, league,"
            " season, goals, assists, minutes) VALUES (?,?,?,?,?,?,?,?)",
            ("Zywy", "legia", "Legia", "POL", 2026, 10, 0, 900))
    monkeypatch.setattr(pdb, "SCIEZKA_ZRZUTU", _zrzut(tmp_path, [
        {"name": "Zamrozony", "team_norm": "legia", "season": 2026, "goals": 5}]))
    assert pdb.team_goal_shares("Legia", 2026, db_path=baza) == {"Zywy": 1.0}


def test_nieznana_druzyna_to_pusty_wynik_nie_blad(tmp_path, monkeypatch):
    monkeypatch.setattr(pdb, "SCIEZKA_ZRZUTU", _zrzut(tmp_path, [
        {"name": "Kowalski", "team_norm": "legia", "season": 2026, "goals": 6}]))
    assert pdb.team_goal_shares("Widzew", 2026, db_path=_pusta_baza(tmp_path)) == {}


def test_zrzut_respektuje_sezon(tmp_path, monkeypatch):
    monkeypatch.setattr(pdb, "SCIEZKA_ZRZUTU", _zrzut(tmp_path, [
        {"name": "Stary", "team_norm": "legia", "season": 2024, "goals": 9},
        {"name": "Nowy", "team_norm": "legia", "season": 2026, "goals": 3}]))
    baza = _pusta_baza(tmp_path)
    assert pdb.team_goal_shares("Legia", 2026, db_path=baza) == {"Nowy": 1.0}
    assert pdb.team_goal_shares("Legia", 2024, db_path=baza) == {"Stary": 1.0}


def test_recent_cofa_sie_po_sezonach_takze_w_zrzucie(tmp_path, monkeypatch):
    monkeypatch.setattr(pdb, "SCIEZKA_ZRZUTU", _zrzut(tmp_path, [
        {"name": "Stary", "team_norm": "legia", "season": 2024, "goals": 9}]))
    out = pdb.team_goal_shares_recent("Legia", 2026, lookback=2,
                                      db_path=_pusta_baza(tmp_path))
    assert out == {"Stary": 1.0}


def test_zepsuty_zrzut_nie_wysadza_pipeline(tmp_path, monkeypatch):
    p = tmp_path / "player_stats.json"
    p.write_text("{to nie jest json", encoding="utf-8")
    monkeypatch.setattr(pdb, "SCIEZKA_ZRZUTU", p)
    assert pdb.team_goal_shares("Legia", 2026, db_path=_pusta_baza(tmp_path)) == {}


def test_zrzut_produkcyjny_istnieje_i_ma_biezacy_sezon():
    """Straznik na plik, ktory realnie jedzie w obrazie.

    Zrzut z samymi starymi sezonami przechodzi wszystkie testy powyzej i jest
    bezuzyteczny na produkcji, bo `team_goal_shares_recent` cofa sie tylko
    o `lookback` sezonow.
    """
    from footstats.core.daily_phases import _current_season

    assert pdb.SCIEZKA_ZRZUTU.exists(), (
        "brak data/player_stats.json — odpal scripts/eksport_player_stats.py")
    dane = json.loads(pdb.SCIEZKA_ZRZUTU.read_text(encoding="utf-8"))
    assert len(dane) > 500
    sezony = {int(w["season"]) for w in dane}
    biezacy = _current_season()
    assert sezony & {biezacy, biezacy - 1, biezacy - 2}, (
        f"zrzut ma sezony {sorted(sezony)}, a biezacy to {biezacy} — odswiez go")
