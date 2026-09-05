"""Korekta tau Dixona-Colesa w glownej sciezce `poisson._macierz`.

Wdrozone 2026-09-05 na podstawie `scripts/ksztalt_dc.py` (pre-rejestracja
4e0591ab1). Do tego dnia glowna sciezka liczyla czysty iloczyn zewnetrzny —
`rho` w tym pliku nie wystepowalo w ogole.
"""
from __future__ import annotations

import numpy as np
import pytest
from scipy.stats import poisson as _p

from footstats.config import DC_RHO_CLASSIC, MAX_GOLE
from footstats.core.poisson import _macierz

N = MAX_GOLE + 1
PARY = ((1.5, 1.1), (2.4, 0.7), (0.6, 2.2), (3.0, 2.5))


def _jawna(lg: float, la: float, rho: float) -> np.ndarray:
    h = np.arange(N)
    m = np.outer(_p.pmf(h, lg), _p.pmf(h, la))
    for (i, j), t in (((0, 0), 1 - lg * la * rho), ((0, 1), 1 + lg * rho),
                      ((1, 0), 1 + la * rho), ((1, 1), 1 - rho)):
        m[i, j] *= max(0.0, t)
    return m / m.sum()


@pytest.mark.parametrize("para", PARY)
def test_rho_zero_to_dokladnie_stare_zachowanie(para):
    """Escape-hatch `DC_RHO_CLASSIC=0` ma wracac do czystego Poissona."""
    pw, pr, pp, _, over, *_ = _macierz(para[0], para[1], N, 0.0)
    m = _jawna(para[0], para[1], 0.0)
    h = np.arange(N)
    assert pw == pytest.approx(float(np.tril(m, -1).sum()), abs=2e-4)
    assert pr == pytest.approx(float(np.trace(m)), abs=2e-4)
    assert pp == pytest.approx(float(np.triu(m, 1).sum()), abs=2e-4)
    assert over == pytest.approx(
        float(m[(h[:, None] + h[None, :]) > 2.5].sum()), abs=2e-4)


@pytest.mark.parametrize("para", PARY)
@pytest.mark.parametrize("rho", [-0.13, -0.04, 0.06])
def test_tau_zgodne_z_macierza_jawna(para, rho):
    pw, pr, pp, _, over, *_ = _macierz(para[0], para[1], N, rho)
    m = _jawna(para[0], para[1], rho)
    h = np.arange(N)
    assert pw == pytest.approx(float(np.tril(m, -1).sum()), abs=2e-4)
    assert pr == pytest.approx(float(np.trace(m)), abs=2e-4)
    assert pp == pytest.approx(float(np.triu(m, 1).sum()), abs=2e-4)
    assert over == pytest.approx(
        float(m[(h[:, None] + h[None, :]) > 2.5].sum()), abs=2e-4)


@pytest.mark.parametrize("para", PARY)
def test_ujemne_rho_podnosi_remis_kosztem_wygranych(para):
    _, pr0, _, *_ = _macierz(para[0], para[1], N, 0.0)
    pw1, pr1, pp1, *_ = _macierz(para[0], para[1], N, -0.04)
    pw0, _, pp0, *_ = _macierz(para[0], para[1], N, 0.0)
    assert pr1 > pr0, "remis ma rosnac"
    assert pw1 < pw0 and pp1 < pp0, "obie wygrane maja malec"


@pytest.mark.parametrize("para", PARY)
def test_tau_nie_rusza_over25_ani_btts(para):
    """Poprawki tau sumuja sie tozsamosciowo do zera i wszystkie cztery komorki
    maja sume goli <= 2, wiec licznik Over 2.5 jest nietkniety, a mianownik
    nie drgnie. BTTS liczy sie z brzegowych pmf, wiec tez nie zalezy od tau."""
    _, _, _, bt0, ov0, *_ = _macierz(para[0], para[1], N, 0.0)
    _, _, _, bt1, ov1, *_ = _macierz(para[0], para[1], N, -0.13)
    assert ov1 == pytest.approx(ov0, abs=1e-12)
    assert bt1 == pytest.approx(bt0, abs=1e-12)


def test_rho_jest_czescia_klucza_cache():
    """`_macierz` jest lru_cache — rho poza kluczem dawaloby ciche zatrucie."""
    a = _macierz(1.5, 1.1, N, 0.0)
    b = _macierz(1.5, 1.1, N, -0.13)
    assert a[1] != b[1]
    assert _macierz(1.5, 1.1, N, 0.0)[1] == pytest.approx(a[1])


def test_prawdopodobienstwa_sumuja_sie_do_jedynki():
    for rho in (-0.30, -0.04, 0.0, 0.30):
        for para in PARY:
            pw, pr, pp, *_ = _macierz(para[0], para[1], N, rho)
            assert pw + pr + pp == pytest.approx(1.0, abs=1e-9)


def test_domyslne_rho_jest_dopasowane_a_nie_zerowe():
    """Wartosc z pomiaru; gdyby ktos ja zmienil, ma to zrobic swiadomie."""
    assert DC_RHO_CLASSIC == pytest.approx(-0.04)


def test_predict_match_realnie_podnosi_remis(monkeypatch):
    """Sciezka end-to-end, nie sama macierz."""
    import pandas as pd

    from footstats.core import poisson as mod

    rng = np.random.default_rng(5)
    druzyny = ["A", "B", "C", "D", "E", "F"]
    wiersze = []
    for i in range(120):
        g, a = rng.choice(len(druzyny), size=2, replace=False)
        wiersze.append({"data": f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}",
                        "league": "T", "gospodarz": druzyny[g], "goscie": druzyny[a],
                        "gole_g": float(rng.poisson(1.5)), "gole_a": float(rng.poisson(1.1))})
    df = pd.DataFrame(wiersze)

    monkeypatch.setattr(mod, "DC_RHO_CLASSIC", 0.0)
    bez = mod.predict_match("A", "B", df, use_xg=False, use_calibration=False)
    monkeypatch.setattr(mod, "DC_RHO_CLASSIC", -0.04)
    ze = mod.predict_match("A", "B", df, use_xg=False, use_calibration=False)

    assert bez is not None and ze is not None
    assert ze["p_remis"] > bez["p_remis"]
    assert ze["lambda_g"] == pytest.approx(bez["lambda_g"]), "tau nie rusza lambdy"
