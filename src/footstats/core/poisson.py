import math
import pandas as pd
import numpy as np
from scipy.stats import poisson
from datetime import datetime
from footstats.config import (
    MAX_GOLE, BONUS_DOMOWY, PEWNIACZEK_PROG, BZZOIRO_MAX_ROZN, OSTATNIE_N,
)
from footstats.core.fatigue import HeurystaZmeczeniaRotacji
from footstats.core.h2h import AnalizaH2H
from footstats.core.fortress import HomeFortress
from footstats.core.classifier import KlasyfikatorMeczu, _korekta_dwumecz, _czy_knockout, _korekta_rewanz_v26
from footstats.core.importance import ImportanceIndex
from footstats.core.form import _oblicz_sile_wazona, _wagi_mecze, AnalizaDomWyjazd
from footstats.utils.console import console

# ================================================================
#  MODUL 10 - PREDYKCJA POISSONA
# ================================================================

def predict_match(
    g: str, a: str,
    df_mecze: pd.DataFrame,
    importance_g: dict = None,
    importance_a: dict = None,
    heurystyka_g: dict = None,
    heurystyka_a: dict = None,
    h2h_g: dict = None,
    h2h_a: dict = None,
    fortress_g: dict = None,
    first_leg_g=None, first_leg_a=None,
    stage: str = "REGULAR_SEASON",
    klasyfikacja: dict = None,
) -> dict | None:
    """
    Kompletna predykcja v2.6 z:
      1. Wazona forma historyczna
      2. Stage Recognition: LIGA vs PUCHAR vs REWANZ vs FINAL
      3. Fallback turniejowy: gdy brak statystyk pary, uzyj sredniej turniejowej
      4. Importance Index 2.0
      5. Heurystyka zmeczenia/rotacji
      6. AnalizaH2H: Patent +10%, Zemsta +15%
      7. HomeFortress: +10% obrona
      8. Rewanz Vabank v2.6 (+30% / Parking Bus)
      9. Single-Match Finals: boost remisu + uwaga 'dogr./karne'
    Zwraca dict lub None jesli za malo danych.
    """
    importance_g = importance_g or {"bonus_atak": 1.0, "komentarz": "", "status": "NORMAL"}
    importance_a = importance_a or {"bonus_atak": 1.0, "komentarz": "", "status": "NORMAL"}
    heurystyka_g = heurystyka_g or {"mnoznik_atak": 1.0, "mnoznik_obr": 1.0, "opis": ""}
    heurystyka_a = heurystyka_a or {"mnoznik_atak": 1.0, "mnoznik_obr": 1.0, "opis": ""}
    h2h_g        = h2h_g or {"mnoznik_atak": 1.0, "mnoznik_szans": 1.0, "opis": "", "pewnosc": 20, "n_h2h": 0}
    h2h_a        = h2h_a or {"mnoznik_atak": 1.0, "mnoznik_szans": 1.0, "opis": "", "pewnosc": 20, "n_h2h": 0}
    fortress_g   = fortress_g or {"bonus_obrona": 1.0, "fortress": False, "opis": ""}
    klasyfikacja = klasyfikacja or {"typ": "LIGA", "rewanz": False, "single": False,
                                    "agg_g": None, "agg_a": None, "opis": ""}

    stage_up     = str(stage).upper()
    is_liga      = (stage_up == "REGULAR_SEASON")
    jest_rewanz  = klasyfikacja.get("rewanz", False)
    jest_single  = klasyfikacja.get("single", False)

    # ── Zbierz mecze do analizy ──────────────────────────────────────
    maska = (
        (df_mecze["gospodarz"] == g) | (df_mecze["goscie"] == g) |
        (df_mecze["gospodarz"] == a) | (df_mecze["goscie"] == a)
    )
    df_f = df_mecze[maska].tail(OSTATNIE_N)

    # ── v2.6 STABILNOSC: fallback turniejowy ─────────────────────────
    # Jesli brak danych pary w fazie pucharowej, nie zwracamy None —
    # uzyj ogolnej sredniej z df_mecze (min 4 mecze dowolnych).
    if len(df_f) < 4:
        if is_liga:
            return None  # Liga: normalna sciezka, brak danych = brak predykcji
        # Tryb turniejowy: probuj z calym df
        df_f_all = df_mecze.tail(OSTATNIE_N * 2)
        if len(df_f_all) < 4:
            return None
        # Policz srednia turniejowa i syntetyczne sily dla pary
        sily_all, srednia_all = _oblicz_sile_wazona(df_f_all)
        if not sily_all:
            return None
        # Szacuj sily jako srednia turniejowa (fallback)
        avg_atak  = float(np.mean([v["atak"]   for v in sily_all.values()]))
        avg_obr   = float(np.mean([v["obrona"] for v in sily_all.values()]))
        avg_gsr   = float(np.mean([v["gole_sr"] for v in sily_all.values()]))
        avg_strac = float(np.mean([v["strac_sr"] for v in sily_all.values()]))
        avg_forma = float(np.mean([v["forma_pkt"] for v in sily_all.values()]))
        syntetyczna = {
            "atak": avg_atak, "obrona": avg_obr,
            "gole_sr": avg_gsr, "strac_sr": avg_strac, "forma_pkt": avg_forma
        }
        sg = sily_all.get(g, syntetyczna)
        sa = sily_all.get(a, syntetyczna)
        srednia = srednia_all
        df_f    = df_f_all   # do confidence
    else:
        sily, srednia = _oblicz_sile_wazona(df_f)
        if g not in sily or a not in sily:
            return None
        sg, sa = sily[g], sily[a]

    # ── Lambda bazowa ────────────────────────────────────────────────
    lambda_g = max(0.05,
        sg["atak"]
        * sa["obrona"]
        * srednia
        * BONUS_DOMOWY
        * importance_g["bonus_atak"]
        * heurystyka_g["mnoznik_atak"]
        * h2h_g["mnoznik_atak"]
        / heurystyka_a["mnoznik_obr"]
    )
    lambda_a = max(0.05,
        sa["atak"]
        * sg["obrona"]
        * srednia
        * importance_a["bonus_atak"]
        * heurystyka_a["mnoznik_atak"]
        * h2h_a["mnoznik_atak"]
        / heurystyka_g["mnoznik_obr"]
        / fortress_g["bonus_obrona"]
    )

    # Patent H2H
    lambda_g *= h2h_g.get("mnoznik_szans", 1.0)
    lambda_a *= h2h_a.get("mnoznik_szans", 1.0)
    lambda_g = max(0.05, lambda_g)
    lambda_a = max(0.05, lambda_a)

    # ── v2.6 Korekta rewanzowa ───────────────────────────────────────
    korekta_opis = ""
    jest_knockout = _czy_knockout(stage)

    if jest_rewanz:
        agg_g = klasyfikacja.get("agg_g")
        agg_a = klasyfikacja.get("agg_a")
        if agg_g is not None and agg_a is not None:
            lambda_g, lambda_a, korekta_opis = _korekta_rewanz_v26(
                lambda_g, lambda_a, int(agg_g), int(agg_a))
        elif first_leg_g is not None:
            lambda_g, lambda_a, korekta_opis = _korekta_dwumecz(
                lambda_g, lambda_a, first_leg_g, first_leg_a, jest_gospodarzem_1=False)
    elif jest_knockout and first_leg_g is not None:
        lambda_g, lambda_a, korekta_opis = _korekta_dwumecz(
            lambda_g, lambda_a, first_leg_g, first_leg_a, jest_gospodarzem_1=False)

    lambda_g = max(0.05, lambda_g)
    lambda_a = max(0.05, lambda_a)

    # ── Macierz Poissona ─────────────────────────────────────────────
    N = MAX_GOLE + 1
    M = np.zeros((N, N))
    for i in range(N):
        for j in range(N):
            M[i][j] = poisson.pmf(i, lambda_g) * poisson.pmf(j, lambda_a)

    pw  = float(np.sum(np.tril(M, -1)))
    pr  = float(np.sum(np.diag(M)))
    pp  = float(np.sum(np.triu(M,  1)))

    # ── v2.6 Final boost: wiekszy remis w meczach bez rewanzu ────────
    from footstats.config import FINAL_REMIS_BOOST
    if jest_single:
        pr *= FINAL_REMIS_BOOST   # szansa remisu rosnie (dogrywka/karne realna)

    suma = pw + pr + pp or 1.0
    pw /= suma; pr /= suma; pp /= suma

    btts   = (1 - poisson.pmf(0, lambda_g)) * (1 - poisson.pmf(0, lambda_a))
    over25 = 1.0 - sum(M[i][j] for i in range(N) for j in range(N) if i+j <= 2)
    over25 = min(over25 / suma, 1.0)

    idx  = np.unravel_index(np.argmax(M), M.shape)
    flat = sorted([(M[i][j], i, j) for i in range(N) for j in range(N)], reverse=True)
    top5 = [(f"{i}:{j}", round(p*100, 1)) for p, i, j in flat[:5]]

    n_h2h_srednia = (h2h_g.get("n_h2h", 0) + h2h_a.get("n_h2h", 0)) // 2
    pewnosc = AnalizaH2H.oblicz_pewnosc_laczna(n_h2h_srednia, len(df_f))

    return {
        "gospodarz":    g,
        "gosc":         a,
        "lambda_g":     round(lambda_g, 2),
        "lambda_a":     round(lambda_a, 2),
        "p_wygrana":    round(pw  * 100, 1),
        "p_remis":      round(pr  * 100, 1),
        "p_przegrana":  round(pp  * 100, 1),
        "btts":         round(btts  * 100, 1),
        "over25":       round(over25 * 100, 1),
        "under25":      round((1 - over25) * 100, 1),
        "wynik_g":      int(idx[0]),
        "wynik_a":      int(idx[1]),
        "top5":         top5,
        "sila_at_g":    round(sg["atak"],   2),
        "sila_ob_g":    round(sg["obrona"], 2),
        "sila_at_a":    round(sa["atak"],   2),
        "sila_ob_a":    round(sa["obrona"], 2),
        "forma_g":      sg["forma_pkt"],
        "forma_a":      sa["forma_pkt"],
        "imp_g":        importance_g,
        "imp_a":        importance_a,
        "heur_g":       heurystyka_g,
        "heur_a":       heurystyka_a,
        "h2h_g":        h2h_g,
        "h2h_a":        h2h_a,
        "fortress_g":   fortress_g,
        "knockout":     jest_knockout,
        "rewanz":       jest_rewanz,
        "single":       jest_single,
        "korekta_opis": korekta_opis,
        "klasyfikacja": klasyfikacja,
        "pewnosc":      pewnosc,
    }
