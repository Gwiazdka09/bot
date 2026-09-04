"""Testy `scripts/estymator_lambda.py` — głównie PARYTET z produkcją.

Ten skrypt liczy ratingi własną, wektorową implementacją, bo `form.sily_ligowe`
wołana per mecz przy 140 tys. meczów razy 35 kombinacji siatki jest nie do
przejścia. Cena za to jest taka, że bez testu zgodności stroiłbym estymator,
którego na produkcji nie ma. Stąd tutaj: te same liczby, dwie drogi.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from estymator_lambda import (  # noqa: E402
    KLUCZE, MIN_MECZOW_LIGOWYCH, brier_1x2, lambdy, liczniki_druzyn,
    maska_uzywalnych, ratingi_ligi, wagi_okna, _srednie_kroczace,
)

DRUZYNY = ("Alfa", "Beta", "Gamma", "Delta", "Epsilon", "Zeta")


def _liga(n: int = 90, ziarno: int = 7, ze_strzalami: bool = False) -> pd.DataFrame:
    """Sztuczna liga z rozłącznymi datami — po jednym meczu dziennie.

    Rozłączne daty są tu istotne: przy remisie dat „ściśle wcześniejsze" i
    „wszystkie poprzednie wiersze" to dwa różne zbiory, a test parytetu ma
    mierzyć arytmetykę ratingów, nie tę różnicę.
    """
    rng = np.random.default_rng(ziarno)
    wiersze = []
    for i in range(n):
        g, a = rng.choice(len(DRUZYNY), size=2, replace=False)
        w = {
            "date": pd.Timestamp("2020-01-01") + pd.Timedelta(days=i),
            "league": "TEST-Liga",
            "home": DRUZYNY[g], "away": DRUZYNY[a],
            "hg": float(rng.poisson(1.5)), "ag": float(rng.poisson(1.1)),
        }
        if ze_strzalami:
            w["hst"] = float(rng.poisson(5.0))
            w["ast"] = float(rng.poisson(4.0))
        wiersze.append(w)
    df = pd.DataFrame(wiersze)
    return df.sort_values("date", kind="stable").reset_index(drop=True)


def _prod_tabela(hist: pd.DataFrame, okno: int, waga_strzalow: float):
    """`form.sily_ligowe` na historii, w nazewnictwie produkcyjnym."""
    from footstats.core.form import sily_ligowe

    p = hist.rename(columns={"home": "gospodarz", "away": "goscie",
                             "hg": "gole_g", "ag": "gole_a"})
    return sily_ligowe(p, okno=okno, waga_strzalow=waga_strzalow, waga_xg=0.0)


# ─────────────────────────────  wagi i okno  ─────────────────────────────────

def test_wagi_plaskie_gdy_polowicz_nieskonczony():
    assert np.allclose(wagi_okna(30, np.inf), np.ones(30))


def test_wagi_zanikaja_wstecz_a_najswiezszy_ma_jeden():
    w = wagi_okna(4, 2.0)
    assert w[-1] == pytest.approx(1.0)
    assert w == pytest.approx([0.5 ** 1.5, 0.5, 0.5 ** 0.5, 1.0])


def test_srednia_kroczaca_bierze_tylko_wpisy_przed_pozycja():
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    sr, n = _srednie_kroczace(x, np.array([0, 1, 2, 5]), 2, wagi_okna(2, np.inf))
    assert np.isnan(sr[0]) and n[0] == 0
    assert sr[1] == pytest.approx(1.0) and n[1] == 1
    assert sr[2] == pytest.approx(1.5) and n[2] == 2
    # Okno 2 przy pięciu dostępnych wpisach bierze DWA ostatnie, nie wszystkie.
    assert sr[3] == pytest.approx(4.5) and n[3] == 2


def test_srednia_kroczaca_wazona_faworyzuje_swiezsze():
    x = np.array([0.0, 10.0])
    sr, _ = _srednie_kroczace(x, np.array([2]), 2, wagi_okna(2, 1.0))
    # wagi [0.5, 1.0] -> (0*0.5 + 10*1)/1.5
    assert sr[0] == pytest.approx(10.0 / 1.5)


# ─────────────────────────────  parytet z produkcją  ─────────────────────────

@pytest.mark.parametrize("okno", [10, 30])
def test_ratingi_zgodne_z_sily_ligowe_na_ostatnim_meczu(okno):
    df = _liga()
    r = ratingi_ligi(df, okno, np.inf)
    assert r is not None
    i = len(df) - 1
    prod = _prod_tabela(df.iloc[:i], okno, waga_strzalow=0.0)
    assert prod is not None
    tabela, sr_dom, sr_wyj = prod
    g, a = df.at[i, "home"], df.at[i, "away"]
    assert g in tabela and a in tabela, "drużyny testowe muszą przejść próg produkcji"

    assert r["sr_dom"][i] == pytest.approx(sr_dom)
    assert r["sr_wyj"][i] == pytest.approx(sr_wyj)
    assert r["atak_dom"][i] == pytest.approx(tabela[g]["atak_dom"])
    assert r["obrona_dom"][i] == pytest.approx(tabela[g]["obrona_dom"])
    assert r["atak_wyj"][i] == pytest.approx(tabela[a]["atak_wyj"])
    assert r["obrona_wyj"][i] == pytest.approx(tabela[a]["obrona_wyj"])


def test_ratingi_zgodne_z_produkcja_takze_z_domieszka_strzalow():
    df = _liga(ze_strzalami=True)
    r = ratingi_ligi(df, 30, np.inf)
    i = len(df) - 1
    tabela, _, _ = _prod_tabela(df.iloc[:i], 30, waga_strzalow=0.7)
    g, a = df.at[i, "home"], df.at[i, "away"]
    assert r["atak_dom"][i] == pytest.approx(tabela[g]["atak_dom"])
    assert r["obrona_wyj"][i] == pytest.approx(tabela[a]["obrona_wyj"])


def test_domieszka_strzalow_realnie_zmienia_rating():
    """Bez tego poprzedni test przechodziłby też, gdyby domieszka nie działała."""
    df = _liga(ze_strzalami=True)
    bez = ratingi_ligi(df.drop(columns=["hst", "ast"]), 30, np.inf)
    ze = ratingi_ligi(df, 30, np.inf)
    i = len(df) - 1
    assert ze["atak_dom"][i] != pytest.approx(bez["atak_dom"][i])


def test_ratingi_zgodne_z_produkcja_na_wielu_meczach():
    """Parytet na jednym wierszu może być zbiegiem okoliczności."""
    df = _liga()
    r = ratingi_ligi(df, 30, np.inf)
    sprawdzone = 0
    for i in range(60, len(df)):
        prod = _prod_tabela(df.iloc[:i], 30, waga_strzalow=0.0)
        tabela = prod[0]
        g, a = df.at[i, "home"], df.at[i, "away"]
        if g not in tabela or a not in tabela:
            continue
        assert r["atak_dom"][i] == pytest.approx(tabela[g]["atak_dom"])
        assert r["obrona_wyj"][i] == pytest.approx(tabela[a]["obrona_wyj"])
        sprawdzone += 1
    assert sprawdzone >= 20


# ─────────────────────────────  brak lookaheadu  ─────────────────────────────

def test_rating_nie_widzi_przyszlosci():
    df = _liga()
    i = 50
    r1 = ratingi_ligi(df, 30, np.inf)
    zepsuty = df.copy()
    zepsuty.loc[i:, "hg"] = 9.0     # katastrofa PO tym meczu włącznie
    zepsuty.loc[i:, "ag"] = 9.0
    r2 = ratingi_ligi(zepsuty, 30, np.inf)
    for k in ("atak_dom", "obrona_dom", "atak_wyj", "obrona_wyj", "sr_dom", "sr_wyj"):
        assert r1[k][i] == pytest.approx(r2[k][i]), f"{k} zobaczyło przyszłość"


def test_zmiana_przeszlosci_rating_jednak_rusza():
    """Kontrola do poprzedniego — inaczej przeszedłby też rating stały."""
    df = _liga()
    i = 50
    r1 = ratingi_ligi(df, 30, np.inf)
    zmieniony = df.copy()
    zmieniony.loc[: i - 1, "hg"] = 7.0
    r2 = ratingi_ligi(zmieniony, 30, np.inf)
    assert r1["sr_dom"][i] != pytest.approx(r2["sr_dom"][i])


# ─────────────────────────────  liczniki i maska  ────────────────────────────

def test_liczniki_licza_mecze_scisle_wczesniejsze():
    df = pd.DataFrame({
        "date": pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"]),
        "home": ["A", "A", "B"], "away": ["B", "C", "A"],
        "hg": [1.0, 1.0, 1.0], "ag": [0.0, 0.0, 0.0],
    })
    lic = liczniki_druzyn(df)
    # wiersz 0 — pierwszy mecz w ogóle, obie drużyny bez historii
    assert (lic["n_dom_g"][0], lic["n_wyj_g"][0]) == (0, 0)
    assert (lic["n_dom_a"][0], lic["n_wyj_a"][0]) == (0, 0)
    # wiersz 1 — A u siebie po raz drugi, C bez historii
    assert (lic["n_dom_g"][1], lic["n_wyj_g"][1]) == (1, 0)
    assert (lic["n_dom_a"][1], lic["n_wyj_a"][1]) == (0, 0)
    # wiersz 2 — gospodarzem B (1 wyjazd, 0 u siebie), gościem A (2x u siebie)
    assert (lic["n_dom_g"][2], lic["n_wyj_g"][2]) == (0, 1)
    assert (lic["n_dom_a"][2], lic["n_wyj_a"][2]) == (2, 0)


def test_maska_stosuje_prog_LACZNY_a_nie_stronny():
    """Produkcja przepuszcza przy dom+wyj >= 6; próg na każdą stronę z osobna
    wyciąłby beniaminków i początek sezonu — czyli to, na czym estymator
    najczęściej się wykłada."""
    d = {k: np.array([1.0]) for k in KLUCZE}
    d.update({"hg": np.array([1.0]), "ag": np.array([1.0])})
    d["n_dom_g"], d["n_wyj_g"] = np.array([1.0]), np.array([5.0])
    d["n_dom_a"], d["n_wyj_a"] = np.array([5.0]), np.array([1.0])
    assert bool(maska_uzywalnych(d)[0]) is True

    d["n_wyj_g"] = np.array([4.0])   # razem 5 < 6
    assert bool(maska_uzywalnych(d)[0]) is False
    assert MIN_MECZOW_LIGOWYCH == 6


def test_druzyna_bez_meczow_na_stronie_dostaje_rating_jeden():
    """Parytet z `if len(dom) else 1.0` w `form._tabela_ratingow`."""
    df = _liga()
    # Nowa drużyna wchodzi jako gość na końcu — u siebie nie grała nigdy.
    nowy = df.iloc[[-1]].copy()
    nowy["date"] = df["date"].max() + pd.Timedelta(days=1)
    nowy["away"] = "Omega"
    df2 = pd.concat([df, nowy], ignore_index=True)
    r = ratingi_ligi(df2, 30, np.inf)
    assert r["atak_wyj"][-1] == pytest.approx(1.0)
    assert r["obrona_wyj"][-1] == pytest.approx(1.0)


# ─────────────────────────────  λ i metryki  ─────────────────────────────────

def test_lambda_bez_sciagania_to_czysty_iloczyn():
    r = {"atak_dom": np.array([1.2]), "obrona_wyj": np.array([0.9]),
         "atak_wyj": np.array([1.1]), "obrona_dom": np.array([0.8]),
         "sr_dom": np.array([1.5]), "sr_wyj": np.array([1.1]),
         "n_gosp": np.array([30.0]), "n_gosc": np.array([30.0])}
    lg, la = lambdy(r, 0.0, 1.0, 1.0)
    assert lg[0] == pytest.approx(1.2 * 0.9 * 1.5)
    assert la[0] == pytest.approx(1.1 * 0.8 * 1.1)


def test_skala_mnozy_lambde_wprost():
    r = {"atak_dom": np.array([1.0]), "obrona_wyj": np.array([1.0]),
         "atak_wyj": np.array([1.0]), "obrona_dom": np.array([1.0]),
         "sr_dom": np.array([1.5]), "sr_wyj": np.array([1.1]),
         "n_gosp": np.array([30.0]), "n_gosc": np.array([30.0])}
    lg, la = lambdy(r, 0.0, 0.94, 0.94)
    assert lg[0] == pytest.approx(1.5 * 0.94)
    assert la[0] == pytest.approx(1.1 * 0.94)


def test_sciaganie_przyciaga_rating_do_jedynki_tym_mocniej_im_mniej_meczow():
    r = {"atak_dom": np.array([2.0, 2.0]), "obrona_wyj": np.array([1.0, 1.0]),
         "atak_wyj": np.array([1.0, 1.0]), "obrona_dom": np.array([1.0, 1.0]),
         "sr_dom": np.array([1.0, 1.0]), "sr_wyj": np.array([1.0, 1.0]),
         "n_gosp": np.array([6.0, 30.0]), "n_gosc": np.array([6.0, 30.0])}
    lg, _ = lambdy(r, 6.0, 1.0, 1.0)
    assert lg[0] == pytest.approx(1.5)    # (6*2 + 6)/(6+6)
    assert lg[1] == pytest.approx((30 * 2 + 6) / 36)
    assert lg[0] < lg[1], "rating z krótszej próby ma być bliżej jedynki"


def test_brier_zgodny_z_macierza_produkcyjna():
    """Ta sama trójka 1X2 co `poisson._macierz` przy rho=0 (USE_DC_TAU=0)."""
    from footstats.core.poisson import _macierz
    from footstats.config import MAX_GOLE

    for lg, la in ((1.5, 1.1), (2.4, 0.7), (0.6, 2.2)):
        pw, pr, pp = _macierz(lg, la, MAX_GOLE)[:3]
        for idx, oczek in ((0, pw), (1, pr), (2, pp)):
            b = brier_1x2(np.array([lg]), np.array([la]), np.array([idx]))[0]
            # Brier przy trafionym wyniku = (p-1)^2 + suma kwadratów reszty.
            reszta = [x for j, x in enumerate((pw, pr, pp)) if j != idx]
            assert b == pytest.approx((oczek - 1.0) ** 2 + sum(x * x for x in reszta),
                                      abs=2e-4)


def test_brier_jest_mniejszy_gdy_prognoza_trafia():
    b_traf = brier_1x2(np.array([2.5]), np.array([0.5]), np.array([0]))[0]
    b_pudlo = brier_1x2(np.array([2.5]), np.array([0.5]), np.array([2]))[0]
    assert b_traf < b_pudlo
