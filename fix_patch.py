"""
fix_patch.py – Usuwa błędny lokalny import Progress z footstats.py
Uruchom: python fix_patch.py
"""
from pathlib import Path
import sys

PLIK = Path("footstats.py")

if not PLIK.exists():
    print("BŁĄD: Nie znaleziono footstats.py")
    sys.exit(1)

kod = PLIK.read_text(encoding="utf-8")

# Linia która powoduje UnboundLocalError - usuń ją
STARA = "                    from rich.progress import Progress, SpinnerColumn, TextColumn\n"
if STARA not in kod:
    print("Linia już usunięta lub nie znaleziona - sprawdzam alternatywę...")
    # Spróbuj wersję z innym wcięciem
    STARA2 = "                from rich.progress import Progress, SpinnerColumn, TextColumn\n"
    if STARA2 in kod:
        kod = kod.replace(STARA2, "", 1)
        PLIK.write_text(kod, encoding="utf-8")
        print("✓ Naprawiono (wcięcie 16 spacji)")
    else:
        print("Nie znaleziono problematycznej linii - może już naprawione?")
    sys.exit(0)

kod = kod.replace(STARA, "", 1)
PLIK.write_text(kod, encoding="utf-8")
print("✓ Usunięto błędny import - footstats.py naprawiony")
print("Uruchom: python footstats.py")
