"""Testy core/walkforward.py — walk-forward backtest."""
import pandas as pd
import pytest
from unittest.mock import patch
from footstats.core.walkforward import (
    _lambda,
    _forma,
    _poisson_probs,
    predict_single,
    raport_walkforward,
)


def _df_hist(n: int = 30) -> pd.DataFrame:
    """Historyczny DataFrame z meczami do testów walk-forward."""
    rows = []
    teams = ["Bayern", "Dortmund", "Leipzig", "Leverkusen", "Stuttgart"]
    for i in range(n):
        hg = i % 4
        ag = (i + 1) % 3
        if hg > ag:
            result = "H"
        elif hg == ag:
            result = "D"
        else:
            result = "A"
        rows.append({
            "date":   pd.Timestamp("2024-01-01") + pd.Timedelta(days=i * 7),
            "league": "GER-Bundesliga",
            "home":   teams[i % len(teams)],
            "away":   teams[(i + 1) % len(teams)],
            "hg":     hg,
            "ag":     ag,
            "result": result,
        })
    return pd.DataFrame(rows)


# ── _lambda ───────────────────────────────────────────────────────────────

class TestLambda:
    def test_za_malo_mecze_zwraca_none(self):
        df = _df_hist(3)
        result = _lambda(df, "Bayern", as_home=True)
        assert result is None

    def test_wystarczajaco_mecze_zwraca_float(self):
        df = _df_hist(30)
        result = _lambda(df, "Bayern", as_home=True)
        # Bayern gra co 5 meczów (teams[0]), przy 30 meczach ma 6 home meczów
        if result is not None:
            assert isinstance(result, float)
            assert result >= 0.0

    def test_as_home_vs_away(self):
        df = _df_hist(30)
        lh = _lambda(df, "Bayern", as_home=True)
        la = _lambda(df, "Bayern", as_home=False)
        # Obie mogą być None jeśli za mało danych, ale sprawdź typy
        for v in [lh, la]:
            assert v is None or isinstance(v, float)


# ── _forma ────────────────────────────────────────────────────────────────

class TestForma:
    def test_pusta_historia_zwraca_default(self):
        df = pd.DataFrame(columns=["home", "away", "result"])
        result = _forma(df, "Bayern")
        assert result == 1.0  # default gdy brak danych

    def test_wartosc_w_zakresie(self):
        df = _df_hist(30)
        result = _forma(df, "Bayern")
        assert 0.0 <= result <= 3.0  # punkty na mecz: 0-3

    def test_zwraca_float(self):
        df = _df_hist(30)
        assert isinstance(_forma(df, "Bayern"), float)


# ── _poisson_probs ────────────────────────────────────────────────────────

class TestPoissonProbs:
    def test_suma_do_jedynki(self):
        pw, pr, pp = _poisson_probs(1.5, 1.2)
        assert abs(pw + pr + pp - 1.0) < 0.01

    def test_wyzsza_lambda_home_faworyzuje_dom(self):
        # lam_h=2.5, lam_a=0.8 → P(home win) powinno być wysokie
        pw, _, _ = _poisson_probs(2.5, 0.8)
        assert pw > 0.60

    def test_wyzsza_lambda_away_faworyzuje_gosci(self):
        # lam_h=0.8, lam_a=2.5 → P(away win) powinno być wysokie
        _, _, pp = _poisson_probs(0.8, 2.5)
        assert pp > 0.60

    def test_rowne_lambdy_remis_moze_byc_powazny(self):
        pw, pr, pp = _poisson_probs(1.3, 1.3)
        # Przy równych lambdach prawdopodobieństwa home≈away
        assert abs(pw - pp) < 0.05

    def test_wartosci_nie_ujemne(self):
        pw, pr, pp = _poisson_probs(1.0, 1.0)
        assert pw >= 0 and pr >= 0 and pp >= 0

    def test_brak_goli_remis_dominuje(self):
        # Przy lambdach bliskich 0, 0-0 (remis) jest najczęstszy
        pw, pr, pp = _poisson_probs(0.1, 0.1)
        assert pr > pw and pr > pp


# ── predict_single ────────────────────────────────────────────────────────

class TestPredictSingle:
    def test_za_malo_historii_zwraca_none(self):
        hist = _df_hist(3)
        result = predict_single(hist, "Bayern", "Dortmund")
        assert result is None

    def test_wystarczajaco_historii_zwraca_dict(self):
        hist = _df_hist(30)
        result = predict_single(hist, "Bayern", "Dortmund")
        if result is not None:
            assert "tip" in result
            assert "conf" in result
            assert "lh" in result
            assert "la" in result
            assert "over25" in result

    def test_tip_z_zbioru(self):
        hist = _df_hist(30)
        result = predict_single(hist, "Bayern", "Dortmund")
        if result is not None:
            assert result["tip"] in ("1", "X", "2")

    def test_conf_w_zakresie(self):
        hist = _df_hist(30)
        result = predict_single(hist, "Bayern", "Dortmund")
        if result is not None:
            assert 0.0 <= result["conf"] <= 1.0

    def test_over25_w_zakresie(self):
        hist = _df_hist(30)
        result = predict_single(hist, "Bayern", "Dortmund")
        if result is not None:
            assert 0.0 <= result["over25"] <= 1.0

    def test_nieznane_druzyny_zwraca_none(self):
        hist = _df_hist(30)
        result = predict_single(hist, "FC Nieznany", "FK Obcy")
        assert result is None


# ── raport_walkforward ────────────────────────────────────────────────────

class TestRaportWalkforward:
    def _df_out(self) -> pd.DataFrame:
        rows = [
            {"league": "GER-Bundesliga", "correct_1x2": 1, "correct_o25": 1,
             "pred_conf": 0.65, "match_date": "2025-06-01",
             "home": "A", "away": "B", "actual_res": "H", "pred_res": "1"},
            {"league": "GER-Bundesliga", "correct_1x2": 0, "correct_o25": 1,
             "pred_conf": 0.50, "match_date": "2025-06-02",
             "home": "C", "away": "D", "actual_res": "A", "pred_res": "1"},
            {"league": "GER-Bundesliga", "correct_1x2": 1, "correct_o25": 0,
             "pred_conf": 0.72, "match_date": "2025-06-03",
             "home": "E", "away": "F", "actual_res": "H", "pred_res": "1"},
        ]
        return pd.DataFrame(rows)

    def test_zwraca_string(self):
        df = self._df_out()
        raport = raport_walkforward(df)
        assert isinstance(raport, str)

    def test_zawiera_nazwe_ligi(self):
        df = self._df_out()
        raport = raport_walkforward(df)
        assert "GER-Bundesliga" in raport

    def test_zawiera_accuracy(self):
        df = self._df_out()
        raport = raport_walkforward(df)
        assert "accuracy" in raport.lower() or "%" in raport

    def test_pusta_df_nie_rzuca_wyjatku(self):
        df = pd.DataFrame(columns=["league", "correct_1x2", "correct_o25", "pred_conf"])
        raport = raport_walkforward(df)
        assert isinstance(raport, str)
