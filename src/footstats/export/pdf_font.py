from pathlib import Path
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ================================================================
#  MODUL 1 - CZCIONKA PDF
# ================================================================

_FONT_PATHS = [
    Path(__file__).parent.parent.parent.parent / "assets" / "DejaVuSans.ttf",
    Path(__file__).parent.parent.parent.parent / "DejaVuSans.ttf",  # legacy (root)
    Path(r"C:\Windows\Fonts\DejaVuSans.ttf"),
    Path(r"C:\Windows\Fonts\dejavusans.ttf"),
    Path.home() / "DejaVuSans.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
]
PDF_FONT      = "Helvetica"
PDF_FONT_BOLD = "Helvetica-Bold"
FONT_OK       = False

def _zarejestruj_font():
    global PDF_FONT, PDF_FONT_BOLD, FONT_OK
    for p in _FONT_PATHS:
        if p.is_file():
            try:
                pdfmetrics.registerFont(TTFont("DejaVu", str(p)))
                PDF_FONT = PDF_FONT_BOLD = "DejaVu"
                FONT_OK = True
                return True
            except Exception:
                pass
    return False

def _pdf(tekst: str) -> str:
    if FONT_OK:
        return str(tekst)
    return str(tekst).translate(str.maketrans(
        "acelnoszz ACELNOSZZ",
        "acelnoszz ACELNOSZZ"
    )).translate(str.maketrans(
        "\u0105\u0107\u0119\u0142\u0144\u00f3\u015b\u017a\u017c\u0104\u0106\u0118\u0141\u0143\u00d3\u015a\u0179\u017b",
        "acelnoszzACELNOSZZ"
    ))
