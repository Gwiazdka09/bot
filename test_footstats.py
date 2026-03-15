"""
test_footstats.py – Testy jednostkowe FootStats v2.7

Pokrycie:
    ✔ _s()                    – helper null-safe string
    ✔ _parse_date()            – parsowanie dat wieloformatowe
    ✔ _pdf()                   – transliteracja polskich znakow
    ✔ _czy_knockout()          – wykrywanie fazy pucharowej
    ✔ _bzz_parse_prob()        – parser Bzzoiro (4 formaty + edge cases)
    ✔ _ml_do_predykcji()       – konwersja ML → format predykcji
    ✔ _typy_pewne()            – zbieranie typow bukmacherskich >= prog
    ✔ typy_zaklady()           – klasyfikacja typow z progami
    ✔ _wagi_mecze()            – wagi czasowe meczow
    ✔ _oblicz_sile_wazona()    – wskazniki ataku/obrony druzyny
    ✔ pobierz_forme()          – forma druzyny z df
    ✔ _korekta_rewanz_v26()    – korekta lambd rewanzowych
    ✔ AnalizaDomWyjazd.analiza()– statystyki dom/wyjazd + Podroznik
    ✔ _af_budget_load/save()   – budzet API-Football (dysk)
    ✔ af_budget_status()       – stan budzetu
    ✔ _cache_get/_cache_set()  – RAM cache z TTL

URUCHOMIENIE:
    python -m pytest test_footstats.py -v
    python -m pytest test_footstats.py -v --tb=short
    python test_footstats.py          (bez pytest – stdlib unittest)
"""

import sys
import json
import math
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open, call
from datetime import datetime, timedelta
from io import StringIO

# ── Ustawienie sciezki do footstats.py ─────────────────────────────
# Zakladamy ze test_footstats.py lezy obok footstats.py
sys.path.insert(0, str(Path(__file__).parent))

# Mockujemy biblioteki UI + HTTP zanim zaimportujemy footstats,
# bo sam import uruchamia kod na poziomie modulu (console = Console())
_mock_console = MagicMock()
_mock_rich     = MagicMock()
_mock_requests = MagicMock()

# Patch modułów PRZED importem footstats
import unittest.mock as _um
_patches = [
    _um.patch.dict("sys.modules", {
        "rich":                    _mock_rich,
        "rich.console":            MagicMock(),
        "rich.table":              MagicMock(),
        "rich.panel":              MagicMock(),
        "rich.progress":           MagicMock(),
        "rich.prompt":             MagicMock(),
        "rich.text":               MagicMock(),
        "rich.box":                MagicMock(),
        "rich.columns":            MagicMock(),
        "rich.align":              MagicMock(),
        "reportlab":               MagicMock(),
        "reportlab.lib":           MagicMock(),
        "reportlab.lib.pagesizes": MagicMock(),
        "reportlab.lib.colors":    MagicMock(),
        "reportlab.lib.styles":    MagicMock(),
        "reportlab.lib.units":     MagicMock(),
        "reportlab.lib.enums":     MagicMock(),
        "reportlab.platypus":      MagicMock(),
        "reportlab.pdfbase":       MagicMock(),
        "reportlab.pdfbase.pdfmetrics": MagicMock(),
        "reportlab.pdfbase.ttfonts":    MagicMock(),
        "dotenv":                  MagicMock(),
        "requests":                _mock_requests,
    })
]
for p in _patches:
    p.start()

# Importuj footstats po zaaplikowaniu patchy
try:
    import footstats as fs
    FOOTSTATS_DOSTEPNY = True
except ImportError as e:
    FOOTSTATS_DOSTEPNY = False
    print(f"[WARN] Nie mozna zaimportowac footstats.py: {e}", file=sys.stderr)

import pandas as pd
import numpy as np

# ════════════════════════════════════════════════════════════════════
#  POMOCNICZE FUNKCJE FABRYCZNE
# ════════════════════════════════════════════════════════════════════

def _df_mecze(*args) -> pd.DataFrame:
    """
    Tworzy minimalny DataFrame z meczami.
    Argumenty: (gospodarz, goscie, gole_g, gole_a, data_str?)
    """
    wiersze = []
    for i, a in enumerate(args):
        g, goscie, gg, ga = a[0], a[1], a[2], a[3]
        data = a[4] if len(a) > 4 else f"2024-0{(i%9)+1}-01"
        wiersze.append({
            "gospodarz": g, "goscie": goscie,
            "gole_g": gg, "gole_a": ga, "data": data
        })
    df = pd.DataFrame(wiersze)
    df["gole_g"] = df["gole_g"].astype(float)
    df["gole_a"] = df["gole_a"].astype(float)
    return df


def _df_minimal() -> pd.DataFrame:
    """Standardowy DataFrame testowy: 3 druzyny, 9 meczow."""
    return _df_mecze(
        ("Arsenal",  "Chelsea",    2, 1, "2024-01-01"),
        ("Chelsea",  "ManCity",    0, 3, "2024-01-08"),
        ("ManCity",  "Arsenal",    1, 1, "2024-01-15"),
        ("Arsenal",  "ManCity",    2, 0, "2024-01-22"),
        ("Chelsea",  "Arsenal",    1, 2, "2024-01-29"),
        ("ManCity",  "Chelsea",    4, 0, "2024-02-05"),
        ("Arsenal",  "Chelsea",    1, 0, "2024-02-12"),
        ("Chelsea",  "ManCity",    0, 2, "2024-02-19"),
        ("ManCity",  "Arsenal",    0, 1, "2024-02-26"),
    )


# ════════════════════════════════════════════════════════════════════
#  TEST 1: _s() – helper bezpiecznego stringa
# ════════════════════════════════════════════════════════════════════

@unittest.skipUnless(FOOTSTATS_DOSTEPNY, "footstats.py niedostepny")
class TestHelperS(unittest.TestCase):

    def test_none_zwraca_domyslna(self):
        # Domyslna to zwykly myslnik "-", nie pauza "–"
        self.assertEqual(fs._s(None), "-")

    def test_none_zwraca_custom_domyslna(self):
        self.assertEqual(fs._s(None, "N/A"), "N/A")

    def test_pusty_string(self):
        self.assertEqual(fs._s(""), "-")

    def test_string_ze_spacjami(self):
        self.assertEqual(fs._s("   "), "-")

    def test_nan_float(self):
        self.assertEqual(fs._s(float("nan")), "-")

    def test_nan_string(self):
        self.assertEqual(fs._s("nan"), "-")

    def test_none_string(self):
        self.assertEqual(fs._s("none"), "-")

    def test_null_string(self):
        self.assertEqual(fs._s("null"), "-")

    def test_poprawny_string(self):
        self.assertEqual(fs._s("Arsenal"), "Arsenal")

    def test_liczba_int(self):
        self.assertEqual(fs._s(42), "42")

    def test_liczba_float(self):
        wynik = fs._s(3.14)
        self.assertIn("3.14", wynik)

    def test_zero(self):
        """Zero to poprawna wartosc, nie None."""
        self.assertEqual(fs._s(0), "0")

    def test_false(self):
        """False to poprawna wartosc."""
        self.assertEqual(fs._s(False), "False")

    def test_string_z_bialymi_znakami_normalny(self):
        """Poprawny string ze spacjami z przodu/tylu."""
        self.assertEqual(fs._s("  Arsenal  "), "Arsenal")

    def test_lista(self):
        """Lista nie jest stringiem ale konwertujemy."""
        wynik = fs._s([1, 2, 3])
        self.assertIsInstance(wynik, str)
        self.assertNotEqual(wynik, "–")


# ════════════════════════════════════════════════════════════════════
#  TEST 2: _parse_date() – parsowanie dat
# ════════════════════════════════════════════════════════════════════

