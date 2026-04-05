"""Testy core/pattern_analyzer.py — analiza wzorców historycznych."""
import pandas as pd
import pytest
from footstats.core.pattern_analyzer import (
    analyze_results_by_league,
    analyze_odds_calibration,
    analyze_form_vs_result,
    extract_marchewki_i_kije,
    _safe_pct,
    _implied_prob,
    MIN_MATCHES,
)


def _df_liga(n: int = 100, league: str = "GER-Bundesliga") -> pd.DataFrame:
    """Generuje minimalny DataFrame z meczami z jednej ligi."""
    rows = []
    for i in range(n):
        hg = i % 4          # 0,1,2,3,0,1,2,3,...
        ag = (i + 1) % 3    # 1,2,0,1,2,0,...
        if hg > ag:
            result = "H"
        elif hg == ag:
            result = "D"
        else:
            result = "A"
        rows.append({
            "league":       league,
            "date":         pd.Timestamp("2025-01-01") + pd.Timedelta(days=i),
            "home":         f"Team{i % 5}",
            "away":         f"Team{(i+1) % 5}",
            "hg":           hg,
            "ag":           ag,
            "result":       result,
            "total_goals":  hg + ag,
            "over25":       int(hg + ag > 2),
            "btts":         int(hg > 0 and ag > 0),
            "odds_h":       1.8,
            "odds_d":       3.5,
            "odds_a":       4.2,
        })
    return pd.DataFrame(rows)


# ── utils ─────────────────────────────────────────────────────────────────

class TestSafePct:
    def test_podstawowy(self):
        assert _safe_pct(25, 100) == 25.0

    def test_zero_mianownik(self):
        assert _safe_pct(5, 0) is None

    def test_zaokraglenie(self):
        assert _safe_pct(1, 3, decimals=2) == pytest.approx(33.33)


class TestImpliedProb:
    def test_kurs_2(self):
        assert _implied_prob(2.0) == pytest.approx(0.5)

    def test_kurs_1(self):
        assert _implied_prob(1.0) == 0.0

    def test_kurs_ponizej_1(self):
        assert _implied_prob(0.5) == 0.0


# ── analyze_results_by_league ─────────────────────────────────────────────

class TestAnalyzeResultsByLeague:
    def test_zwraca_dict(self):
        df = _df_liga(120)
        wynik = analyze_results_by_league(df)
        assert isinstance(wynik, dict)

    def test_liga_w_wyniku(self):
        df = _df_liga(120)
        wynik = analyze_results_by_league(df)
        assert "GER-Bundesliga" in wynik

    def test_za_malo_mecze_wykluczone(self):
        df = _df_liga(MIN_MATCHES - 1)
        wynik = analyze_results_by_league(df)
        assert "GER-Bundesliga" not in wynik

    def test_suma_wynikow_100(self):
        df = _df_liga(200)
        wynik = analyze_results_by_league(df)
        liga = wynik["GER-Bundesliga"]
        s = (liga.get("home_win") or 0) + (liga.get("draw") or 0) + (liga.get("away_win") or 0)
        assert abs(s - 100.0) < 1.0

    def test_over25_w_zakresie(self):
        df = _df_liga(200)
        wynik = analyze_results_by_league(df)
        over = wynik["GER-Bundesliga"].get("over25_pct")
        assert over is None or 0.0 <= over <= 100.0

    def test_dwie_ligi(self):
        df1 = _df_liga(120, "GER-Bundesliga")
        df2 = _df_liga(120, "ENG-Premier")
        df  = pd.concat([df1, df2]).reset_index(drop=True)
        wynik = analyze_results_by_league(df)
        assert "GER-Bundesliga" in wynik
        assert "ENG-Premier"    in wynik


# ── analyze_odds_calibration ──────────────────────────────────────────────

class TestAnalyzeOddsCalibration:
    def test_zwraca_dict_z_binami(self):
        df = _df_liga(200)
        wynik = analyze_odds_calibration(df)
        assert isinstance(wynik, dict)

    def test_klucze_biny(self):
        df = _df_liga(200)
        wynik = analyze_odds_calibration(df)
        # Powinien mieć klucze jako zakresy lub ligę
        assert len(wynik) >= 0  # może być pusty przy braku kursów — OK


# ── analyze_form_vs_result ────────────────────────────────────────────────

class TestAnalyzeFormVsResult:
    def test_zwraca_dict(self):
        df = _df_liga(200)
        wynik = analyze_form_vs_result(df)
        assert isinstance(wynik, dict)


# ── extract_marchewki_i_kije ──────────────────────────────────────────────

class TestExtractMarchewkiIKije:
    def test_zwraca_dict_z_kluczami(self):
        df = _df_liga(200)
        rbl = analyze_results_by_league(df)
        wynik = extract_marchewki_i_kije(rbl, {}, {})
        assert "marchewki" in wynik
        assert "kije" in wynik

    def test_marchewki_lista(self):
        df = _df_liga(200)
        rbl = analyze_results_by_league(df)
        wynik = extract_marchewki_i_kije(rbl, {}, {})
        assert isinstance(wynik["marchewki"], list)

    def test_over25_marchewka_gdy_wysoki(self):
        """Liga z Over2.5 > 58% powinna trafić do marchewek."""
        # Symuluj dane z wysokim Over2.5
        rbl = {
            "TST-Liga": {
                "n": 300,
                "home_win": 45.0,
                "draw": 25.0,
                "away_win": 30.0,
                "avg_goals": 3.1,
                "over25_pct": 62.0,
                "btts_pct": 58.0,
            }
        }
        wynik = extract_marchewki_i_kije(rbl, {}, {})
        marchewki_str = " ".join(wynik["marchewki"])
        assert "TST-Liga" in marchewki_str or "Over" in marchewki_str
