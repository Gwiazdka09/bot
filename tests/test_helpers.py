"""Testy utils/helpers.py – _s() i _parse_date()."""
import math
import pytest
from footstats.utils.helpers import _s, _parse_date


class TestS:
    def test_none_zwraca_domyslna(self):
        assert _s(None) == "-"

    def test_none_custom_domyslna(self):
        assert _s(None, "N/A") == "N/A"

    def test_pusty_string(self):
        assert _s("") == "-"

    def test_string_ze_spacjami(self):
        assert _s("   ") == "-"

    def test_nan_float(self):
        assert _s(float("nan")) == "-"

    def test_nan_string(self):
        assert _s("nan") == "-"

    def test_none_string(self):
        assert _s("none") == "-"

    def test_null_string(self):
        assert _s("null") == "-"

    def test_poprawny_string(self):
        assert _s("Arsenal") == "Arsenal"

    def test_liczba_int(self):
        assert _s(42) == "42"

    def test_liczba_float(self):
        assert "3.14" in _s(3.14)

    def test_zero(self):
        assert _s(0) == "0"

    def test_false(self):
        assert _s(False) == "False"

    def test_string_z_bialymi_znakami(self):
        assert _s("  Arsenal  ") == "Arsenal"

    def test_lista(self):
        wynik = _s([1, 2, 3])
        assert isinstance(wynik, str)
        assert wynik != "-"


class TestParseDate:
    def test_format_iso_z_Z(self):
        w = _parse_date("2024-03-15T20:30:00Z")
        assert w is not None
        assert w.year == 2024
        assert w.month == 3
        assert w.day == 15
        assert w.hour == 20

    def test_format_iso_bez_Z(self):
        w = _parse_date("2024-03-15T20:30:00")
        assert w is not None
        assert w.hour == 20

    def test_format_sama_data(self):
        w = _parse_date("2024-03-15")
        assert w is not None
        assert w.day == 15

    def test_none_zwraca_none(self):
        assert _parse_date(None) is None

    def test_pusty_string(self):
        assert _parse_date("") is None

    def test_myslnik(self):
        assert _parse_date("-") is None

    def test_nan_string(self):
        assert _parse_date("nan") is None

    def test_bledny_format(self):
        assert _parse_date("15/03/2024") is None

    def test_bledna_data(self):
        assert _parse_date("2024-02-30") is None

    def test_stary_rok(self):
        w = _parse_date("1990-06-08")
        assert w is not None
        assert w.year == 1990

    def test_przyszla_data(self):
        w = _parse_date("2099-12-31")
        assert w is not None
        assert w.year == 2099