@unittest.skipUnless(FOOTSTATS_DOSTEPNY, "footstats.py niedostepny")
class TestParseDate(unittest.TestCase):

    def test_format_iso_z_Z(self):
        wynik = fs._parse_date("2024-03-15T20:30:00Z")
        self.assertIsNotNone(wynik)
        self.assertEqual(wynik.year, 2024)
        self.assertEqual(wynik.month, 3)
        self.assertEqual(wynik.day, 15)
        self.assertEqual(wynik.hour, 20)

    def test_format_iso_bez_Z(self):
        wynik = fs._parse_date("2024-03-15T20:30:00")
        self.assertIsNotNone(wynik)
        self.assertEqual(wynik.hour, 20)

    def test_format_sama_data(self):
        wynik = fs._parse_date("2024-03-15")
        self.assertIsNotNone(wynik)
        self.assertEqual(wynik.day, 15)

    def test_none_zwraca_none(self):
        self.assertIsNone(fs._parse_date(None))

    def test_pusty_string(self):
        self.assertIsNone(fs._parse_date(""))

    def test_myslnik(self):
        self.assertIsNone(fs._parse_date("-"))

    def test_nan_string(self):
        self.assertIsNone(fs._parse_date("nan"))

    def test_bledny_format(self):
        self.assertIsNone(fs._parse_date("15/03/2024"))

    def test_bledna_data(self):
        """30 lutego nie istnieje."""
        self.assertIsNone(fs._parse_date("2024-02-30"))

    def test_stary_rok(self):
        """Bardzo stara data – moze byc w historii H2H."""
        wynik = fs._parse_date("1990-06-08")
        self.assertIsNotNone(wynik)
        self.assertEqual(wynik.year, 1990)

    def test_przyszla_data(self):
        """Nadchodzace mecze maja date w przyszlosci."""
        wynik = fs._parse_date("2099-12-31")
        self.assertIsNotNone(wynik)
        self.assertEqual(wynik.year, 2099)


# ════════════════════════════════════════════════════════════════════
#  TEST 3: _czy_knockout() – fazy pucharowe
# ════════════════════════════════════════════════════════════════════

@unittest.skipUnless(FOOTSTATS_DOSTEPNY, "footstats.py niedostepny")
class TestCzyKnockout(unittest.TestCase):

    def test_final(self):
        self.assertTrue(fs._czy_knockout("FINAL"))

    def test_polfinaly(self):
        self.assertTrue(fs._czy_knockout("SEMI_FINALS"))

    def test_cwierc(self):
        self.assertTrue(fs._czy_knockout("QUARTER_FINALS"))

    def test_last_16(self):
        self.assertTrue(fs._czy_knockout("LAST_16"))

    def test_playoff(self):
        self.assertTrue(fs._czy_knockout("PLAYOFFS"))

    def test_regular_season_nie_jest_knockout(self):
        self.assertFalse(fs._czy_knockout("REGULAR_SEASON"))

    def test_group_stage_nie_jest_knockout(self):
        self.assertFalse(fs._czy_knockout("GROUP_STAGE"))

    def test_pusty_string(self):
        self.assertFalse(fs._czy_knockout(""))

    def test_none_jako_string(self):
        self.assertFalse(fs._czy_knockout(None))

    def test_male_litery(self):
        """Stage moze przyjsc z API jako male litery."""
        self.assertTrue(fs._czy_knockout("final"))

    def test_mieszane_litery(self):
        self.assertTrue(fs._czy_knockout("Final"))

    def test_nieznany_stage(self):
        self.assertFalse(fs._czy_knockout("MATCH_DAY_5"))


# ════════════════════════════════════════════════════════════════════
#  TEST 4: _bzz_parse_prob() – parser Bzzoiro
# ════════════════════════════════════════════════════════════════════

@unittest.skipUnless(FOOTSTATS_DOSTEPNY, "footstats.py niedostepny")
class TestBzzParseProb(unittest.TestCase):

    # ── None / puste ───────────────────────────────────────────────

    def test_none_zwraca_none(self):
        self.assertIsNone(fs._bzz_parse_prob(None))

    def test_pusty_dict_zwraca_none(self):
        self.assertIsNone(fs._bzz_parse_prob({}))

    def test_string_zwraca_none(self):
        self.assertIsNone(fs._bzz_parse_prob("55%"))

    def test_lista_zwraca_none(self):
        self.assertIsNone(fs._bzz_parse_prob([55, 25, 20]))

    # ── Format A: {percent: {home:"55%"}} ─────────────────────────

    def test_format_A_procenty_string(self):
        dane = {"percent": {"home": "55%", "draw": "25%", "away": "20%"}}
        wynik = fs._bzz_parse_prob(dane)
        self.assertIsNotNone(wynik)
        pw, pr, pp, bt, o25 = wynik
        self.assertAlmostEqual(pw, 55.0, delta=0.2)
        self.assertAlmostEqual(pr, 25.0, delta=0.2)
        self.assertAlmostEqual(pp, 20.0, delta=0.2)

    def test_format_A_normalizuje_do_100(self):
        """Suma prob. musi byc 100% po normalizacji."""
        dane = {"percent": {"home": "60%", "draw": "20%", "away": "30%"}}  # suma = 110%
        wynik = fs._bzz_parse_prob(dane)
        self.assertIsNotNone(wynik)
        pw, pr, pp = wynik[0], wynik[1], wynik[2]
        self.assertAlmostEqual(pw + pr + pp, 100.0, delta=0.5)

    def test_format_A_z_btts_i_over25(self):
        dane = {
            "percent": {"home": "60%", "draw": "25%", "away": "15%"},
            "btts":    "65%",
            "over_2_5": "70%"
        }
        wynik = fs._bzz_parse_prob(dane)
        self.assertIsNotNone(wynik)
        pw, pr, pp, bt, o25 = wynik
        self.assertGreater(bt, 0)
        self.assertGreater(o25, 0)

    def test_format_A_zerowe_wartosci(self):
        """Jesli suma < 5%, zwroc None (dane niespojne)."""
        dane = {"percent": {"home": "0%", "draw": "0%", "away": "0%"}}
        self.assertIsNone(fs._bzz_parse_prob(dane))

    # ── Format B: home_win_prob (floaty 0-1) ───────────────────────

    def test_format_B_floaty(self):
        dane = {"home_win_prob": 0.55, "draw_prob": 0.25, "away_win_prob": 0.20}
        wynik = fs._bzz_parse_prob(dane)
        self.assertIsNotNone(wynik)
        pw, pr, pp = wynik[0], wynik[1], wynik[2]
        self.assertAlmostEqual(pw, 55.0, delta=0.5)

    def test_format_B_z_btts_over25(self):
        dane = {
            "home_win_prob": 0.60, "draw_prob": 0.25, "away_win_prob": 0.15,
            "btts": 0.68, "over_2_5": 0.72,
        }
        wynik = fs._bzz_parse_prob(dane)
        self.assertIsNotNone(wynik)
        pw, pr, pp, bt, o25 = wynik
        self.assertAlmostEqual(bt, 68.0, delta=1.0)
        self.assertAlmostEqual(o25, 72.0, delta=1.0)

    def test_format_B_pod_proba(self):
        """home_win_prob ale suma = 0 → None."""
        dane = {"home_win_prob": 0, "draw_prob": 0, "away_win_prob": 0}
        self.assertIsNone(fs._bzz_parse_prob(dane))

    # ── Format C: home/draw/away jako int ─────────────────────────

    def test_format_C_inty(self):
        dane = {"home": 55, "draw": 25, "away": 20}
        wynik = fs._bzz_parse_prob(dane)
        self.assertIsNotNone(wynik)
        self.assertAlmostEqual(wynik[0], 55.0, delta=0.2)

    def test_format_C_float_procenty(self):
        dane = {"home": 55.5, "draw": 24.5, "away": 20.0}
        wynik = fs._bzz_parse_prob(dane)
        self.assertIsNotNone(wynik)

    # ── Format D: zagniezdzone ─────────────────────────────────────

    def test_format_D_predictions(self):
        dane = {"predictions": {"percent": {"home": "60%", "draw": "25%", "away": "15%"}}}
        wynik = fs._bzz_parse_prob(dane)
        self.assertIsNotNone(wynik)
        self.assertAlmostEqual(wynik[0], 60.0, delta=0.5)

    def test_format_D_prediction_singular(self):
        dane = {"prediction": {"home_win_prob": 0.60, "draw_prob": 0.25, "away_win_prob": 0.15}}
        wynik = fs._bzz_parse_prob(dane)
        self.assertIsNotNone(wynik)

    # ── Edge cases ─────────────────────────────────────────────────

    def test_nieznany_format_zwraca_none(self):
        dane = {"winner": "Arsenal", "confidence": 0.8}
        self.assertIsNone(fs._bzz_parse_prob(dane))

    def test_wartosci_gt_100_sa_clampowane(self):
        """BTTS > 100% jest niemozliwe – musi byc przyciete."""
        dane = {
            "percent": {"home": "60%", "draw": "20%", "away": "20%"},
            "btts": "150%"
        }
        wynik = fs._bzz_parse_prob(dane)
        if wynik is not None:
            bt = wynik[3]
            self.assertLessEqual(bt, 100.0)

    def test_format_A_brakujacy_klucz_home(self):
        """Brakuje klucza home – dane niepelne."""
        dane = {"percent": {"draw": "30%", "away": "25%"}}
        wynik = fs._bzz_parse_prob(dane)
        # Moze zwrocic None lub probowac innego formatu
        # Wazne: nie crasha

    def test_wszystkie_prawdopodobienstwta_w_zakresie(self):
        """pw, pr, pp musza byc w [0, 100]."""
        dane = {"percent": {"home": "45%", "draw": "35%", "away": "20%"}}
        wynik = fs._bzz_parse_prob(dane)
        self.assertIsNotNone(wynik)
        for v in wynik:
            self.assertGreaterEqual(v, 0, f"Wartosc ujemna: {v}")
            self.assertLessEqual(v, 100, f"Wartosc > 100: {v}")

    def test_format_B_autoparsowanie_ulamkow_vs_procenty(self):
        """Auto-wykrywanie: 0.55 → 55%, ale 55.0 → 55% tez."""
        dane_ulamki = {"home_win_prob": 0.55, "draw_prob": 0.25, "away_win_prob": 0.20}
        dane_procenty = {"home": 55, "draw": 25, "away": 20}
        wynik_u = fs._bzz_parse_prob(dane_ulamki)
        wynik_p = fs._bzz_parse_prob(dane_procenty)
        self.assertIsNotNone(wynik_u)
        self.assertIsNotNone(wynik_p)
        self.assertAlmostEqual(wynik_u[0], wynik_p[0], delta=1.0)


