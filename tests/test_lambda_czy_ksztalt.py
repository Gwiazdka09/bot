"""Rozdzielenie lambda / ksztalt — czy mierzymy TEN model, ktory gra."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from footstats.core.bet_builder import probability_matrix  # noqa: E402
from lambda_czy_ksztalt import _wyjscia, dopasuj_lambdy, macierz  # noqa: E402


@pytest.mark.parametrize("lh,la", [(1.4, 1.1), (0.6, 2.3), (2.9, 0.4), (1.0, 1.0)])
def test_wektorowa_macierz_zgadza_sie_z_produkcyjna(lh, la):
    """Napisalem wlasna, wektorowa wersje dla szybkosci. Gdyby rozjechala sie
    z `core/bet_builder.probability_matrix`, caly pomiar dotyczylby innego
    modelu niz ten, ktory gra — i nikt by tego nie zobaczyl."""
    assert np.allclose(macierz(lh, la), probability_matrix(lh, la, rho=-0.05),
                       atol=1e-12)


def test_macierz_sumuje_sie_do_jedynki():
    for lh, la in ((0.2, 3.4), (1.7, 1.7)):
        assert macierz(lh, la).sum() == pytest.approx(1.0)


def test_wyjscia_sumuja_sie_do_jedynki_z_remisem():
    pw, pp, _ = _wyjscia(macierz(1.5, 1.2))
    assert 0 < pw < 1 and 0 < pp < 1
    assert pw + pp < 1.0, "brak miejsca na remis"


def test_wieksza_lambda_gospodarza_podnosi_jego_szanse():
    slaby = _wyjscia(macierz(0.8, 1.5))[0]
    mocny = _wyjscia(macierz(2.2, 1.5))[0]
    assert mocny > slaby


def test_dopasowanie_lambd_odtwarza_zadane_1X2():
    """Sedno metody: dwa parametry, dwa cele. Jesli odtworzenie jest niedokladne,
    wszystkie trzy pomiary stoja na zlych lambdach."""
    for lh, la in ((1.4, 1.1), (2.1, 0.7), (0.9, 1.9)):
        pw, pp, _ = _wyjscia(macierz(lh, la))
        lh2, la2 = dopasuj_lambdy(pw, pp)
        pw2, pp2, _ = _wyjscia(macierz(lh2, la2))
        assert pw2 == pytest.approx(pw, abs=2e-3), f"pw nieodtworzone dla {lh},{la}"
        assert pp2 == pytest.approx(pp, abs=2e-3), f"pp nieodtworzone dla {lh},{la}"


def test_dopasowanie_odzyskuje_same_lambdy_a_nie_tylko_prawdopodobienstwa():
    """Odtworzenie 1X2 nie wystarczy — pomiar 1 porownuje LAMBDY wprost,
    wiec musza wracac te same, nie dowolna para dajaca to samo 1X2."""
    for lh, la in ((1.4, 1.1), (2.1, 0.7)):
        pw, pp, _ = _wyjscia(macierz(lh, la))
        lh2, la2 = dopasuj_lambdy(pw, pp)
        assert lh2 == pytest.approx(lh, abs=0.05)
        assert la2 == pytest.approx(la, abs=0.05)
