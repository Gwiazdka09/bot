"""Testy naprawy pieciu stalych w ramieniu bayesian.

Naprawa jest bledem JEDNOSTEK, nie wyborem modelowym: kod dzielil gole
gospodarzy przez srednia goli gosci. Testy sprawdzaja to bez zadnych danych —
przez tozsamosc, ktora musi zachodzic z samej definicji.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ramie_bayesian import lambdy_bayes, ratingi_bayes  # noqa: E402
from ramie_bayesian_naprawa import lambdy_bayes_naprawione  # noqa: E402
from test_ramie_bayesian import _dane  # noqa: E402

LIG_DOM, LIG_WYJ = 1.4883, 1.1790


def _przecietna_druzyna(n: float = 30.0) -> dict:
    """Ratingi drozyny doskonale przecietnej: kazda wielkosc rowna swojej sredniej.

    `att_dom` to gole strzelone U SIEBIE  -> srednia goli gospodarzy
    `def_dom` to gole STRACONE u siebie   -> srednia goli gosci
    `att_wyj` to gole strzelone NA WYJEZDZIE -> srednia goli gosci
    `def_wyj` to gole STRACONE na wyjezdzie  -> srednia goli gospodarzy
    """
    j = np.ones(1)
    return {"liga_dom": j * LIG_DOM, "liga_wyj": j * LIG_WYJ,
            "att_dom": j * LIG_DOM, "def_dom": j * LIG_WYJ,
            "att_wyj": j * LIG_WYJ, "def_wyj": j * LIG_DOM,
            "n_dom": j * n, "n_wyj": j * n}


def test_przecietna_druzyna_dostaje_dokladnie_srednie_ligowe():
    """Tozsamosc, ktora musi zachodzic z definicji — i ktora byla zlamana."""
    lg, la = lambdy_bayes_naprawione(_przecietna_druzyna())
    assert lg[0] == pytest.approx(LIG_DOM, abs=1e-9)
    assert la[0] == pytest.approx(LIG_WYJ, abs=1e-9)


def test_przecietna_druzyna_zachowuje_tozsamosc_przy_KAZDEJ_liczbie_meczow():
    """Sciaganie do priora nie moze ruszac druzyny, ktora JEST przecietna."""
    for n in (0.0, 1.0, 6.0, 30.0, 300.0):
        lg, la = lambdy_bayes_naprawione(_przecietna_druzyna(n))
        assert lg[0] == pytest.approx(LIG_DOM, abs=1e-9), f"n={n}"
        assert la[0] == pytest.approx(LIG_WYJ, abs=1e-9), f"n={n}"


def test_stara_wersja_LAMIE_te_tozsamosc():
    """Kontrola: bez niej powyzsze przeszlyby tez dla kodu bez zmian."""
    lg, la = lambdy_bayes(_przecietna_druzyna())
    assert lg[0] > LIG_DOM * 1.3, "stara wersja ma zawyzac gospodarza"
    assert la[0] < LIG_WYJ * 0.9, "stara wersja ma zanizac goscia"


def test_naprawa_zbliza_srednie_lambda_do_faktycznych():
    df = _dane(n=300, ziarno=31)
    r = ratingi_bayes(df)
    lg_z, la_z = lambdy_bayes(r)
    lg_n, la_n = lambdy_bayes_naprawione(r)
    ogon = slice(150, None)
    fakt_g, fakt_a = df["hg"].to_numpy()[ogon].mean(), df["ag"].to_numpy()[ogon].mean()
    assert abs(lg_n[ogon].mean() - fakt_g) < abs(lg_z[ogon].mean() - fakt_g)
    assert abs(la_n[ogon].mean() - fakt_a) < abs(la_z[ogon].mean() - fakt_a)


def test_naprawa_nie_dotyka_atakow():
    """Zmieniamy wylacznie strony obrony i mianowniki — ataki zostaja."""
    r = _przecietna_druzyna()
    r["att_dom"] = np.array([2.0])       # napastnik ponad przecietna
    lg_n, _ = lambdy_bayes_naprawione(r)
    # att_dom sciagane do lig_dom, mianownik lig_dom, def_a = lig_dom -> iloraz 1
    oczek = (30 * 2.0 + 3 * LIG_DOM) / 33
    assert lg_n[0] == pytest.approx(oczek, abs=1e-9)


def test_naprawa_nie_wprowadza_lookaheadu():
    df = _dane(n=200, ziarno=41)
    i = 120
    lg1, _ = lambdy_bayes_naprawione(ratingi_bayes(df))
    zepsuty = df.copy()
    zepsuty.loc[i:, "hg"] = 7.0
    lg2, _ = lambdy_bayes_naprawione(ratingi_bayes(zepsuty))
    assert lg1[i] == pytest.approx(lg2[i])