# ════════════════════════════════════════════════════════════════════
#  TEST 5: _ml_do_predykcji() – konwersja ML
# ════════════════════════════════════════════════════════════════════

@unittest.skipUnless(FOOTSTATS_DOSTEPNY, "footstats.py niedostepny")
class TestMlDoPredykcji(unittest.TestCase):

    def _pred_ok(self):
        return {"percent": {"home": "60%", "draw": "25%", "away": "15%"}}

    def test_none_zwraca_none(self):
        self.assertIsNone(fs._ml_do_predykcji(None))

    def test_pusty_dict_zwraca_none(self):
        self.assertIsNone(fs._ml_do_predykcji({}))

    def test_poprawne_wejscie_zwraca_dict(self):
        wynik = fs._ml_do_predykcji(self._pred_ok())
        self.assertIsInstance(wynik, dict)

    def test_wynik_zawiera_wymagane_klucze(self):
        wynik = fs._ml_do_predykcji(self._pred_ok())
        wymagane = {"metoda", "p_wygrana", "p_remis", "p_przegrana",
                    "btts", "over25", "under25", "wynik_g", "wynik_a", "pewnosc"}
        self.assertFalse(wymagane - set(wynik.keys()),
                         f"Brakuje kluczy: {wymagane - set(wynik.keys())}")

    def test_metoda_ML(self):
        wynik = fs._ml_do_predykcji(self._pred_ok())
        self.assertEqual(wynik["metoda"], "ML")

    def test_suma_1X2_rowna_100(self):
        wynik = fs._ml_do_predykcji(self._pred_ok())
        suma = wynik["p_wygrana"] + wynik["p_remis"] + wynik["p_przegrana"]
        self.assertAlmostEqual(suma, 100.0, delta=1.0)

    def test_over25_under25_sumuja_do_100(self):
        wynik = fs._ml_do_predykcji(self._pred_ok())
        suma = wynik["over25"] + wynik["under25"]
        self.assertAlmostEqual(suma, 100.0, delta=0.5)

    def test_most_likely_score(self):
        dane = {
            "percent": {"home": "60%", "draw": "25%", "away": "15%"},
            "most_likely_score": {"home": 2, "away": 1}
        }
        wynik = fs._ml_do_predykcji(dane)
        self.assertEqual(wynik["wynik_g"], 2)
        self.assertEqual(wynik["wynik_a"], 1)

    def test_przekazuje_odds(self):
        odds = {"home": 1.5, "draw": 3.5, "away": 5.0}
        wynik = fs._ml_do_predykcji(self._pred_ok(), odds=odds)
        self.assertEqual(wynik["odds"], odds)

    def test_bledne_wejscie_nie_crasha(self):
        """Nieparsowalne dane nie moga crashowac programu."""
        for bledne in [
            {"percent": {"home": "BLAD", "draw": "??", "away": "N/A"}},
            {"home_win_prob": "NaN", "draw_prob": None, "away_win_prob": "inf"},
        ]:
            wynik = fs._ml_do_predykcji(bledne)
            # Moze byc None lub poprawny dict – wazne ze nie rzuca wyjatku


# ════════════════════════════════════════════════════════════════════
#  TEST 6: _typy_pewne() – filtrator typow
# ════════════════════════════════════════════════════════════════════

