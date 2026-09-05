"""Testy `scripts/ksztalt_dc.py` — parytet z macierzami produkcyjnymi.

Skrypt liczy wyjscia korekty tau BEZ budowania macierzy 8x8 (przy 134 tys.
meczow razy siatka rho pelna macierz kosztowalaby gigabajty). Cena za skrot
jest taka, ze arytmetyka musi sie zgadzac z jawna macierza co do bitu — inaczej
mierzylbym inny rozklad niz ten, ktory bym potem wdrozyl.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from estymator_lambda import MAX_GOLI  # noqa: E402
from ksztalt_dc import dopasuj_rho, pmf_obciete, wyjscia_dc  # noqa: E402

PARY = ((1.5, 1.1), (2.4, 0.7), (0.6, 2.2), (1.0, 1.0))


def _wy(lg, la, rho, hg=None, ag=None):
    a, b = np.array([lg]), np.array([la])
    return wyjscia_dc(pmf_obciete(a), pmf_obciete(b), a, b, rho,
                      None if hg is None else np.array([hg]),
                      None if ag is None else np.array([ag]))


@pytest.mark.parametrize("para", PARY)
def test_rho_zero_zgodne_z_macierza_produkcyjna(para):
    """Przy rho=0 musimy dawac dokladnie to, co `poisson._macierz`."""
    from footstats.config import MAX_GOLE
    from footstats.core.poisson import _macierz

    pw, pr, pp, _, over, *_ = _macierz(para[0], para[1], MAX_GOLE + 1)
    w = _wy(*para, 0.0)
    assert w["p1x2"][0] == pytest.approx([pw, pr, pp], abs=2e-4)
    assert w["over25"][0] == pytest.approx(over, abs=2e-4)


def _macierz_jawna(lg: float, la: float, rho: float) -> np.ndarray:
    """Jawna macierz MAX_GOLI x MAX_GOLI z korekta tau — wzorzec dla skrotu.

    Ta sama arytmetyka co `poisson_bayesian.macierz_dixon_coles`, ale na
    MAX_GOLI komorkach. Nie wolam tamtej wprost, bo ona uzywa arange(MAX_GOLE)
    = 8 komorek, podczas gdy glowna sciezka wola _macierz(..., MAX_GOLE + 1)
    = 9. Dwie macierze produkcyjne obcinaja W INNYM MIEJSCU — patrz
    `test_dwie_macierze_produkcyjne_obcinaja_inaczej`.
    """
    h = np.arange(MAX_GOLI)
    from scipy.stats import poisson as _p
    pg, pa = _p.pmf(h, lg), _p.pmf(h, la)
    m = np.outer(pg, pa)
    for (i, j), t in (((0, 0), 1 - lg * la * rho), ((0, 1), 1 + lg * rho),
                      ((1, 0), 1 + la * rho), ((1, 1), 1 - rho)):
        m[i, j] *= max(0.0, t)
    return m / m.sum()


def test_dwie_macierze_produkcyjne_obcinaja_inaczej():
    """Udokumentowany rozjazd w repo, znaleziony 2026-09-05.

    `poisson.predict_match` wola `_macierz(lg, la, MAX_GOLE + 1)` = 9 komorek,
    a `poisson_bayesian.macierz_dixon_coles` liczy `arange(MAX_GOLE)` = 8.
    Roznica siega 2.6e-3 w p(1) przy wysokich lambdach — wiecej niz efekty
    mierzone przez `ksztalt_dc.py`. Ten test nie naprawia rozjazdu, tylko
    pilnuje, zeby nikt go po cichu nie przeoczyl po raz drugi.
    """
    from footstats.config import MAX_GOLE
    from footstats.core.poisson import _macierz
    from footstats.core.poisson_bayesian import macierz_dixon_coles

    assert MAX_GOLI == MAX_GOLE + 1, "harness ma liczyc tyle komorek co glowna sciezka"
    assert macierz_dixon_coles(1.5, 1.1, 0.0).shape[0] == MAX_GOLE
    pw_klas = _macierz(3.0, 2.5, MAX_GOLE + 1)[0]
    pw_bayes = float(np.tril(macierz_dixon_coles(3.0, 2.5, 0.0), -1).sum())
    assert abs(pw_klas - pw_bayes) > 1e-3, "rozjazd zniknal — zaktualizuj ten test"


@pytest.mark.parametrize("para", PARY)
@pytest.mark.parametrize("rho", [-0.13, -0.05, 0.07])
def test_tau_zgodne_z_macierza_jawna(para, rho):
    """Skrot bez macierzy musi dawac to samo, co macierz zbudowana wprost."""
    m = _macierz_jawna(para[0], para[1], rho)
    h = np.arange(m.shape[0])
    oczek_pw = float(np.tril(m, -1).sum())
    oczek_pr = float(np.trace(m))
    oczek_over = float(m[(h[:, None] + h[None, :]) > 2.5].sum())

    w = _wy(*para, rho)
    assert w["p1x2"][0, 0] == pytest.approx(oczek_pw, abs=1e-9)
    assert w["p1x2"][0, 1] == pytest.approx(oczek_pr, abs=1e-9)
    assert w["over25"][0] == pytest.approx(oczek_over, abs=1e-9)


@pytest.mark.parametrize("wynik", [(0, 0), (1, 0), (0, 1), (1, 1), (2, 1), (3, 3)])
def test_prawdopodobienstwo_wyniku_zgodne_z_macierza(wynik):
    """`p_wynik` to komorka macierzy — wlacznie z czterema, ktore tau rusza."""
    m = _macierz_jawna(1.6, 1.2, -0.11)
    w = _wy(1.6, 1.2, -0.11, wynik[0], wynik[1])
    assert w["p_wynik"][0] == pytest.approx(float(m[wynik]), abs=1e-9)


def test_ujemne_rho_podnosi_remisy():
    """Kierunek dzialania tau — bez tego test parytetu przeszedlby tez dla tau=1."""
    bez = _wy(1.5, 1.2, 0.0)
    z_tau = _wy(1.5, 1.2, -0.13)
    assert z_tau["p1x2"][0, 1] > bez["p1x2"][0, 1], "remis ma rosnac"
    assert z_tau["p1x2"][0, 0] < bez["p1x2"][0, 0], "wygrana gospodarza ma malec"


@pytest.mark.parametrize("para", PARY)
@pytest.mark.parametrize("rho", [-0.3, -0.13, 0.2])
def test_tau_NIE_rusza_over25(para, rho):
    """Wlasnosc konstrukcyjna tau, znaleziona 2026-09-05 przy pisaniu testow.

    Poprawki czterech komorek sumuja sie TOZSAMOSCIOWO do zera:
        d(0,0) = -K*l*m*rho   d(0,1) = +K*l*m*rho
        d(1,0) = +K*l*m*rho   d(1,1) = -K*l*m*rho
    Wszystkie cztery maja sume goli <= 2, wiec licznik Over 2.5 jest nietkniety,
    a mianownik nie drgnie. Wniosek, ktory to niesie: niedoboru 7.8 pp na Over
    2.5 NIE DA SIE naprawic korekta tau. Pierwsza wersja pre-rejestracji
    zakladala cos przeciwnego.
    """
    assert _wy(*para, rho)["over25"][0] == pytest.approx(
        _wy(*para, 0.0)["over25"][0], abs=1e-12)


def test_prawdopodobienstwa_sumuja_sie_do_jedynki():
    for rho in (-0.3, -0.13, 0.0, 0.3):
        for para in PARY:
            assert _wy(*para, rho)["p1x2"][0].sum() == pytest.approx(1.0)


def test_dopasowanie_rho_odnajduje_rho_uzyte_do_generowania():
    """Round-trip: generujemy wyniki z rho=-0.12, dopasowanie ma je odnalezc."""
    rng = np.random.default_rng(3)
    n = 40000
    lg = rng.uniform(0.9, 2.1, n)
    la = rng.uniform(0.7, 1.8, n)
    pg, pa = pmf_obciete(lg), pmf_obciete(la)
    prawdziwe = -0.12
    # Losujemy wyniki z pelnej macierzy przy prawdziwym rho.
    h = np.arange(pg.shape[1])
    hg = np.empty(n)
    ag = np.empty(n)
    for i in range(n):
        m = np.outer(pg[i], pa[i])
        for (a_, b_), t in (((0, 0), 1 - lg[i] * la[i] * prawdziwe),
                            ((0, 1), 1 + lg[i] * prawdziwe),
                            ((1, 0), 1 + la[i] * prawdziwe),
                            ((1, 1), 1 - prawdziwe)):
            m[a_, b_] *= max(0.0, t)
        m /= m.sum()
        k = rng.choice(m.size, p=m.ravel())
        hg[i], ag[i] = h[k // len(h)], h[k % len(h)]
    odnalezione = dopasuj_rho(pg, pa, lg, la, hg, ag)
    assert odnalezione == pytest.approx(prawdziwe, abs=0.02)
