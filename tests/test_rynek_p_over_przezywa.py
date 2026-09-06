"""Cena z tamtej chwili musi przezyc, nawet gdy nie umiemy policzyc przewagi.

STAN ZASTANY (2026-09-07). `_policz_edge_absencji` ustawialo `rynek_p_over`
DOPIERO PO bramce:

    if not ud_h and not ud_a:
        continue                  # <- tutaj konczyla sie droga
    ...
    k["rynek_p_over"] = rynek     # <- a cena zapisywala sie dopiero tu

Bramka wypada, gdy znamy nieobecnych, ale nie znamy ich udzialu w golach —
czyli ZAWSZE, kiedy `player_db` jest puste. W kontenerze bylo puste zawsze
(`no such table: player_stats`, 105 wpisow w jednym przebiegu), wiec cena nie
zapisala sie ANI RAZU: `model_log` mial 1078 wierszy i zero z `rynek_p_over`.

Komentarz dwie linie nizej sam argumentuje, dlaczego to zle: „bez ceny, wobec
ktorej liczylismy przewage, nie da sie pozniej orzec, kto mial racje. To jest
cala wartosc tego wpisu." Cena nie zalezy od udzialow golowych — zalezy od
kursow, ktore juz mamy w reku.
"""
from __future__ import annotations

import pytest

from footstats.core import daily_phases as dp


def _kandydat(**nadpisz) -> dict:
    k = {
        "gospodarz": "Legia", "goscie": "Lech",
        "pw": 45.0, "pr": 27.0, "pp": 28.0, "o25": 52.0,
        "lambda_h": 1.55, "lambda_a": 1.20,
        "_absencje_pewne_nazwiska_home": ["Kowalski"],
        "_absencje_pewne_nazwiska_away": [],
        "market_p_over": 0.503,
    }
    k.update(nadpisz)
    return k


def test_cena_zapisana_mimo_pustego_player_db(monkeypatch):
    """Sedno naprawy: brak udzialow nie moze kasowac ceny."""
    monkeypatch.setattr(dp, "_goal_shares_for", lambda *a, **kw: {})
    k = _kandydat()
    dp._policz_edge_absencji([k])
    assert k["rynek_p_over"] == pytest.approx(0.503)
    # Przewagi policzyc sie nie da i to jest w porzadku — ma zostac NIEobecna,
    # a nie zerowa. Zero znaczyloby "policzone i wyszlo zero".
    assert "edge_absencje" not in k
    assert "p_over_abs" not in k


def test_z_udzialami_dalej_liczy_komplet(monkeypatch):
    """Kontrola: naprawa nie moze wylaczyc glownej sciezki."""
    monkeypatch.setattr(dp, "_goal_shares_for",
                        lambda team, side=None: {"Kowalski": 0.4, "Inny": 0.6})
    k = _kandydat()
    dp._policz_edge_absencji([k])
    assert k["rynek_p_over"] == pytest.approx(0.503)
    assert k["p_over_abs"] is not None
    assert k["edge_absencje"] is not None


def test_bez_absencji_nie_dotykamy_nawet_ceny(monkeypatch):
    """Kandydat bez ani jednej pewnej absencji nie jest obserwacja team-news."""
    monkeypatch.setattr(dp, "_goal_shares_for", lambda *a, **kw: {})
    k = _kandydat(_absencje_pewne_nazwiska_home=[], _absencje_pewne_nazwiska_away=[])
    dp._policz_edge_absencji([k])
    assert "rynek_p_over" not in k


def test_brak_kursow_daje_None_a_nie_wyjatek(monkeypatch):
    """Brak pary kursow to brak pomiaru, nie zero."""
    monkeypatch.setattr(dp, "_goal_shares_for", lambda *a, **kw: {})
    k = _kandydat()
    k.pop("market_p_over")
    dp._policz_edge_absencji([k])
    assert k["rynek_p_over"] is None