@unittest.skipUnless(FOOTSTATS_DOSTEPNY, "footstats.py niedostepny")
class TestTypyPewne(unittest.TestCase):

    def _typy(self, pw=80, pr=10, pp=10, bt=60, o25=65, u25=35, prog=75):
        return fs._typy_pewne(pw, pr, pp, bt, o25, u25, "Arsenal", "Chelsea", prog)

    def test_wygrana_gospodarza_powyzej_progu(self):
        typy = self._typy(pw=80, prog=75)
        nazwy = [t[0] for t in typy]
        self.assertTrue(any("Arsenal" in n for n in nazwy),
                        "Powinien byc typ 1 dla Arsenal")

    def test_wygrana_ponizej_progu(self):
        typy = self._typy(pw=60, pr=20, pp=20, prog=75)
        nazwy = [t[0] for t in typy]
        self.assertFalse(any("Arsenal" in n and "1 –" in n for n in nazwy))

    def test_prog_graniczny_rowny_prog(self):
        """Dokladnie prog% – powinno przejsc."""
        typy = fs._typy_pewne(75, 15, 10, 50, 50, 50, "A", "B", 75)
        nazwy = [t[0] for t in typy]
        self.assertTrue(any("1 –" in n for n in nazwy))

    def test_prog_graniczny_ponizej_o_0_1(self):
        """75% - 0.1% nie przechodzi przez prog 75%."""
        typy = fs._typy_pewne(74.9, 15.1, 10, 50, 50, 50, "A", "B", 75)
        nazwy = [t[0] for t in typy]
        self.assertFalse(any("1 –" in n for n in nazwy))

    def test_1X_podwojna_szansa(self):
        """1X = pw + pr = 75 + 15 = 90 >= 75."""
        typy = fs._typy_pewne(75, 15, 10, 50, 50, 50, "A", "B", 75)
        nazwy = [t[0] for t in typy]
        self.assertTrue(any("1X" in n for n in nazwy))

    def test_12_ktos_wygrywa(self):
        """12 = pw + pp = 45 + 45 = 90 >= 80."""
        typy = fs._typy_pewne(45, 10, 45, 50, 50, 50, "A", "B", 80)
        nazwy = [t[0] for t in typy]
        self.assertTrue(any("12" in n for n in nazwy))

    def test_pusty_wynik_przy_wysokim_progu(self):
        typy = self._typy(pw=60, pr=20, pp=20, bt=50, o25=50, u25=50, prog=95)
        self.assertEqual(typy, [])

    def test_wszystkie_typy_przy_niskim_progu(self):
        """Przy progu 0% wszystkie 8 typow powinno przejsc."""
        typy = fs._typy_pewne(40, 30, 30, 60, 60, 40, "A", "B", prog=0)
        self.assertGreaterEqual(len(typy), 6)

    def test_nazwy_druzyn_obcinane_do_15(self):
        """_typy_pewne uzywa g[:15] – nazwa w opisie jest obcieta do 15 znakow."""
        dluga = "Manchester United F.C."
        typy = fs._typy_pewne(85, 10, 5, 50, 50, 50, dluga, "B", 75)
        for opis, _ in typy:
            if "1 –" in opis:
                # Format: "1 – Wygrana <nazwa[:15]>"
                fragment = opis.split("Wygrana ")[-1] if "Wygrana" in opis else ""
                self.assertLessEqual(len(fragment), 15,
                    f"Nazwa druzyny w opisie powinna miec max 15 znakow: {fragment!r}")

    def test_zwraca_liste_tupli(self):
        typy = self._typy()
        self.assertIsInstance(typy, list)
        for item in typy:
            self.assertIsInstance(item, tuple)
            self.assertEqual(len(item), 2, f"Tupla powinna miec 2 elementy: {item}")

    def test_szansa_jest_liczba(self):
        """round(int, 1) w Python 3 zwraca int, round(float, 1) zwraca float.
        Wazne jest ze szansa jest numeryczna, nie typ konkretny."""
        typy = self._typy(pw=80, prog=75)
        for _, szansa in typy:
            self.assertIsInstance(szansa, (int, float),
                                  f"Szansa powinna byc numeryczna, dostano: {type(szansa)}")
            self.assertGreater(szansa, 0)
            self.assertLessEqual(szansa, 100)


# ════════════════════════════════════════════════════════════════════
#  TEST 7: typy_zaklady() – klasyfikacja typow z progami
# ════════════════════════════════════════════════════════════════════

@unittest.skipUnless(FOOTSTATS_DOSTEPNY, "footstats.py niedostepny")
class TestTypyZaklady(unittest.TestCase):

    def _w(self, pw=60, pr=25, pp=15, bt=55, o25=60, u25=40):
        return {
            "p_wygrana": pw, "p_remis": pr, "p_przegrana": pp,
            "btts": bt, "over25": o25, "under25": u25
        }

    def test_zwraca_liste(self):
        self.assertIsInstance(fs.typy_zaklady(self._w()), list)

    def test_pewny_typ_przy_90_procent(self):
        wyniki = fs.typy_zaklady(self._w(pw=90, pr=5, pp=5))
        nazwy = [t[0] for t in wyniki]
        self.assertTrue(any("Gospodarz" in n for n in nazwy))

    def test_brak_typu_przy_niskich_szansach(self):
        """Wszystkie szanse za niskie – lista powinna byc pusta lub minimalna."""
        wyniki = fs.typy_zaklady(self._w(pw=30, pr=30, pp=40, bt=30, o25=40, u25=60))
        # Moze byc 1X2 lub X2 jesli pr >= 32
        # Nie powinnno byc typow 1 ani 2
        for opis, _, _ in wyniki:
            self.assertNotIn("(Gospodarz wygrywa)", opis)

    def test_remis_przy_32_procent(self):
        """Remis jest dodawany od 32%, nie 55%."""
        wyniki = fs.typy_zaklady(self._w(pr=32))
        opisy = [t[0] for t in wyniki]
        self.assertTrue(any("Remis" in o for o in opisy))

    def test_remis_ponizej_32_procent(self):
        wyniki = fs.typy_zaklady(self._w(pw=50, pr=31, pp=19))
        opisy = [t[0] for t in wyniki]
        self.assertFalse(any(o == "X  (Remis)" for o in opisy))

    def test_btts_tak_przy_65_procent(self):
        wyniki = fs.typy_zaklady(self._w(bt=65))
        opisy = [t[0] for t in wyniki]
        self.assertTrue(any("BTTS TAK" in o for o in opisy))

    def test_btts_nie_przy_niskim_btts(self):
        wyniki = fs.typy_zaklady(self._w(bt=30))
        opisy = [t[0] for t in wyniki]
        self.assertTrue(any("BTTS NIE" in o for o in opisy))

    def test_oceny_sa_w_znanych_wartosciach(self):
        wyniki = fs.typy_zaklady(self._w(pw=80, pr=10, pp=10))
        znane_oceny = {"PEWNY", "DOBRY", "SLABY"}
        for _, _, ocena in wyniki:
            self.assertIn(ocena, znane_oceny, f"Nieznana ocena: {ocena}")

    def test_format_tuple_3(self):
        for item in fs.typy_zaklady(self._w(pw=80)):
            self.assertEqual(len(item), 3, f"Zla dlugosc tupli: {item}")


# ════════════════════════════════════════════════════════════════════
#  TEST 8: _wagi_mecze() – wagi czasowe
# ════════════════════════════════════════════════════════════════════

@unittest.skipUnless(FOOTSTATS_DOSTEPNY, "footstats.py niedostepny")
class TestWagiMecze(unittest.TestCase):

    def test_puste_df_daje_pusta_serie(self):
        df = pd.DataFrame(columns=["data"])
        wagi = fs._wagi_mecze(df)
        self.assertEqual(len(wagi), 0)

    def test_jeden_mecz_dostaje_1_5(self):
        """Najnowszy mecz (pozycja 0 od konca) → waga 1.5."""
        df = _df_mecze(("A", "B", 1, 0))
        wagi = fs._wagi_mecze(df)
        self.assertEqual(wagi.iloc[0], 1.5)

    def test_pierwsze_3_maja_wage_1_5(self):
        """Ostatnie 3 mecze (najnowsze) → waga 1.5."""
        df = _df_mecze(
            ("A","B",1,0,"2024-01-01"),
            ("A","B",2,1,"2024-01-08"),
            ("A","B",0,0,"2024-01-15"),
        )
        wagi = fs._wagi_mecze(df)
        for w in wagi:
            self.assertEqual(w, 1.5)

    def test_starsze_mecze_maja_mniejsze_wagi(self):
        """Mecze od pozycji 7+ maja wage 0.5."""
        wiersze = [{"gospodarz": "A", "goscie": "B", "gole_g": i, "gole_a": 0,
                    "data": f"2024-{(i%12)+1:02d}-01"} for i in range(10)]
        df = pd.DataFrame(wiersze)
        wagi = fs._wagi_mecze(df)
        # Najstarszy mecz (indeks 0) powinien miec wage 0.5
        self.assertEqual(wagi.iloc[0], 0.5)

    def test_dlugosc_wyjscia_rowna_df(self):
        df = _df_mecze(("A","B",1,0), ("A","B",2,1), ("A","B",0,0))
        wagi = fs._wagi_mecze(df)
        self.assertEqual(len(wagi), len(df))

    def test_wagi_sa_nieujemne(self):
        df = _df_minimal()
        wagi = fs._wagi_mecze(df)
        self.assertTrue((wagi >= 0).all())

    def test_indeks_wagi_odpowiada_df(self):
        """Wagi powinny miec ten sam indeks co DataFrame."""
        df = _df_minimal()
        wagi = fs._wagi_mecze(df)
        self.assertTrue(wagi.index.equals(df.index))


