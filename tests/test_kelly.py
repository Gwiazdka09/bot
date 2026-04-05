"""Testy core/kelly.py — Kelly Criterion i EV."""
import pytest
from footstats.core.kelly import kelly_stake, kelly_kupon, ev_netto


class TestKellyStake:
    def test_brak_edge_zwraca_zero(self):
        # p=0.40, odds=2.0 → f* = (1*0.4 - 0.6)/1 = -0.2 → ujemny edge
        assert kelly_stake(0.40, 2.0) == 0.0

    def test_dodatni_edge(self):
        # p=0.60, odds=2.0 → f* = (1*0.6 - 0.4)/1 = 0.20 → stawka > 0
        stake = kelly_stake(0.60, 2.0, bankroll=200, fraction=3)
        assert stake > 0.0

    def test_min_stake(self):
        # Bardzo mały edge → raw < min_stake=2.0, zwraca min_stake
        stake = kelly_stake(0.52, 2.0, bankroll=100, fraction=10, min_stake=2.0)
        assert stake >= 2.0

    def test_max_stake_ogranicza(self):
        # Duży edge i duży bankroll → ograniczone przez max_stake
        stake = kelly_stake(0.90, 3.0, bankroll=10000, fraction=1, max_stake=50.0)
        assert stake <= 50.0

    def test_kurs_ponizej_1_zwraca_zero(self):
        assert kelly_stake(0.80, 0.99) == 0.0

    def test_p_zero_zwraca_zero(self):
        assert kelly_stake(0.0, 2.0) == 0.0

    def test_p_jeden_zwraca_zero(self):
        # p=1.0 to p >= 1.0, zwraca 0
        assert kelly_stake(1.0, 2.0) == 0.0

    def test_wartosc_zaokraglona_do_1_miejsca(self):
        stake = kelly_stake(0.65, 1.85, bankroll=200, fraction=3)
        # Sprawdź że ma co najwyżej 1 miejsce po przecinku
        assert stake == round(stake, 1)

    def test_fraction_wiekszy_daje_mniejsza_stawke(self):
        s3 = kelly_stake(0.65, 2.10, bankroll=200, fraction=3)
        s6 = kelly_stake(0.65, 2.10, bankroll=200, fraction=6)
        assert s3 >= s6


class TestKellyKupon:
    def test_pusty_zwraca_zero(self):
        assert kelly_kupon([]) == 0.0

    def test_jedna_noga(self):
        zdarzenia = [{"pewnosc_pct": 65, "kurs": 2.10}]
        stake = kelly_kupon(zdarzenia, bankroll=200, fraction=3)
        # Taki sam jak dla p=0.65, odds=2.10
        assert stake == kelly_stake(0.65, 2.10, bankroll=200, fraction=3)

    def test_wiele_nog_mnozi_prawdopodobienstwa(self):
        # 2 nogi po 70% → p_kupon = 0.49, kurs = 2.0*2.0 = 4.0
        zdarzenia = [
            {"pewnosc_pct": 70, "kurs": 2.0},
            {"pewnosc_pct": 70, "kurs": 2.0},
        ]
        stake = kelly_kupon(zdarzenia, bankroll=200, fraction=3)
        expected = kelly_stake(0.49, 4.0, bankroll=200, fraction=3)
        assert stake == expected

    def test_brak_edge_w_kuponie_zwraca_zero(self):
        # Niskie prawdopodobieństwo vs niskie kursy
        zdarzenia = [
            {"pewnosc_pct": 30, "kurs": 1.5},
            {"pewnosc_pct": 30, "kurs": 1.5},
        ]
        assert kelly_kupon(zdarzenia) == 0.0


class TestEvNetto:
    def test_ev_dodatni(self):
        # p=0.60, odds=2.0 → EV = 0.60*2.0*0.88 - 1 = 1.056 - 1 = 0.056
        ev = ev_netto(0.60, 2.0)
        assert abs(ev - 0.056) < 0.001

    def test_ev_ujemny(self):
        # p=0.40, odds=2.0 → EV = 0.40*2.0*0.88 - 1 = 0.704 - 1 = -0.296
        ev = ev_netto(0.40, 2.0)
        assert ev < 0.0

    def test_ev_przy_kursie_1(self):
        ev = ev_netto(1.0, 1.0)
        # 1.0*1.0*0.88 - 1 = -0.12
        assert abs(ev - (-0.12)) < 0.001

    def test_podatek_wplyw(self):
        # Bez podatku: EV = 0.60*2.0 - 1 = 0.20
        # Z podatkiem 12%: EV = 0.60*2.0*0.88 - 1 = 0.056
        ev_z = ev_netto(0.60, 2.0, podatek=0.12)
        ev_bez = ev_netto(0.60, 2.0, podatek=0.0)
        assert ev_bez > ev_z

    def test_zwraca_float(self):
        assert isinstance(ev_netto(0.55, 1.90), float)
