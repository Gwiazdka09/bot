"""Testy `scripts/lambda_kto_lepszy.py`.

Cały pomiar stoi na odzyskiwaniu λ rynku. Jeśli odzyskiwanie kłamie, kłamie
wszystko — a to jest dokładnie ten błąd, który ten skrypt prostuje po 04.09.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from estymator_lambda import p_1x2  # noqa: E402
from lambda_kto_lepszy import odzyskaj_lambdy, over25_z_lambd  # noqa: E402


def test_odzyskiwanie_wraca_do_tych_samych_lambd():
    """Round-trip: λ → 1X2 → λ. Bez tego mierzylibyśmy szum optymalizatora."""
    rng = np.random.default_rng(11)
    lg = rng.uniform(0.4, 3.2, 300)
    la = rng.uniform(0.3, 2.8, 300)
    p = p_1x2(lg, la)
    olg, ola, zbieglo = odzyskaj_lambdy(p[:, 0], p[:, 2])
    assert zbieglo.mean() > 0.98, "odzyskiwanie ma zbiegac prawie zawsze"
    assert olg[zbieglo] == pytest.approx(lg[zbieglo], abs=1e-4)
    assert ola[zbieglo] == pytest.approx(la[zbieglo], abs=1e-4)


def test_odzyskiwanie_nie_zalezy_od_punktu_startu():
    """Start jest zaszyty na (1.5, 1.2); wynik nie może od niego zależeć."""
    p = p_1x2(np.array([0.5, 3.0]), np.array([2.9, 0.4]))
    olg, ola, zbieglo = odzyskaj_lambdy(p[:, 0], p[:, 2])
    assert zbieglo.all()
    assert olg == pytest.approx([0.5, 3.0], abs=1e-4)
    assert ola == pytest.approx([2.9, 0.4], abs=1e-4)


def test_niezbiegniete_sa_oznaczone_a_nie_przemilczane():
    """Prawdopodobieństwa nie do osiągnięcia Poissonem muszą wypaść jawnie."""
    _, _, zbieglo = odzyskaj_lambdy(np.array([0.999]), np.array([0.999]))
    assert not zbieglo[0]


def test_over25_zgodne_z_macierza_produkcyjna():
    from footstats.config import MAX_GOLE
    from footstats.core.poisson import _macierz

    for lg, la in ((1.5, 1.1), (2.6, 2.1), (0.7, 0.6)):
        oczek = _macierz(lg, la, MAX_GOLE)[4]
        assert over25_z_lambd(np.array([lg]), np.array([la]))[0] == pytest.approx(
            oczek, abs=2e-4)


def test_over25_rosnie_z_lambdami():
    maly = over25_z_lambd(np.array([0.8]), np.array([0.7]))[0]
    duzy = over25_z_lambd(np.array([2.4]), np.array([2.1]))[0]
    assert maly < duzy < 1.0


def test_odrzuca_pierwiastek_pozorny_z_obciecia():
    """Regresja na blad znaleziony 2026-09-05.

    Macierz produkcyjna obcina na 8 golach, wiec (4.39, 21.64) daje 1X2 co do
    szostego miejsca identyczne z (0.5, 2.9) — cala masa siedzi w ogonie i
    rozklad przestaje zalezec od lambdy. Pojedynczy Newton ladowal na tej
    galezi i MELDOWAL ZBIEZNOSC. To jest ta sama pulapka, ktora skazila pomiar
    z 04.09.
    """
    p = p_1x2(np.array([0.5]), np.array([2.9]))
    lg, la, zbieglo = odzyskaj_lambdy(p[:, 0], p[:, 2])
    assert zbieglo[0]
    assert lg[0] == pytest.approx(0.5, abs=1e-3)
    assert la[0] == pytest.approx(2.9, abs=1e-3)


@pytest.mark.parametrize("para", [(0.4, 3.0), (3.0, 0.4), (0.3, 0.3), (2.8, 2.8)])
def test_odzyskiwanie_dziala_na_skrajnie_niesymetrycznych(para):
    """Skrajne pary to dokladnie te, w ktorych galaz pozorna jest blisko."""
    p = p_1x2(np.array([para[0]]), np.array([para[1]]))
    lg, la, zbieglo = odzyskaj_lambdy(p[:, 0], p[:, 2])
    assert zbieglo[0]
    assert (lg[0], la[0]) == pytest.approx(para, abs=1e-3)