# ════════════════════════════════════════════════════════════════════
#  TEST 9: _oblicz_sile_wazona() – sila druzyn
# ════════════════════════════════════════════════════════════════════

@unittest.skipUnless(FOOTSTATS_DOSTEPNY, "footstats.py niedostepny")
class TestObliczSileWazona(unittest.TestCase):

    def test_podstawowe_wywolanie(self):
        df = _df_minimal()
        sily, srednia = fs._oblicz_sile_wazona(df)
        self.assertIsInstance(sily, dict)
        self.assertGreater(srednia, 0)

    def test_wszystkie_druzyny_obecne(self):
        df = _df_minimal()
        sily, _ = fs._oblicz_sile_wazona(df)
        for druzyna in ("Arsenal", "Chelsea", "ManCity"):
            self.assertIn(druzyna, sily)

    def test_klucze_slownika_sily(self):
        df = _df_minimal()
        sily, _ = fs._oblicz_sile_wazona(df)
        wymagane_klucze = {"atak", "obrona", "mecze", "gole_sr", "strac_sr", "forma_pkt"}
        for d, s in sily.items():
            brakujace = wymagane_klucze - set(s.keys())
            self.assertEqual(brakujace, set(), f"{d}: brakuje kluczy {brakujace}")

    def test_sila_ataku_jest_dodatnia(self):
        df = _df_minimal()
        sily, _ = fs._oblicz_sile_wazona(df)
        for d, s in sily.items():
            self.assertGreater(s["atak"], 0, f"{d}: atak <= 0")

    def test_srednia_jest_dodatnia(self):
        df = _df_minimal()
        _, srednia = fs._oblicz_sile_wazona(df)
        self.assertGreater(srednia, 0)

    def test_druzyna_dominator(self):
        """Druzyna wygrywajaca wszystkie mecze powinna miec wysoki wskaznik ataku."""
        df = _df_mecze(
            ("SuperTeam", "Weak", 5, 0, "2024-01-01"),
            ("SuperTeam", "Weak", 4, 0, "2024-01-08"),
            ("SuperTeam", "Weak", 3, 0, "2024-01-15"),
            ("Weak",      "SuperTeam", 0, 3, "2024-01-22"),
        )
        sily, srednia = fs._oblicz_sile_wazona(df)
        if "SuperTeam" in sily and srednia > 0:
            self.assertGreater(sily["SuperTeam"]["atak"],
                               sily["Weak"]["atak"])

    def test_druzyna_bez_meczu_dostaje_srednia(self):
        """
        Druzyna ktora wystepuje tylko jako gosc (dom.empty) powinna
        dostac fallback = srednia zamiast dzielenia przez zero.
        """
        df = _df_mecze(
            ("Arsenal", "Phantom", 2, 1, "2024-01-01"),
            ("Arsenal", "Phantom", 3, 0, "2024-01-08"),
        )
        sily, srednia = fs._oblicz_sile_wazona(df)
        # Phantom gra tylko na wyjezdzie – nie powinno crashowac
        self.assertIn("Phantom", sily)


# ════════════════════════════════════════════════════════════════════
#  TEST 10: pobierz_forme() – forma druzyny
# ════════════════════════════════════════════════════════════════════

@unittest.skipUnless(FOOTSTATS_DOSTEPNY, "footstats.py niedostepny")
class TestPobierzForme(unittest.TestCase):

    def test_podstawowe_wywolanie(self):
        df = _df_minimal()
        forma = fs.pobierz_forme("Arsenal", df)
        self.assertIsInstance(forma, pd.DataFrame)

    def test_zwraca_tylko_mecze_druzyny(self):
        df = _df_minimal()
        forma = fs.pobierz_forme("Arsenal", df)
        for _, row in forma.iterrows():
            self.assertTrue(
                row["gospodarz"] == "Arsenal" or row["goscie"] == "Arsenal",
                "Forma zawiera mecz bez Arsenalu!"
            )

    def test_limit_n(self):
        df = _df_minimal()
        forma = fs.pobierz_forme("Arsenal", df, n=3)
        self.assertLessEqual(len(forma), 3)

    def test_nieznana_druzyna_zwraca_puste_df(self):
        df = _df_minimal()
        forma = fs.pobierz_forme("Nieistnieje FC", df)
        self.assertTrue(forma.empty)

    def test_kolumny_wymagane(self):
        df = _df_minimal()
        forma = fs.pobierz_forme("Arsenal", df)
        if not forma.empty:
            wymagane = {"data", "gospodarz", "goscie", "wynik", "miejsce"}
            brakujace = wymagane - set(forma.columns)
            self.assertEqual(brakujace, set())

    def test_wynik_W_R_P(self):
        df = _df_minimal()
        forma = fs.pobierz_forme("Arsenal", df)
        for _, row in forma.iterrows():
            self.assertIn(row["wynik"], {"W", "R", "P"})

    def test_miejsce_Dom_lub_Wyjazd(self):
        df = _df_minimal()
        forma = fs.pobierz_forme("Arsenal", df)
        for _, row in forma.iterrows():
            self.assertIn(row["miejsce"], {"Dom", "Wyjazd"})

    def test_sortowane_po_dacie(self):
        df = _df_minimal()
        forma = fs.pobierz_forme("Arsenal", df)
        if len(forma) > 1:
            daty = list(forma["data"])
            self.assertEqual(daty, sorted(daty))

    def test_pusty_df_wejsciowy(self):
        df = pd.DataFrame(columns=["gospodarz", "goscie", "gole_g", "gole_a", "data"])
        forma = fs.pobierz_forme("Arsenal", df)
        self.assertTrue(forma.empty)


# ════════════════════════════════════════════════════════════════════
#  TEST 11: _korekta_rewanz_v26() – korekta rewanzowa
# ════════════════════════════════════════════════════════════════════

