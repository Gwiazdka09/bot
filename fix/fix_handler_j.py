"""
fix_handler_j.py – Naprawia handler opcji J w footstats.py
Problem: cache_kolejki ma strukturę {"mecz": ..., "predykcja": ..., "klasyfikacja": ...}
         ale handler czytał pola bezpośrednio z _m zamiast z _m["predykcja"]
Uruchom: python fix_handler_j.py
"""
from pathlib import Path
import sys

PLIK = Path("footstats.py")
if not PLIK.exists():
    print("BŁĄD: Nie znaleziono footstats.py"); sys.exit(1)

kod = PLIK.read_text(encoding="utf-8")

# ── Znajdź i zamień blok handlera J ─────────────────────────────────
STARY = '''                    console.print(f"  [{_i}/{len(cache_kolejki)}] {_g} vs {_a}")
                        _k = None
                        if _liga_slug_j:
                            try:
                                _k = _kursy_ai(_g, _a, _liga_slug_j)
                            except Exception:
                                pass
                        try:
                            _wyn = _analizuj_ai(
                                gospodarz      = _g,
                                goscie         = _a,
                                p_wygrana      = _m.get("p_wygrana", 33),
                                p_remis        = _m.get("p_remis", 33),
                                p_przegrana    = _m.get("p_przegrana", 34),
                                btts           = _m.get("btts", 0),
                                over25         = _m.get("over25", 0),
                                pewnosc_modelu = _m.get("pewnosc", 0),
                                komentarz_footstats = _m.get("komentarz", ""),
                                kursy          = _k,
                            )'''

NOWY = '''                    # cache_kolejki = [{"mecz": row, "predykcja": wynik, "klasyfikacja": klas}]
                        _pred = _m.get("predykcja") or {}
                        _mecz = _m.get("mecz") or {}
                        # Pobierz nazwy z predykcji (zawiera gospodarz/gosc z predict_match)
                        _g = _pred.get("gospodarz") or (
                            _mecz.get("gospodarz") if hasattr(_mecz, "get") else
                            getattr(_mecz, "gospodarz", _g)
                        )
                        _a = _pred.get("gosc") or (
                            _mecz.get("goscie") if hasattr(_mecz, "get") else
                            getattr(_mecz, "goscie", _a)
                        )
                        if not _g or not _a:
                            continue  # pomijaj mecze bez nazw drużyn
                        console.print(f"  [{_i}/{len(cache_kolejki)}] {_g} vs {_a}")
                        _k = None
                        if _liga_slug_j:
                            try:
                                _k = _kursy_ai(_g, _a, _liga_slug_j)
                            except Exception:
                                pass
                        # Pobierz formę jako string
                        def _fstr(druz, n=5):
                            try:
                                df_f = df_wyniki[
                                    (df_wyniki["gospodarz"]==druz)|(df_wyniki["goscie"]==druz)
                                ].tail(n)
                                r2=[]
                                for _, rw in df_f.iterrows():
                                    if rw["gospodarz"]==druz:
                                        r2.append("W" if rw["gole_g"]>rw["gole_a"] else("R" if rw["gole_g"]==rw["gole_a"] else "P"))
                                    else:
                                        r2.append("W" if rw["gole_a"]>rw["gole_g"] else("R" if rw["gole_g"]==rw["gole_a"] else "P"))
                                return "".join(r2)
                            except Exception:
                                return "-"
                        try:
                            _wyn = _analizuj_ai(
                                gospodarz           = _g,
                                goscie              = _a,
                                p_wygrana           = _pred.get("p_wygrana", 33),
                                p_remis             = _pred.get("p_remis",   33),
                                p_przegrana         = _pred.get("p_przegrana", 34),
                                btts                = _pred.get("btts", 0),
                                over25              = _pred.get("over25", 0),
                                forma_g             = _fstr(_g),
                                forma_a             = _fstr(_a),
                                h2h_opis            = _pred.get("h2h_g", {}).get("opis", "-") or "-",
                                pewnosc_modelu      = _pred.get("pewnosc", 0),
                                komentarz_footstats = komentarz_analityka(_pred),
                                kursy               = _k,
                            )'''

if STARY not in kod:
    print("BŁĄD: Nie znaleziono bloku do naprawienia.")
    print("Sprawdź czy patch_footstats_ai.py był uruchomiony.")
    sys.exit(1)

kod = kod.replace(STARY, NOWY, 1)
PLIK.write_text(kod, encoding="utf-8")
print("✓ Handler J naprawiony — teraz czyta dane z _m['predykcja']")
print("✓ Dodano formę i komentarz FootStats do promptu AI")
print("✓ Puste mecze (bez nazw) są pomijane")
print()
print("Uruchom: python footstats.py → opcja 5 → opcja J")
