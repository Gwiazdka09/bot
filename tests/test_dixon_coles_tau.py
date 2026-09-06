"""Korekta τ Dixona-Colesa — to, czego dotąd nie było mimo nazwy `poisson-dc`.

PO CO: ramię nazwane „Dixon-Coles" liczyło `np.outer(pmf_h, pmf_a)`, czyli
DWA NIEZALEŻNE rozkłady Poissona z bayesowskim shrinkiem. Cała treść pracy
Dixona i Colesa (1997) to obserwacja, że przy niskich wynikach ta niezależność
nie zachodzi: 0-0 i 1-1 zdarzają się CZĘŚCIEJ, a 1-0 i 0-1 RZADZIEJ, niż wynika
z iloczynu. Ich poprawka τ dotyka dokładnie tych czterech pól:

    τ(0,0) = 1 - λ·μ·ρ      τ(0,1) = 1 + λ·ρ
    τ(1,0) = 1 + μ·ρ        τ(1,1) = 1 - ρ

Bez niej model zaniża remis — a remis to jeden z trzech rynków, na których
gramy. Zmierzone 09.08.2026: w kubełku 60-70% model trafia 47,1% (rynek 71,4%).

Flaga `USE_DC_TAU` domyślnie WYŁĄCZONA: to zmiana model-critical, więc wchodzi
dopiero po pomiarze walk-forward i decyzji człowieka.
"""
from __future__ import annotations

import numpy as np
import pytest

from footstats.core.poisson_bayesian import macierz_dixon_coles, tau_dixon_coles


class TestTau:
    """Sam współczynnik — cztery pola i neutralność poza nimi."""

    def test_rho_zero_nie_zmienia_niczego(self):
        """ρ=0 to model niezależny — τ musi być tożsamościowe."""
        for h in range(4):
            for a in range(4):
                assert tau_dixon_coles(h, a, 1.5, 1.2, rho=0.0) == 1.0

    def test_remisy_niskie_ida_w_gore(self):
        """0-0 i 1-1 są w danych częstsze, niż mówi niezależność."""
        assert tau_dixon_coles(1, 1, 1.5, 1.2, rho=-0.1) > 1.0

    def test_wyniki_jednobramkowe_ida_w_dol(self):
        assert tau_dixon_coles(1, 0, 1.5, 1.2, rho=-0.1) < 1.0
        assert tau_dixon_coles(0, 1, 1.5, 1.2, rho=-0.1) < 1.0

    @pytest.mark.parametrize(("h", "a"), [(2, 0), (0, 2), (2, 2), (3, 1), (0, 3)])
    def test_poza_czterema_polami_bez_zmian(self, h, a):
        """Poprawka dotyczy WYŁĄCZNIE wyników, gdzie oba zespoły mają ≤1 gola."""
        assert tau_dixon_coles(h, a, 1.5, 1.2, rho=-0.1) == 1.0

    def test_tau_nigdy_ujemne(self):
        """Ujemne τ dałoby ujemne prawdopodobieństwo — przy dużych λ i ρ to realne."""
        assert tau_dixon_coles(0, 0, 4.0, 4.0, rho=-0.2) >= 0.0


class TestMacierz:
    """Macierz wyników — normalizacja i kierunek zmiany."""

    def test_sumuje_sie_do_jedynki(self):
        M = macierz_dixon_coles(1.5, 1.2, rho=-0.1)
        assert M.sum() == pytest.approx(1.0)

    def test_rho_zero_rowna_sie_niezaleznemu_poissonowi(self):
        """Bez ρ macierz musi być identyczna z dotychczasową — zero regresji."""
        from scipy.stats import poisson

        from footstats.config import MAX_GOLE

        lam_h, lam_a = 1.5, 1.2
        oczekiwana = np.outer(
            poisson.pmf(np.arange(MAX_GOLE), lam_h),
            poisson.pmf(np.arange(MAX_GOLE), lam_a),
        )
        oczekiwana = oczekiwana / oczekiwana.sum()

        assert np.allclose(macierz_dixon_coles(lam_h, lam_a, rho=0.0), oczekiwana)

    def test_ujemne_rho_podnosi_remis(self):
        """Sedno poprawki: więcej masy na przekątnej niskich wyników."""
        lam_h, lam_a = 1.4, 1.3
        bez = macierz_dixon_coles(lam_h, lam_a, rho=0.0)
        z_tau = macierz_dixon_coles(lam_h, lam_a, rho=-0.13)

        assert np.trace(z_tau) > np.trace(bez)

    def test_zadne_pole_nie_jest_ujemne(self):
        M = macierz_dixon_coles(3.5, 3.5, rho=-0.2)
        assert (M >= 0).all()


class TestFlaga:
    """Domyślnie wyłączone — wejście dopiero po pomiarze i zgodzie."""

    def test_domyslnie_rho_zero(self):
        from footstats.config import DC_RHO, USE_DC_TAU

        assert USE_DC_TAU is False, "τ nie może wejść na produkcję bez decyzji"
        assert DC_RHO == 0.0 or not USE_DC_TAU

    def test_predykcja_bez_flagi_zachowuje_sie_jak_dotad(self, monkeypatch):
        """Wyłączona flaga = dokładnie poprzednie liczby, nie 'prawie'."""
        import pandas as pd

        from footstats.core import poisson_bayesian as pb

        df = pd.DataFrame({
            "data": pd.date_range("2025-01-01", periods=40, freq="7D"),
            "gospodarz": ["Legia", "Lech"] * 20,
            "goscie": ["Lech", "Legia"] * 20,
            "gole_g": [2, 1] * 20,
            "gole_a": [1, 1] * 20,
        })

        monkeypatch.setattr(pb, "USE_DC_TAU", False)
        bez = pb.predict_match_bayesian("Legia", "Lech", df)

        assert bez is not None
        # Tolerancja 2e-4, nie 1e-6: `predict_match_bayesian` zwraca trzy
        # liczby ZAOKRAGLONE do 4 miejsc, wiec ich suma moze odbiegac od
        # jedynki nawet o 1.5e-4. Surowa suma z macierzy jest dokladnie 1.
        # Prog 1e-6 przechodzil przypadkiem i pekl 06.09.2026 przy zmianie
        # lambd — nie byla to regresja, tylko inne miejsce zaokraglenia.
        assert bez["pw"] + bez["pr"] + bez["pa"] == pytest.approx(1.0, abs=2e-4)