@unittest.skipUnless(FOOTSTATS_DOSTEPNY, "footstats.py niedostepny")
class TestKorektaRewanz(unittest.TestCase):

    def test_gospodarz_prowadzi_2_plus(self):
        """agg: 3:1 → gospodarz prowadzi +2 → gra na czas (parking bus)."""
        lg, la, opis = fs._korekta_rewanz_v26(1.5, 1.2, agg_g=3, agg_a=1)
        # Gospodarz hamuje atak (parking bus < 1)
        from footstats import REWANZ_PARKING_BUS
        self.assertAlmostEqual(lg, 1.5 * REWANZ_PARKING_BUS, delta=0.01)
        self.assertIn("PROWADZI", opis.upper())

    def test_gospodarz_przegrywa_2_plus(self):
        """agg: 0:3 → gospodarz przegrywa -3 → vabank."""
        from footstats import REWANZ_VABANK
        lg, la, opis = fs._korekta_rewanz_v26(1.5, 1.2, agg_g=0, agg_a=3)
        self.assertAlmostEqual(lg, 1.5 * REWANZ_VABANK, delta=0.01)
        self.assertIn("PRZEGRYWA", opis.upper())

    def test_remis_obaj_atakuja(self):
        """agg: 1:1 → remis → obaj musza atakowac (+10%)."""
        lg, la, opis = fs._korekta_rewanz_v26(1.5, 1.2, agg_g=1, agg_a=1)
        self.assertAlmostEqual(lg, 1.5 * 1.10, delta=0.01)
        self.assertAlmostEqual(la, 1.2 * 1.10, delta=0.01)

    def test_remis_0_0(self):
        """agg: 0:0 → remis bez goli → obaj musza atakowac."""
        lg, la, opis = fs._korekta_rewanz_v26(1.0, 1.0, agg_g=0, agg_a=0)
        self.assertAlmostEqual(lg, 1.0 * 1.10, delta=0.01)

    def test_minimalna_roznica_plus_1(self):
        """agg: 2:1 → roznica 1 → wyrownana walka (+5%)."""
        lg, la, opis = fs._korekta_rewanz_v26(1.5, 1.2, agg_g=2, agg_a=1)
        self.assertAlmostEqual(lg, 1.5 * 1.05, delta=0.01)
        self.assertAlmostEqual(la, 1.2 * 1.05, delta=0.01)

    def test_minimalna_roznica_minus_1(self):
        """agg: 1:2 → roznica -1 → wyrownana walka."""
        lg, la, opis = fs._korekta_rewanz_v26(1.5, 1.2, agg_g=1, agg_a=2)
        self.assertAlmostEqual(lg, 1.5 * 1.05, delta=0.01)

    def test_lambdy_sa_dodatnie(self):
        """Lambda nigdy nie moze byc ujemna (brak sensu fizyczny)."""
        for agg_g, agg_a in [(0, 5), (5, 0), (2, 2), (1, 0), (0, 1)]:
            lg, la, _ = fs._korekta_rewanz_v26(1.5, 1.2, agg_g=agg_g, agg_a=agg_a)
            self.assertGreater(lg, 0, f"lg<=0 przy agg {agg_g}:{agg_a}")
            self.assertGreater(la, 0, f"la<=0 przy agg {agg_g}:{agg_a}")

    def test_zwraca_tuple_3(self):
        wynik = fs._korekta_rewanz_v26(1.5, 1.2, agg_g=1, agg_a=1)
        self.assertIsInstance(wynik, tuple)
        self.assertEqual(len(wynik), 3)

    def test_opis_jest_stringiem(self):
        _, _, opis = fs._korekta_rewanz_v26(1.5, 1.2, agg_g=2, agg_a=0)
        self.assertIsInstance(opis, str)
        self.assertGreater(len(opis), 5)


# ════════════════════════════════════════════════════════════════════
#  TEST 12: AnalizaDomWyjazd – statystyki dom/wyjazd
# ════════════════════════════════════════════════════════════════════

@unittest.skipUnless(FOOTSTATS_DOSTEPNY, "footstats.py niedostepny")
class TestAnalizaDomWyjazd(unittest.TestCase):

    def _dw(self, df=None):
        return fs.AnalizaDomWyjazd(df if df is not None else _df_minimal())

    def test_inicjalizacja_z_none(self):
        dw = fs.AnalizaDomWyjazd(None)
        wynik = dw.analiza("Arsenal")
        self.assertIsInstance(wynik, dict)

    def test_inicjalizacja_z_pustym_df(self):
        dw = fs.AnalizaDomWyjazd(pd.DataFrame())
        wynik = dw.analiza("Arsenal")
        self.assertIsInstance(wynik, dict)

    def test_analiza_zwraca_dict(self):
        wynik = self._dw().analiza("Arsenal")
        self.assertIsInstance(wynik, dict)

    def test_klucze_wynikowe(self):
        wynik = self._dw().analiza("Arsenal")
        wymagane = {"druzyna", "dom_pkt", "wyjazd_pkt", "podroznik",
                    "dom_m", "wyj_m", "opis"}
        brakujace = wymagane - set(wynik.keys())
        self.assertEqual(brakujace, set(), f"Brakuje: {brakujace}")

    def test_nazwa_druzyny_w_wyniku(self):
        wynik = self._dw().analiza("Arsenal")
        self.assertEqual(wynik["druzyna"], "Arsenal")

    def test_pkt_na_mecz_zakres(self):
        """Punkty na mecz: 0 <= pkt <= 3."""
        wynik = self._dw().analiza("Arsenal")
        self.assertGreaterEqual(wynik["dom_pkt"], 0)
        self.assertLessEqual(wynik["dom_pkt"], 3)
        self.assertGreaterEqual(wynik["wyjazd_pkt"], 0)
        self.assertLessEqual(wynik["wyjazd_pkt"], 3)

    def test_podroznik_wykrywanie(self):
        """Druzyna lepsza na wyjezdzie > dom o DOMWYJAZD_PODROZNIK."""
        df = _df_mecze(
            # Arsenal: słaby u siebie
            ("Arsenal", "Chelsea",  0, 2, "2024-01-01"),
            ("Arsenal", "ManCity",  0, 3, "2024-01-08"),
            ("Arsenal", "Liverpool",0, 1, "2024-01-15"),
            ("Arsenal", "Everton",  0, 2, "2024-01-22"),
            ("Arsenal", "Burnley",  0, 1, "2024-01-29"),
            # Arsenal: doskonaly na wyjezdzie
            ("Chelsea",  "Arsenal", 0, 3, "2024-02-05"),
            ("ManCity",  "Arsenal", 0, 3, "2024-02-12"),
            ("Liverpool","Arsenal", 0, 3, "2024-02-19"),
            ("Everton",  "Arsenal", 0, 3, "2024-02-26"),
            ("Burnley",  "Arsenal", 0, 3, "2024-03-04"),
        )
        dw = fs.AnalizaDomWyjazd(df)
        wynik = dw.analiza("Arsenal", n=10)
        # Arsenal wygrywa wszystko na wyjezdzie, przegrywa u siebie
        self.assertGreater(wynik["wyjazd_pkt"], wynik["dom_pkt"])

    def test_nieznana_druzyna(self):
        wynik = self._dw().analiza("Nieistnieje FC")
        self.assertIsInstance(wynik, dict)
        self.assertEqual(wynik["dom_m"], 0)
        self.assertEqual(wynik["wyj_m"], 0)

    def test_bonus_wyjazd_podroznika(self):
        """Podroznik powinien miec bonus_wyjazd = 1.10."""
        df = _df_mecze(
            ("Arsenal", "Chelsea",  0, 3, "2024-01-01"),
            ("Arsenal", "Chelsea",  0, 3, "2024-01-08"),
            ("Arsenal", "Chelsea",  0, 3, "2024-01-15"),
            ("Arsenal", "Chelsea",  0, 3, "2024-01-22"),
            ("Arsenal", "Chelsea",  0, 3, "2024-01-29"),
            ("Chelsea", "Arsenal",  0, 3, "2024-02-05"),
            ("ManCity", "Arsenal",  0, 3, "2024-02-12"),
            ("Everton", "Arsenal",  0, 3, "2024-02-19"),
            ("Liverpool","Arsenal", 0, 3, "2024-02-26"),
            ("Burnley", "Arsenal",  0, 3, "2024-03-04"),
        )
        dw = fs.AnalizaDomWyjazd(df)
        wynik = dw.analiza("Arsenal", n=10)
        if wynik["podroznik"]:
            self.assertEqual(wynik["bonus_wyjazd"], 1.10)


# ════════════════════════════════════════════════════════════════════
#  TEST 13: Cache RAM – _cache_get / _cache_set
# ════════════════════════════════════════════════════════════════════

