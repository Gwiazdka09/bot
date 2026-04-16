"""
Minimalny test regresji PDF.
Weryfikuje:
  1. Że pdf_font.py ładuje się bez błędu
  2. Że PDF generuje się poprawnie (nawet bez fontu DejaVu)
  3. Czy font DejaVuSans.ttf jest dostępny w assets/ lub fallback
"""
import io
from pathlib import Path

import pytest


ASSETS_FONT = Path(__file__).parents[1] / "assets" / "DejaVuSans.ttf"
WINDOWS_FONT = Path(r"C:\Windows\Fonts\DejaVuSans.ttf")


def test_font_path_exists_or_windows_fallback():
    """Font jest w assets/ lub dostępny systemowo — co najmniej jedno musi być prawdą."""
    has_font = ASSETS_FONT.exists() or WINDOWS_FONT.exists()
    if not has_font:
        pytest.skip(
            f"DejaVuSans.ttf nie znaleziony w {ASSETS_FONT} ani {WINDOWS_FONT}. "
            "Skopiuj font do F:/bot/assets/DejaVuSans.ttf."
        )
    assert has_font


def test_pdf_font_module_imports():
    """pdf_font.py musi się importować bez wyjątku."""
    from footstats.export import pdf_font  # noqa: F401 — sam import to test


def test_pdf_generates_without_crash():
    """Generuje minimalny PDF w pamięci — musi się udać niezależnie od stanu fontu."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from footstats.export.pdf_font import _pdf, FONT_OK, PDF_FONT

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)

    # Rejestracja fontu jest idempotentna dzięki _zarejestruj_font() przy imporcie
    c.setFont(PDF_FONT, 12)
    c.drawString(100, 700, _pdf("FootStats — test PDF z polskimi znakami: ąćęłńóśźż"))
    c.save()

    pdf_bytes = buf.getvalue()
    assert pdf_bytes[:4] == b"%PDF", "Wygenerowany plik nie jest prawidłowym PDF"
    assert len(pdf_bytes) > 500, "PDF jest podejrzanie mały"

    font_status = "DejaVu (ogonki OK)" if FONT_OK else "Helvetica (fallback, brak ogonków)"
    print(f"\n  Font: {font_status} | Rozmiar PDF: {len(pdf_bytes)} bajtów")
