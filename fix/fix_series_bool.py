"""
fix_series_bool.py – Naprawia błąd "Truth value of a Series is ambiguous"
Linia 5118 w footstats.py: _m.get("mecz") or {} crashuje bo "mecz" to pandas Series
Uruchom: python fix_series_bool.py
"""
from pathlib import Path
import sys

PLIK = Path("footstats.py")
if not PLIK.exists():
    print("BŁĄD: Nie znaleziono footstats.py"); sys.exit(1)

kod = PLIK.read_text(encoding="utf-8")

# ── Fix 1: błędna linia z pandas Series bool ────────────────────────
STARA = "                        _pred = _m.get(\"predykcja\") or {}\n                        _mecz = _m.get(\"mecz\") or {}"
NOWA  = """                        _pred_raw = _m.get("predykcja")
                        _pred = _pred_raw if _pred_raw is not None else {}
                        _mecz_raw = _m.get("mecz")
                        _mecz = _mecz_raw if _mecz_raw is not None else {}"""

if STARA not in kod:
    print("BŁĄD: Nie znaleziono linii do naprawy.")
    print("Sprawdź czy fix_handler_j.py był uruchomiony.")
    sys.exit(1)

kod = kod.replace(STARA, NOWA, 1)

# ── Fix 2: _mecz.get() na pandas Series też crashuje ────────────────
# Zamień _mecz.get("gospodarz") na bezpieczne getattr dla Series
STARA2 = """                        _g = _pred.get("gospodarz") or (
                            _mecz.get("gospodarz") if hasattr(_mecz, "get") else
                            getattr(_mecz, "gospodarz", _g)
                        )
                        _a = _pred.get("gosc") or (
                            _mecz.get("goscie") if hasattr(_mecz, "get") else
                            getattr(_mecz, "goscie", _a)
                        )"""

NOWA2  = """                        # Pobierz nazwy — _pred to dict, _mecz to pandas Series lub dict
                        _g = _pred.get("gospodarz", "") if isinstance(_pred, dict) else ""
                        _a = _pred.get("gosc", "")      if isinstance(_pred, dict) else ""
                        if not _g and _mecz_raw is not None:
                            try:
                                _g = str(_mecz_raw["gospodarz"]) if "gospodarz" in _mecz_raw.index else ""
                            except Exception:
                                pass
                        if not _a and _mecz_raw is not None:
                            try:
                                _a = str(_mecz_raw["goscie"]) if "goscie" in _mecz_raw.index else ""
                            except Exception:
                                pass"""

if STARA2 in kod:
    kod = kod.replace(STARA2, NOWA2, 1)
    print("✓ Fix 2: bezpieczne odczytywanie pól z pandas Series")
else:
    print("⚠ Fix 2: nie znaleziono (może już naprawione)")

PLIK.write_text(kod, encoding="utf-8")
print("✓ Fix 1: naprawiono błąd 'Truth value of a Series is ambiguous'")
print()
print("Uruchom: python footstats.py → liga → 5 → J")