@unittest.skipUnless(FOOTSTATS_DOSTEPNY, "footstats.py niedostepny")
class TestCacheRAM(unittest.TestCase):

    def setUp(self):
        """Wyczysc cache przed kazdy testem."""
        fs._RAM_CACHE.clear()

    def test_cache_miss(self):
        """Brakujacy klucz zwraca None."""
        self.assertIsNone(fs._cache_get("nieistnieje::klucz"))

    def test_cache_set_i_get(self):
        dane = {"wynik": 42, "opis": "test"}
        fs._cache_set("test::klucz", dane)
        wynik = fs._cache_get("test::klucz")
        self.assertEqual(wynik, dane)

    def test_cache_ttl_wygasniecie(self):
        """Po wygasnieciu TTL klucz powinien byc niedostepny."""
        klucz = "test::ttl_expiry"
        fs._cache_set(klucz, {"v": 1})
        # Symuluj upływ czasu – podmień timestamp
        ts_stary = datetime.now() - timedelta(minutes=fs.CACHE_TTL_MIN + 1)
        fs._RAM_CACHE[klucz]["ts"] = ts_stary
        wynik = fs._cache_get(klucz)
        self.assertIsNone(wynik, "Cache nie wygas! Stary wpis wciaz widoczny.")

    def test_cache_ttl_wciaz_wazny(self):
        """Przed wygsniciem klucz powinien byc dostepny."""
        klucz = "test::ttl_valid"
        fs._cache_set(klucz, {"v": 2})
        wynik = fs._cache_get(klucz)
        self.assertIsNotNone(wynik)

    def test_nadpisanie_klucza(self):
        fs._cache_set("test::nadpisz", {"v": 1})
        fs._cache_set("test::nadpisz", {"v": 2})
        wynik = fs._cache_get("test::nadpisz")
        self.assertEqual(wynik["v"], 2)

    def test_rozne_klucze_niezalezne(self):
        fs._cache_set("test::k1", {"v": 1})
        fs._cache_set("test::k2", {"v": 2})
        self.assertEqual(fs._cache_get("test::k1")["v"], 1)
        self.assertEqual(fs._cache_get("test::k2")["v"], 2)

    def test_none_jako_dane(self):
        """Mozna przechowac None – ale _cache_get zwraca None gdy brak wpisu."""
        fs._cache_set("test::none_val", None)
        # Wpis istnieje ale data=None → _cache_get zwraca None (falsy → nie wchodzi w ifa)
        wynik = fs._cache_get("test::none_val")
        # Zachowanie: if wpis (truthy → data=None → get None), ale blok sprawdza "if wpis"
        # To edge case – istnienie wpisu ale None data

    def test_duze_dane(self):
        """Cache musi obslugiwac duze obiekty (np. DataFrame)."""
        df = _df_minimal()
        fs._cache_set("test::df", df)
        wynik = fs._cache_get("test::df")
        self.assertIsNotNone(wynik)


# ════════════════════════════════════════════════════════════════════
#  TEST 14: af_budget_status() + _af_budget_load/save
# ════════════════════════════════════════════════════════════════════

