"""
tests/test_pdf_export.py – Test eksportu PDF z polskimi znakami i czcionką DejaVuSans.

Weryfikuje:
1. Plik PDF fizycznie powstaje na dysku.
2. Czcionka PDF_FONT to "DejaVu" (DejaVuSans załadowany poprawnie).
3. FONT_OK == True (czcionka zarejestrowana, ogonki nie są zastępowane ASCII).
4. Eksport nie crashuje przy polskich znakach: ą, ę, ł, ó, ś, ź, ż, ń, ć.
"""
import os
import tempfile
from pathlib import Path

import pandas as pd
import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _wpis(gospodarz: str, goscie: str) -> dict:
    """Tworzy jeden wpis wyniki_kolejki w formacie oczekiwanym przez eksportuj_pdf."""
    mecz = {
        "gospodarz": gospodarz,
        "goscie":    goscie,
        "data":      "2026-04-20",
        "liga":      "Ekstraklasa",
    }
    predykcja = {
        # pola identyfikujące
        "gospodarz":   gospodarz,
        "gosc":        goscie,
        # prawdopodobieństwa
        "p_wygrana":   55.0,
        "p_remis":     27.0,
        "p_przegrana": 18.0,
        "wynik_g":     1,
        "wynik_a":     0,
        "btts":        42.0,
        "over25":      48.0,
        "under25":     52.0,
        "over15":      72.0,
        # Poisson
        "lambda_g":    1.45,
        "lambda_a":    0.92,
        "forma_g":     1.1,
        "forma_a":     0.9,
        # top5 typów (wymagane przez pdf.py linia 134)
        "top5":        [("1", 55), ("X", 27), ("2", 18), ("BTTS", 42), ("Over 2.5", 48)],
        # heurystyki
        "heur_g":      {"ikony": "", "opis": ""},
        "heur_a":      {"ikony": "", "opis": ""},
        "zemsta_g":    {"ikona": "", "opis": ""},
        "zemsta_a":    {"ikona": "", "opis": ""},
        "imp_g":       {"label_plain": "", "label": ""},
        "h2h_g":       {"ikona": ""},
        "h2h_a":       {"ikona": ""},
        "fort_g":      {"ikona": ""},
        # misc
        "pewnosc":     68,
        "single":      False,
    }
    klasyfikacja = {"etykieta_pdf": "[EKSTRA]", "etykieta": "[dim][EKSTRA][/dim]"}
    return {"mecz": mecz, "predykcja": predykcja, "klasyfikacja": klasyfikacja}


@pytest.fixture
def fikcyjne_wyniki() -> list[dict]:
    """Fikcyjne dane meczowe z polskimi znakami w nazwach drużyn i ligach."""
    return [
        _wpis("Łódź Athletic", "Świętosław FC"),
        _wpis("Górnik Zabrze", "Ząbkowicka Żyrafa"),
    ]


@pytest.fixture
def fikcyjna_tabela() -> pd.DataFrame:
    """Minimalna tabela ligowa z polskimi znakami."""
    # Kolumny muszą odpowiadać temu, czego oczekuje pdf.py (linia ~159)
    return pd.DataFrame(
        {
            "Poz.":    [1, 2, 3],
            "Druzyna": ["Łódź Athletic", "Górnik Zabrze", "Ząbkowicka Żyrafa"],
            "M":       [15, 15, 15],
            "W":       [9, 8, 7],
            "R":       [3, 4, 4],
            "P":       [3, 3, 4],
            "Bramki":  ["22:14", "19:15", "17:16"],
            "+/-":     [8, 4, 1],
            "Pkt":     [30, 28, 25],
        }
    )


# ── Testy czcionki ─────────────────────────────────────────────────────────────

def test_font_ok_true():
    """FONT_OK musi być True — DejaVuSans.ttf jest w assets/."""
    from footstats.export.pdf_font import FONT_OK
    assert FONT_OK is True, (
        "FONT_OK=False — DejaVuSans.ttf nie załadowany. "
        "Sprawdź czy plik istnieje w F:/bot/assets/DejaVuSans.ttf"
    )


def test_pdf_font_is_dejavu():
    """PDF_FONT musi wskazywać na DejaVu, nie Helvetica."""
    from footstats.export.pdf_font import PDF_FONT
    assert PDF_FONT == "DejaVu", (
        f"Oczekiwano PDF_FONT='DejaVu', otrzymano '{PDF_FONT}'. "
        "Czcionka nie jest zarejestrowana lub plik .ttf brakuje."
    )


def test_pdf_helper_preserves_polish():
    """_pdf() przy FONT_OK=True nie zmienia polskich znaków."""
    from footstats.export.pdf_font import _pdf, FONT_OK
    if not FONT_OK:
        pytest.skip("DejaVuSans niedostępny — pomijam test ogonków")
    tekst = "Łódź Athletic śpiewa ćwiczenia"
    assert _pdf(tekst) == tekst, "_pdf() nie powinno transliterować przy FONT_OK=True"


# ── Test eksportu pliku ────────────────────────────────────────────────────────

def test_pdf_file_generated(fikcyjne_wyniki, fikcyjna_tabela):
    """Eksport tworzy plik PDF o niezerowym rozmiarze."""
    from footstats.export.pdf import eksportuj_pdf

    with tempfile.TemporaryDirectory() as tmpdir:
        sciezka = os.path.join(tmpdir, "test_raport.pdf")
        wynik = eksportuj_pdf(
            wyniki_kolejki=fikcyjne_wyniki,
            nazwa_ligi="Ekstraklasa — test ą ę ł",
            df_tabela=fikcyjna_tabela,
            sciezka=sciezka,
        )
        assert Path(sciezka).exists(), f"Plik PDF nie powstał: {sciezka}"
        size = Path(sciezka).stat().st_size
        assert size > 1_000, f"Plik PDF jest za mały ({size} bajtów) — prawdopodobnie pusty"


def test_pdf_polish_chars_no_crash():
    """Eksport z polskimi znakami nie rzuca wyjątku."""
    from footstats.export.pdf import eksportuj_pdf

    polskie = [_wpis("Żółw Ćmy Łódź", "Ąąkacja Świętosław")]

    with tempfile.TemporaryDirectory() as tmpdir:
        sciezka = os.path.join(tmpdir, "polish_test.pdf")
        try:
            eksportuj_pdf(
                wyniki_kolejki=polskie,
                nazwa_ligi="Liga Polskich Znaków: ą ę ó ś ź ż ń ć ł",
                sciezka=sciezka,
            )
        except Exception as e:
            pytest.fail(f"eksportuj_pdf() rzuciło wyjątek przy polskich znakach: {e}")
