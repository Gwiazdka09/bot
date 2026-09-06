"""Testy `scripts/ramie_bayesian.py` — parytet z `poisson_bayesian`.

Mierzymy ramie, ktore gra na produkcji, RAZEM z jego wadami (brak filtra ligi,
brak okna, obciecie na 8 komorkach, prior po niewlasciwej stronie). Bez testu
parytetu mierzylbym wlasna, poprawiona wersje — czyli nie to, co jest.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ramie_bayesian import (  # noqa: E402
    MAX_GOLI_BAYES, blenduj, lambdy_bayes, p1x2_bayes, ratingi_bayes, wagi_bayes,
)
from ramie_bayesian_naprawa import lambdy_bayes_naprawione  # noqa: E402

# Od 06.09.2026 produkcja liczy lambda WERSJA NAPRAWIONA — parytet celuje w nia.
# `lambdy_bayes` zostaje jako zapis stanu sprzed naprawy, uzywany przez
# `ramie_bayesian_naprawa.py` do porownania obu ramion.
lambdy_prod = lambdy_bayes_naprawione

DRUZYNY = ("Alfa", "Beta", "Gamma", "Delta", "Epsilon", "Zeta")


def _dane(n: int = 100, ziarno: int = 13) -> pd.DataFrame:
    rng = np.random.default_rng(ziarno)
    w = []
    for i in range(n):
        g, a = rng.choice(len(DRUZYNY), size=2, replace=False)
        w.append({"date": pd.Timestamp("2021-01-01") + pd.Timedelta(days=int(i)),
                  "league": "L1" if i % 2 else "L2",
                  "home": DRUZYNY[g], "away": DRUZYNY[a],
                  "hg": float(rng.poisson(1.6)), "ag": float(rng.poisson(1.2))})
    return pd.DataFrame(w).sort_values("date", kind="stable").reset_index(drop=True)


def _prod(hist: pd.DataFrame, g: str, a: str):
    from footstats.core.poisson_bayesian import predict_match_bayesian

    p = hist.rename(columns={"home": "gospodarz", "away": "goscie",
                             "hg": "gole_g", "ag": "gole_a"})
    return predict_match_bayesian(g, a, p)


def test_wagi_trzy_razy_dla_ostatnich_pieciu():
    w = wagi_bayes(10)
    assert list(w) == [1.0] * 5 + [3.0] * 5


def test_lambda_zgodna_z_predict_match_bayesian_na_ostatnim_meczu():
    df = _dane()
    r = ratingi_bayes(df)
    lg, la = lambdy_prod(r)
    i = len(df) - 1
    oczek = _prod(df.iloc[:i], df.at[i, "home"], df.at[i, "away"])
    assert oczek is not None
    assert lg[i] == pytest.approx(oczek["lambda_g"], abs=5e-4)
    assert la[i] == pytest.approx(oczek["lambda_a"], abs=5e-4)


def test_lambda_zgodna_na_wielu_meczach():
    """Jeden wiersz moze byc zbiegiem okolicznosci."""
    df = _dane()
    lg, la = lambdy_prod(ratingi_bayes(df))
    sprawdzone = 0
    for i in range(40, len(df)):
        oczek = _prod(df.iloc[:i], df.at[i, "home"], df.at[i, "away"])
        if oczek is None:
            continue
        assert lg[i] == pytest.approx(oczek["lambda_g"], abs=5e-4), f"wiersz {i}"
        assert la[i] == pytest.approx(oczek["lambda_a"], abs=5e-4), f"wiersz {i}"
        sprawdzone += 1
    assert sprawdzone >= 30


def test_1x2_zgodne_z_predict_match_bayesian():
    df = _dane()
    lg, la = lambdy_prod(ratingi_bayes(df))
    i = len(df) - 1
    oczek = _prod(df.iloc[:i], df.at[i, "home"], df.at[i, "away"])
    p = p1x2_bayes(np.array([lg[i]]), np.array([la[i]]))[0]
    assert p[0] == pytest.approx(oczek["pw"], abs=1e-3)
    assert p[1] == pytest.approx(oczek["pr"], abs=1e-3)
    assert p[2] == pytest.approx(oczek["pa"], abs=1e-3)


def test_ratingi_nie_widza_przyszlosci():
    df = _dane()
    i = 60
    lg1, la1 = lambdy_prod(ratingi_bayes(df))
    zepsuty = df.copy()
    zepsuty.loc[i:, "hg"] = 8.0
    zepsuty.loc[i:, "ag"] = 8.0
    lg2, la2 = lambdy_prod(ratingi_bayes(zepsuty))
    assert lg1[i] == pytest.approx(lg2[i])
    assert la1[i] == pytest.approx(la2[i])


def test_zmiana_przeszlosci_jednak_rusza():
    df = _dane()
    i = 60
    lg1, _ = lambdy_prod(ratingi_bayes(df))
    zmieniony = df.copy()
    zmieniony.loc[: i - 1, "hg"] = 6.0
    lg2, _ = lambdy_prod(ratingi_bayes(zmieniony))
    assert lg1[i] != pytest.approx(lg2[i])


def test_ramie_bayesian_ignoruje_lige():
    """Wada produkcyjna, ktora mierzymy — nie naprawiamy jej tutaj.

    Ta sama para, te same jej mecze, ale INNE mecze reszty swiata musza zmienic
    jej lambda — bo `_league_averages` liczy srednia z calej ramki.
    """
    df = _dane()
    i = len(df) - 1
    lg1, _ = lambdy_prod(ratingi_bayes(df))
    inny_swiat = df.copy()
    obce = (inny_swiat["home"] != df.at[i, "home"]) & (inny_swiat["away"] != df.at[i, "home"]) \
        & (inny_swiat["home"] != df.at[i, "away"]) & (inny_swiat["away"] != df.at[i, "away"])
    inny_swiat.loc[obce, "hg"] = 5.0
    lg2, _ = lambdy_prod(ratingi_bayes(inny_swiat))
    assert lg1[i] != pytest.approx(lg2[i]), \
        "lambda pary zalezy od meczow zupelnie obcych druzyn — to jest ta wada"


def test_macierz_bayesian_obcina_na_osmiu_komorkach():
    """Rozjazd z glowna sciezka, ktora liczy MAX_GOLE + 1 = 9."""
    from footstats.config import MAX_GOLE

    assert MAX_GOLI_BAYES == MAX_GOLE
    p9 = p1x2_bayes(np.array([3.0]), np.array([2.5]))
    from footstats.core.poisson import _macierz
    pw9 = _macierz(3.0, 2.5, MAX_GOLE + 1, 0.0)[0]
    assert abs(p9[0, 0] - pw9) > 1e-3, "rozjazd 8 vs 9 zniknal — zaktualizuj test"


def test_blend_odpowiada_blend_dixon_coles():
    from footstats.core.poisson_bayesian import blend_dixon_coles

    p_c = np.array([[0.50, 0.28, 0.22]])
    p_b = np.array([[0.40, 0.30, 0.30]])
    moje = blenduj(p_c, p_b, 0.5)[0]

    class _Atrapa:
        pass

    # `blend_dixon_coles` wola `predict_match_bayesian`; podmieniamy je w ZRODLE,
    # bo import jest lokalny wewnatrz funkcji.
    import footstats.core.poisson_bayesian as pb
    stare = pb.predict_match_bayesian
    pb.predict_match_bayesian = lambda g, a, df: {
        "pw": p_b[0, 0], "pr": p_b[0, 1], "pa": p_b[0, 2]}
    try:
        out = blend_dixon_coles(
            {"pw": p_c[0, 0] * 100, "pr": p_c[0, 1] * 100, "pp": p_c[0, 2] * 100},
            "A", "B", _Atrapa(), w_bayesian=0.5)
    finally:
        pb.predict_match_bayesian = stare
    assert moje == pytest.approx([out["pw"] / 100, out["pr"] / 100, out["pp"] / 100],
                                 abs=1e-6)


def test_blend_skrajne_wagi():
    p_c = np.array([[0.5, 0.3, 0.2]])
    p_b = np.array([[0.1, 0.2, 0.7]])
    assert blenduj(p_c, p_b, 0.0)[0] == pytest.approx(p_c[0])
    assert blenduj(p_c, p_b, 1.0)[0] == pytest.approx(p_b[0])
    assert blenduj(p_c, p_b, 0.5)[0].sum() == pytest.approx(1.0)


def test_waga_ramienia_obnizona_swiadomie():
    """Wartosc z pomiaru 06.09 — gdyby ktos ja zmienil, ma to zrobic swiadomie.

    0.5 dawalo Brier 1X2 0.63344 na holdoucie, 0.13 daje 0.61991 (+0.01352,
    z=+19.14, 37 lig na 38). Po zmieszaniu z cena przy wadze rynku 0.70 zysk
    +0.00134 (z=+5.53) — jedyna zmiana tej serii, ktora realnie widac.
    """
    from footstats.config import W_BAYESIAN

    assert W_BAYESIAN == pytest.approx(0.49)


def test_lambda_ramienia_jest_juz_zdrowa():
    """Po naprawie pieciu stalych (06.09.2026) lambda ma byc realistyczna.

    Przed naprawa bylo 2.1585 / 0.9515 przy faktycznych 1.5087 / 1.2146 —
    priory i mianowniki po zlej stronie boiska plus podwojny BONUS_DOMOWY.
    """
    df = _dane(n=300, ziarno=21)
    r = ratingi_bayes(df)
    lg, la = lambdy_prod(r)
    ogon = slice(150, None)
    fakt_g = df["hg"].to_numpy()[ogon].mean()
    fakt_a = df["ag"].to_numpy()[ogon].mean()
    assert abs(lg[ogon].mean() - fakt_g) < 0.15, "lambda gospodarza odjezdza"
    assert abs(la[ogon].mean() - fakt_a) < 0.15, "lambda goscia odjezdza"

    # Kontrola: stara arytmetyka byla wyraznie gorsza na tych samych danych.
    lg_z, la_z = lambdy_bayes(r)
    assert abs(lg_z[ogon].mean() - fakt_g) > abs(lg[ogon].mean() - fakt_g)