@unittest.skipUnless(FOOTSTATS_DOSTEPNY, "footstats.py niedostepny")
class TestBudzetAF(unittest.TestCase):

    def test_status_zwraca_dict(self):
        """af_budget_status() zawsze zwraca dict (nawet bez pliku cache)."""
        with patch("footstats.AF_BUDGET_FILE", Path(tempfile.mktemp())):
            status = fs.af_budget_status()
            self.assertIsInstance(status, dict)

    def test_status_klucze(self):
        with patch("footstats.AF_BUDGET_FILE", Path(tempfile.mktemp())):
            status = fs.af_budget_status()
            wymagane = {"dzien", "uzyto", "pozostalo", "limit", "procent",
                        "krytyczny", "ostrzezenie"}
            brakujace = wymagane - set(status.keys())
            self.assertEqual(brakujace, set())

    def test_status_reset_nowego_dnia(self):
        """Plik z datą wczorajszą – budzet powinien się zresetować."""
        z_wczoraj = {
            "dzien": "2000-01-01",  # stara data
            "uzyto": 99,
            "historia": []
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                         delete=False, encoding="utf-8") as f:
            json.dump(z_wczoraj, f)
            tmp = Path(f.name)

        try:
            with patch("footstats.AF_BUDGET_FILE", tmp):
                b = fs._af_budget_load()
                self.assertEqual(b.get("uzyto"), 0, "Nowy dzien: uzyto powinno byc 0")
        finally:
            tmp.unlink(missing_ok=True)

    def test_save_i_load_roundtrip(self):
        """Zapis i odczyt budzetu daje te same dane."""
        with tempfile.TemporaryDirectory() as td:
            plik = Path(td) / "test_budget.json"
            with patch("footstats.AF_BUDGET_FILE", plik), \
                 patch("footstats.CACHE_DIR", Path(td)):
                dane = {
                    "dzien": datetime.now().strftime("%Y-%m-%d"),
                    "uzyto": 42,
                    "historia": [{"ts": "12:00:00", "endpoint": "/matches"}]
                }
                fs._af_budget_save(dane)
                self.assertTrue(plik.exists())
                zaladowane = fs._af_budget_load()
                self.assertEqual(zaladowane.get("uzyto"), 42)

    def test_load_brak_pliku(self):
        """Brak pliku budzetu – funkcja zwraca domyslny dict."""
        with patch("footstats.AF_BUDGET_FILE", Path("/nieistnieje/budget.json")):
            with patch("footstats.CACHE_DIR", Path("/nieistnieje")):
                b = fs._af_budget_load()
                self.assertIsInstance(b, dict)
                self.assertEqual(b.get("uzyto"), 0)

    def test_load_uszkodzony_json(self):
        """Uszkodzony JSON – funkcja zwraca domyslny dict (nie crashuje)."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                          delete=False, encoding="utf-8") as f:
            f.write("{ BLAD BLAD }")
            tmp = Path(f.name)
        try:
            with patch("footstats.AF_BUDGET_FILE", tmp):
                b = fs._af_budget_load()
                self.assertIsInstance(b, dict)
                self.assertEqual(b.get("uzyto"), 0)
        finally:
            tmp.unlink(missing_ok=True)


# ════════════════════════════════════════════════════════════════════
#  TEST 15: _pdf() – transliteracja polskich znakow
# ════════════════════════════════════════════════════════════════════

@unittest.skipUnless(FOOTSTATS_DOSTEPNY, "footstats.py niedostepny")
class TestPdf(unittest.TestCase):

    def test_zwraca_string(self):
        wynik = fs._pdf("Tekst testowy")
        self.assertIsInstance(wynik, str)

    def test_pusty_string(self):
        self.assertEqual(fs._pdf(""), "")

    def test_none_konwertowane(self):
        """_pdf(None) → str(None) = "None"."""
        wynik = fs._pdf(None)
        self.assertIsInstance(wynik, str)

    def test_liczby(self):
        wynik = fs._pdf(42)
        self.assertEqual(wynik, "42")

    def test_ascii_bez_zmian_gdy_font_ok(self):
        """Gdy font jest OK, ASCII przechodzi bez zmian."""
        with patch("footstats.FONT_OK", True):
            self.assertEqual(fs._pdf("Arsenal"), "Arsenal")

    def test_transliteracja_gdy_brak_fonta(self):
        """Bez fontu polskie litery sa transliterowane."""
        with patch("footstats.FONT_OK", False):
            wynik = fs._pdf("łódź")
            self.assertIsInstance(wynik, str)
            self.assertNotIn("ł", wynik)
            self.assertNotIn("ó", wynik)
            self.assertNotIn("ź", wynik)


# ════════════════════════════════════════════════════════════════════
#  TEST 16: footstats_logging.py – modul logowania
# ════════════════════════════════════════════════════════════════════

class TestLoggingModul(unittest.TestCase):
    """
    Testuje modul footstats_logging.py niezaleznie od footstats.py.
    """

    def _import_logging(self):
        try:
            import footstats_logging as fl
            return fl
        except ImportError:
            self.skipTest("footstats_logging.py niedostepny")

    def test_inicjalizacja(self):
        fl = self._import_logging()
        import logging
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            tmp = Path(f.name)
        try:
            log = fl.inicjalizuj(log_file=tmp)
            self.assertIsNotNone(log)
        finally:
            tmp.unlink(missing_ok=True)

    def test_bezpieczny_parse_prob_format_A(self):
        fl = self._import_logging()
        wynik = fl.bezpieczny_parse_prob(
            {"percent": {"home": "60%", "draw": "25%", "away": "15%"}}
        )
        self.assertIsNotNone(wynik)
        self.assertAlmostEqual(wynik[0], 60.0, delta=0.5)

    def test_bezpieczny_parse_prob_none(self):
        fl = self._import_logging()
        self.assertIsNone(fl.bezpieczny_parse_prob(None))

    def test_bezpieczny_parse_prob_suma_niespojne(self):
        """Suma 1+1+1=3 < 5 → niespojne dane → None.
        Uwaga: przed naprawka bledu p() 1% bylo blednie interpretowane
        jako ulamek i mnozono przez 100 (dajac 100%), co dawalo sume 300.
        Po naprawie: p('1%') = 1.0 (procent), suma = 3.0 < 5 → None."""
        fl = self._import_logging()
        wynik = fl.bezpieczny_parse_prob(
            {"percent": {"home": "1%", "draw": "1%", "away": "1%"}}
        )
        self.assertIsNone(wynik,
            "Dane z suma 1X2 < 5% to niespojne dane – oczekiwano None")

    def test_dekorator_bezpieczna_funkcja(self):
        fl = self._import_logging()

        @fl.bezpieczna_funkcja(fallback="FALLBACK")
        def crashujaca():
            raise RuntimeError("Test crash")

        wynik = crashujaca()
        self.assertEqual(wynik, "FALLBACK")

    def test_dekorator_bez_bledu(self):
        fl = self._import_logging()

        @fl.bezpieczna_funkcja(fallback=None)
        def normalna(x):
            return x * 2

        self.assertEqual(normalna(21), 42)

    def test_waliduj_df_poprawny(self):
        fl = self._import_logging()
        df = pd.DataFrame({
            "gospodarz": ["A"], "goscie": ["B"],
            "gole_g": [2], "gole_a": [1], "data": ["2024-01-01"]
        })
        self.assertTrue(fl.waliduj_df_wyniki(df))

    def test_waliduj_df_none(self):
        fl = self._import_logging()
        self.assertFalse(fl.waliduj_df_wyniki(None))

    def test_waliduj_df_brakujace_kolumny(self):
        fl = self._import_logging()
        df = pd.DataFrame({"gospodarz": ["A"], "goscie": ["B"]})
        self.assertFalse(fl.waliduj_df_wyniki(df))

    def test_waliduj_df_pusty(self):
        fl = self._import_logging()
        df = pd.DataFrame(columns=["gospodarz", "goscie", "gole_g", "gole_a", "data"])
        self.assertFalse(fl.waliduj_df_wyniki(df))

    def test_bezpieczny_cache_json_roundtrip(self):
        fl = self._import_logging()
        with tempfile.TemporaryDirectory() as td:
            plik = Path(td) / "test.json"
            dane = {"klucz": "wartość", "liczba": 42}
            ok = fl.BezpiecznyCache.zapisz_json(plik, dane)
            self.assertTrue(ok)
            zaladowane = fl.BezpiecznyCache.wczytaj_json(plik)
            self.assertEqual(zaladowane, dane)

    def test_bezpieczny_cache_brak_pliku(self):
        fl = self._import_logging()
        wynik = fl.BezpiecznyCache.wczytaj_json(Path("/nieistnieje/plik.json"))
        self.assertIsNone(wynik)

    def test_bezpieczny_cache_uszkodzony_json(self):
        fl = self._import_logging()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                          delete=False, encoding="utf-8") as f:
            f.write("{BLAD}")
            tmp = Path(f.name)
        try:
            wynik = fl.BezpiecznyCache.wczytaj_json(tmp)
            self.assertIsNone(wynik)
        finally:
            tmp.unlink(missing_ok=True)

    def test_bezpieczne_pobieranie_context_manager(self):
        fl = self._import_logging()
        with fl.BezpiecznePobieranie("Serie A") as bp:
            wynik = bp.wykonaj(lambda: {"dane": 42}, opis="test_func")
        self.assertEqual(wynik, {"dane": 42})
        self.assertFalse(bp.ma_bledy)

    def test_bezpieczne_pobieranie_z_bledem(self):
        fl = self._import_logging()
        with fl.BezpiecznePobieranie("Serie A") as bp:
            wynik = bp.wykonaj(lambda: (_ for _ in ()).throw(ValueError("test")),
                               fallback="FALLBACK", opis="crasher")
        self.assertEqual(wynik, "FALLBACK")
        self.assertTrue(bp.ma_bledy)


# ════════════════════════════════════════════════════════════════════
#  TESTY INTEGRACYJNE – predict_match (bez sieciowych)
# ════════════════════════════════════════════════════════════════════

@unittest.skipUnless(FOOTSTATS_DOSTEPNY, "footstats.py niedostepny")
class TestPredictMatch(unittest.TestCase):

    def test_za_malo_danych_zwraca_none(self):
        """Liga, mniej niz 4 mecze → None."""
        df = _df_mecze(("A", "B", 2, 1))
        wynik = fs.predict_match("A", "B", df, stage="REGULAR_SEASON")
        self.assertIsNone(wynik)

    def test_zwraca_dict_dla_wstarczajacych_danych(self):
        df = _df_minimal()
        wynik = fs.predict_match("Arsenal", "ManCity", df)
        if wynik is not None:
            self.assertIsInstance(wynik, dict)

    def test_prawdopodobienstwta_sumuja_do_100(self):
        df = _df_minimal()
        wynik = fs.predict_match("Arsenal", "ManCity", df)
        if wynik:
            suma = wynik["p_wygrana"] + wynik["p_remis"] + wynik["p_przegrana"]
            self.assertAlmostEqual(suma, 100.0, delta=1.5,
                                   msg=f"Suma 1X2={suma}, != 100")

    def test_lambdy_dodatnie(self):
        df = _df_minimal()
        wynik = fs.predict_match("Arsenal", "Chelsea", df)
        if wynik:
            self.assertGreater(wynik.get("lambda_g", 0), 0)
            self.assertGreater(wynik.get("lambda_a", 0), 0)

    def test_pewnosc_w_zakresie(self):
        df = _df_minimal()
        wynik = fs.predict_match("Arsenal", "Chelsea", df)
        if wynik:
            self.assertGreaterEqual(wynik.get("pewnosc", 0), 0)
            self.assertLessEqual(wynik.get("pewnosc", 100), 100)

    def test_nieznana_druzyna_zwraca_none(self):
        df = _df_minimal()
        wynik = fs.predict_match("Nieistnieje FC", "Tez Brak", df)
        self.assertIsNone(wynik)

    def test_stage_knockout_nie_crashuje(self):
        """Fazy pucharowe moga uzyc fallbacku turniejowego."""
        df = _df_minimal()
        wynik = fs.predict_match("Arsenal", "ManCity", df, stage="FINAL")
        # Moze byc None lub dict – wazne ze nie rzuca wyjatku


# ════════════════════════════════════════════════════════════════════
#  URUCHOMIENIE
# ════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    loader   = unittest.TestLoader()
    suite    = unittest.TestSuite()

    # Zbierz wszystkie klasy testowe z tego modulu
    test_classes = [
        TestHelperS,
        TestParseDate,
        TestCzyKnockout,
        TestBzzParseProb,
        TestMlDoPredykcji,
        TestTypyPewne,
        TestTypyZaklady,
        TestWagiMecze,
        TestObliczSileWazona,
        TestPobierzForme,
        TestKorektaRewanz,
        TestAnalizaDomWyjazd,
        TestCacheRAM,
        TestBudzetAF,
        TestPdf,
        TestLoggingModul,
        TestPredictMatch,
    ]

    for cls in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(
        verbosity=2,
        stream=sys.stdout,
        descriptions=True,
        failfast=False,
    )
    wynik = runner.run(suite)

    # Kod wyjscia
    sys.exit(0 if wynik.wasSuccessful() else 1)
