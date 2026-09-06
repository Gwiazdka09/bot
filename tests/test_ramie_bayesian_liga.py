"""Testy filtra ligi w ramieniu bayesian.

Kluczowa wlasnosc: przy filtrze ligi rating druzyny NIE MOZE zalezec od meczow
rozgrywanych w innych ligach. Bez tego testu mierzylbym cos, co tylko wyglada
na przefiltrowane.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ramie_bayesian import ratingi_bayes  # noqa: E402
from ramie_bayesian_liga import MIN_MECZOW_LIGA, ratingi_bayes_ligowe  # noqa: E402
from ramie_bayesian_naprawa import lambdy_bayes_naprawione  # noqa: E402


def _dwie_ligi(n: int = 120, ziarno: int = 5) -> pd.DataFrame:
    """Dwie rozlaczne ligi o WYRAZNIE roznej golowosci.

    L1 strzela duzo, L2 malo. Druzyna z L1 liczona wobec sredniej z obu lig
    wyjdzie sztucznie mocna, a wobec wlasnej ligi — przecietna. Na tym polega
    cala roznica miedzy ramionami.
    """
    rng = np.random.default_rng(ziarno)
    l1 = ["A1", "B1", "C1", "D1", "E1", "F1"]
    l2 = ["A2", "B2", "C2", "D2", "E2", "F2"]
    w = []
    for i in range(n):
        for liga, druzyny, lam_g, lam_a in (("L1", l1, 2.6, 2.1), ("L2", l2, 0.9, 0.7)):
            g, a = rng.choice(len(druzyny), size=2, replace=False)
            w.append({"date": pd.Timestamp("2021-01-01") + pd.Timedelta(days=int(i)),
                      "league": liga, "home": druzyny[g], "away": druzyny[a],
                      "hg": float(rng.poisson(lam_g)), "ag": float(rng.poisson(lam_a))})
    return pd.DataFrame(w).sort_values("date", kind="stable").reset_index(drop=True)


def test_rating_ligowy_nie_zalezy_od_drugiej_ligi():
    """Serce tej zmiany. Mecze L2 nie moga ruszac ratingow z L1."""
    df = _dwie_ligi()
    r1, _ = ratingi_bayes_ligowe(df)
    inny = df.copy()
    obca = inny["league"] == "L2"
    inny.loc[obca, "hg"] = 9.0
    inny.loc[obca, "ag"] = 9.0
    r2, _ = ratingi_bayes_ligowe(inny)

    w_l1 = (df["league"] == "L1").to_numpy()
    for k in ("liga_dom", "liga_wyj", "att_dom", "def_dom", "att_wyj", "def_wyj"):
        a, b = r1[k][w_l1], r2[k][w_l1]
        maska = np.isfinite(a) & np.isfinite(b)
        assert np.allclose(a[maska], b[maska]), f"{k} przeciekl z drugiej ligi"


def test_wersja_globalna_JEDNAK_zalezy_od_drugiej_ligi():
    """Kontrola — inaczej poprzedni test przeszedlby tez dla kodu bez filtra."""
    df = _dwie_ligi()
    r1 = ratingi_bayes(df)
    inny = df.copy()
    obca = inny["league"] == "L2"
    inny.loc[obca, "hg"] = 9.0
    r2 = ratingi_bayes(inny)
    w_l1 = (df["league"] == "L1").to_numpy()
    a, b = r1["liga_dom"][w_l1], r2["liga_dom"][w_l1]
    maska = np.isfinite(a) & np.isfinite(b)
    assert not np.allclose(a[maska], b[maska])


def test_srednie_ligowe_odpowiadaja_wlasnej_lidze():
    df = _dwie_ligi()
    r, _ = ratingi_bayes_ligowe(df)
    for liga, oczek_g in (("L1", 2.6), ("L2", 0.9)):
        m = (df["league"] == liga).to_numpy()
        ogon = np.flatnonzero(m)[-50:]
        assert r["liga_dom"][ogon].mean() == pytest.approx(oczek_g, abs=0.35), liga


def test_prog_ligowy_odrzuca_poczatek_historii():
    df = _dwie_ligi()
    _, dosc = ratingi_bayes_ligowe(df)
    assert not dosc[:8].any(), "pierwsze mecze nie moga miec ratingu"
    assert dosc[-50:].mean() > 0.9, "pod koniec historii prog ma przepuszczac"
    assert MIN_MECZOW_LIGA == 4


def test_filtr_ligi_zwieksza_rozrzut_lambd():
    """Rating wobec wlasnej ligi ma ROZROZNIAC druzyny, nie sciagac do sredniej.

    Wersja globalna miesza dwie ligi o roznej golowosci, wiec lambda odjezdzaja
    od realiow obu. To jest ta sama diagnoza, ktora `form.sily_ligowe` opisuje
    po stronie ramienia classic.
    """
    df = _dwie_ligi()
    lg_g, _ = lambdy_bayes_naprawione(ratingi_bayes(df))
    r_l, dosc = ratingi_bayes_ligowe(df)
    lg_l, _ = lambdy_bayes_naprawione(r_l)
    m = dosc & np.isfinite(lg_g) & np.isfinite(lg_l)
    w_l1 = m & (df["league"] == "L1").to_numpy()
    w_l2 = m & (df["league"] == "L2").to_numpy()
    # Wersja ligowa musi trafiac w golowosc KAZDEJ ligi z osobna.
    assert abs(lg_l[w_l1].mean() - df["hg"].to_numpy()[w_l1].mean()) < \
        abs(lg_g[w_l1].mean() - df["hg"].to_numpy()[w_l1].mean())
    assert abs(lg_l[w_l2].mean() - df["hg"].to_numpy()[w_l2].mean()) < \
        abs(lg_g[w_l2].mean() - df["hg"].to_numpy()[w_l2].mean())


def test_ratingi_ligowe_nie_widza_przyszlosci():
    df = _dwie_ligi()
    i = 150
    r1, _ = ratingi_bayes_ligowe(df)
    zepsuty = df.copy()
    zepsuty.loc[i:, "hg"] = 8.0
    r2, _ = ratingi_bayes_ligowe(zepsuty)
    for k in ("liga_dom", "att_dom", "def_wyj"):
        if np.isfinite(r1[k][i]) and np.isfinite(r2[k][i]):
            assert r1[k][i] == pytest.approx(r2[k][i]), f"{k} zobaczyl przyszlosc"
