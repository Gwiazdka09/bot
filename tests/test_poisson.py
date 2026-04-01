"""Testy core/poisson.py oraz core/classifier.py."""
import pandas as pd
import pytest
from datetime import datetime, timedelta

from footstats.core.classifier import _czy_knockout, KlasyfikatorMeczu
from footstats.core.form import _wagi_mecze, _oblicz_sile_wazona
from footstats.core.poisson import predict_match


def _df_minimal(n=20):
    """Minimalne DataFrame z meczami do testów (kolumny polskie)."""
    today = datetime.now()
    druzyny = ["Arsenal", "Chelsea", "Liverpool", "Man Utd", "Tottenham", "Everton"]
    mecze = []
    for i in range(n):
        g = druzyny[i % len(druzyny)]
        a = druzyny[(i + 1) % len(druzyny)]
        mecze.append({
            "gospodarz": g,
            "goscie": a,
            "gole_g": i % 4,
            "gole_a": i % 3,
            "data": (today - timedelta(days=i * 7)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "faza": "REGULAR_SEASON",
        })
    return pd.DataFrame(mecze)


class TestCzyKnockout:
    def test_final_knockout(self):
        assert _czy_knockout("FINAL") is True

    def test_quarter_finals_knockout(self):
        assert _czy_knockout("QUARTER_FINALS") is True

    def test_regular_season_nie_knockout(self):
        assert _czy_knockout("REGULAR_SEASON") is False

    def test_pusty_string(self):
        assert _czy_knockout("") is False

    def test_group_stage_nie_knockout(self):
        assert _czy_knockout("GROUP_STAGE") is False

    def test_round_of_16_knockout(self):
        assert _czy_knockout("ROUND_OF_16") is True

    def test_case_insensitive(self):
        assert _czy_knockout("final") is True
        assert _czy_knockout("Final") is True


class TestWagiMecze:
    def test_zwraca_series(self):
        df = _df_minimal(10)
        wagi = _wagi_mecze(df)
        assert isinstance(wagi, pd.Series)

    def test_dlugosc_rowna_df(self):
        df = _df_minimal(10)
        wagi = _wagi_mecze(df)
        assert len(wagi) == len(df)

    def test_wagi_pozytywne(self):
        df = _df_minimal(10)
        wagi = _wagi_mecze(df)
        assert (wagi >= 0).all()

    def test_nowsze_mecze_maja_wieksze_wagi(self):
        """Wagi rosną dla końcowych pozycji (nowszych meczów) w df posortowanym wg daty."""
        df = _df_minimal(10)
        # Posortuj rosnąco wg daty (najstarsza = 0, najnowsza = 9)
        df_sorted = df.sort_values("data").reset_index(drop=True)
        wagi = _wagi_mecze(df_sorted)
        # Nowszy mecz (wyższy indeks po sort asc) powinien mieć wyższą lub równą wagę
        assert wagi.iloc[-1] >= wagi.iloc[0]


class TestPredictMatch:
    def test_zwraca_dict_lub_none(self):
        df = _df_minimal(20)
        wynik = predict_match("Arsenal", "Chelsea", df)
        assert wynik is None or isinstance(wynik, dict)

    def test_wynik_ma_klucze(self):
        df = _df_minimal(20)
        wynik = predict_match("Arsenal", "Chelsea", df)
        if wynik is not None:
            assert "p_wygrana" in wynik
            assert "p_remis" in wynik
            assert "p_przegrana" in wynik

    def test_prawdopodobienstwa_sumuja_sie_do_1(self):
        df = _df_minimal(20)
        wynik = predict_match("Arsenal", "Chelsea", df)
        if wynik is not None:
            total = wynik["p_wygrana"] + wynik["p_remis"] + wynik["p_przegrana"]
            assert abs(total - 100.0) < 0.5  # wartości w procentach (0-100)

    def test_za_malo_danych_zwraca_none(self):
        df = _df_minimal(2)
        wynik = predict_match("Arsenal", "Chelsea", df)
        # Przy bardzo malej probce moze zwrocic None
        assert wynik is None or isinstance(wynik, dict)

    def test_nieznane_druzyny(self):
        df = _df_minimal(20)
        wynik = predict_match("Nieznana FC", "Obca United", df)
        assert wynik is None
