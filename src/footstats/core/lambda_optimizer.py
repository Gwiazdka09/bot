"""
lambda_optimizer.py – Kalibracja modelu Poisson na podstawie walk-forward.

Wylicza Bias (mnożnik korygujący) dla lambda_h i lambda_a przez porównanie
przewidywanych lambd z rzeczywistymi golami z ostatnich N meczów historycznych.

Bias_Home = mean(actual_hg) / mean(predicted_lambda_h)
Bias_Away = mean(actual_ag)  / mean(predicted_lambda_a)

Safety rail: mnożnik clampowany do [0.85, 1.15].

Użycie:
    python -m footstats.core.lambda_optimizer           # 200 meczów
    python -m footstats.core.lambda_optimizer --n 500  # więcej danych
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd

# Ścieżka do pliku kalibracji
CALIBRATION_PATH = Path(__file__).parents[3] / "data" / "model_calibration.json"

# Safety rail — zakres dopuszczalnych mnożników
CAL_MIN = 0.85
CAL_MAX = 1.15

# Minimalna liczba meczów do rzetelnej kalibracji
MIN_MATCHES_FOR_CAL = 30

# Cache w pamięci — ładowany raz na sesję
_cache: dict | None = None


# ── Odczyt kalibracji ─────────────────────────────────────────────────────

def load_calibration() -> tuple[float, float]:
    """
    Zwraca (factor_home, factor_away) z pliku JSON.
    Jeśli plik nie istnieje lub jest uszkodzony → (1.0, 1.0).
    """
    global _cache
    if _cache is not None:
        return _cache["factor_home"], _cache["factor_away"]
    try:
        data = json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))
        fh = float(data.get("factor_home", 1.0))
        fa = float(data.get("factor_away", 1.0))
        # Enforce safety rail na odczycie (zabezpieczenie przed ręczną edycją)
        fh = max(CAL_MIN, min(CAL_MAX, fh))
        fa = max(CAL_MIN, min(CAL_MAX, fa))
        _cache = {"factor_home": fh, "factor_away": fa}
        return fh, fa
    except Exception:
        return 1.0, 1.0


def invalidate_cache() -> None:
    """Wyczyść cache w pamięci — np. po zapisaniu nowej kalibracji."""
    global _cache
    _cache = None


# ── Zapis kalibracji ──────────────────────────────────────────────────────

def save_calibration(
    bias_h: float,
    bias_a: float,
    n_matches: int,
    acc_1x2: float | None = None,
) -> dict:
    """
    Aplikuje safety rail i zapisuje kalibrację do JSON.
    Zwraca dict z zapisanymi wartościami.
    """
    factor_h = round(max(CAL_MIN, min(CAL_MAX, bias_h)), 4)
    factor_a = round(max(CAL_MIN, min(CAL_MAX, bias_a)), 4)

    payload = {
        "factor_home":   factor_h,
        "factor_away":   factor_a,
        "bias_raw_home": round(bias_h, 6),
        "bias_raw_away": round(bias_a, 6),
        "n_matches":     n_matches,
        "acc_1x2_pct":   round(acc_1x2, 2) if acc_1x2 is not None else None,
        "updated_at":    datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "safety_rail":   [CAL_MIN, CAL_MAX],
        "clamped_home":  factor_h != round(bias_h, 4),
        "clamped_away":  factor_a != round(bias_a, 4),
    }

    CALIBRATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    CALIBRATION_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    invalidate_cache()
    return payload


# ── Pomocnicze funkcje walk-forward (bez zapisu do DB) ───────────────────

MIN_HIST = 5


def _lambda_from_hist(hist: pd.DataFrame, team: str, as_home: bool, n: int = 10) -> float | None:
    if as_home:
        sub = hist[hist["home"] == team]["hg"]
    else:
        sub = hist[hist["away"] == team]["ag"]
    sub = sub.dropna().tail(n)
    return float(sub.mean()) if len(sub) >= MIN_HIST else None


def _forma(hist: pd.DataFrame, team: str, n: int = 5) -> float:
    h = hist[hist["home"] == team][["result"]].copy()
    h["pts"] = h["result"].map({"H": 3, "D": 1, "A": 0})
    a = hist[hist["away"] == team][["result"]].copy()
    a["pts"] = a["result"].map({"A": 3, "D": 1, "H": 0})
    pts = pd.concat([h["pts"], a["pts"]]).dropna().tail(n)
    return float(pts.mean()) if len(pts) > 0 else 1.0


def _predict_lambdas(hist: pd.DataFrame, home: str, away: str) -> tuple[float, float] | None:
    """Zwraca (lambda_h, lambda_a) z korekta formy lub None jeśli za mało danych."""
    lh = _lambda_from_hist(hist, home, as_home=True)
    la = _lambda_from_hist(hist, away, as_home=False)
    if lh is None or la is None:
        return None

    fh = _forma(hist, home)
    fa = _forma(hist, away)
    ratio = (fh + 0.1) / (fa + 0.1)
    corr  = min(max(ratio ** 0.3, 0.7), 1.4)
    return lh * corr, la / corr


# ── Główna funkcja kalibracji ─────────────────────────────────────────────

def run_calibration(n_matches: int = 200, verbose: bool = True) -> dict:
    """
    Uruchamia walk-forward na ostatnich n_matches meczach historycznych,
    wylicza Bias i zapisuje kalibrację do data/model_calibration.json.

    Zwraca dict z wynikami (factor_home, factor_away, n_used, ...).
    """
    from footstats.data.historical_loader import load_cached

    if verbose:
        print(f"[LambdaOptimizer] Ładowanie danych historycznych...")
    df = load_cached()
    if df.empty:
        print("[LambdaOptimizer] Brak danych historycznych — przerywam.")
        return {}

    # Normalizacja kolumn — walkforward.py używa home/away/hg/ag/result/date
    col_map = {
        "gospodarz": "home", "goscie": "away",
        "gole_g": "hg",     "gole_a": "ag",
        "wynik":  "result",  "data":   "date",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    required = {"home", "away", "hg", "ag", "result", "date"}
    if not required.issubset(df.columns):
        missing = required - set(df.columns)
        print(f"[LambdaOptimizer] Brakuje kolumn: {missing} — przerywam.")
        return {}

    df = df.sort_values("date").reset_index(drop=True)

    # Zacznij od punktu gdzie jest wystarczająco dużo historii (20%)
    start_idx = max(50, len(df) // 5)
    df_wf = df.iloc[start_idx:].tail(n_matches).reset_index(drop=True)

    if verbose:
        print(f"[LambdaOptimizer] Testowe mecze: {len(df_wf)} (ostatnie z {len(df)} historycznych)")

    actual_hg_list: list[float] = []
    actual_ag_list: list[float] = []
    pred_lh_list:   list[float] = []
    pred_la_list:   list[float] = []
    correct_1x2 = 0
    total_1x2   = 0

    for _, row in df_wf.iterrows():
        hist = df[df["date"] < row["date"]]
        result = _predict_lambdas(hist, row["home"], row["away"])
        if result is None:
            continue

        lh, la = result
        ahg = row.get("hg")
        aag = row.get("ag")

        if pd.isna(ahg) or pd.isna(aag):
            continue

        actual_hg_list.append(float(ahg))
        actual_ag_list.append(float(aag))
        pred_lh_list.append(lh)
        pred_la_list.append(la)

        # Accuracy 1X2
        actual_res = row.get("result", "")
        if actual_res in ("H", "D", "A"):
            from math import exp, factorial
            def _pois_probs(lmh: float, lma: float, maxg: int = 6):
                p = [[exp(-lmh) * lmh**i / factorial(i) *
                      exp(-lma) * lma**j / factorial(j)
                      for j in range(maxg + 1)] for i in range(maxg + 1)]
                pw = sum(p[i][j] for i in range(maxg+1) for j in range(maxg+1) if i > j)
                pr = sum(p[i][i] for i in range(maxg+1))
                return pw, pr, 1.0 - pw - pr
            pw, pr, pp = _pois_probs(lh, la)
            tip = "1" if pw >= pr and pw >= pp else ("X" if pr >= pp else "2")
            tip_map = {"1": "H", "X": "D", "2": "A"}
            if tip_map[tip] == actual_res:
                correct_1x2 += 1
            total_1x2 += 1

    n_used = len(pred_lh_list)

    if n_used < MIN_MATCHES_FOR_CAL:
        print(f"[LambdaOptimizer] Za mało danych ({n_used} < {MIN_MATCHES_FOR_CAL}) — kalibracja pominięta.")
        return {"n_used": n_used, "error": "insufficient_data"}

    bias_h = float(np.mean(actual_hg_list)) / float(np.mean(pred_lh_list))
    bias_a = float(np.mean(actual_ag_list)) / float(np.mean(pred_la_list))
    acc    = correct_1x2 / total_1x2 * 100 if total_1x2 else None

    if verbose:
        print(f"[LambdaOptimizer] Użyto meczów:  {n_used}")
        print(f"[LambdaOptimizer] Bias_Home raw:  {bias_h:.4f}")
        print(f"[LambdaOptimizer] Bias_Away raw:  {bias_a:.4f}")
        print(f"[LambdaOptimizer] Accuracy 1X2:   {acc:.1f}%" if acc else "[LambdaOptimizer] Accuracy: brak danych")

    result_dict = save_calibration(bias_h, bias_a, n_used, acc)

    if verbose:
        clamped_h = " [CLAMPED]" if result_dict["clamped_home"] else ""
        clamped_a = " [CLAMPED]" if result_dict["clamped_away"] else ""
        print(f"[LambdaOptimizer] factor_home: {result_dict['factor_home']}{clamped_h}")
        print(f"[LambdaOptimizer] factor_away: {result_dict['factor_away']}{clamped_a}")
        print(f"[LambdaOptimizer] Zapisano → {CALIBRATION_PATH}")

    return result_dict


# ── CLI ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="FootStats Lambda Optimizer — kalibracja Poisson")
    parser.add_argument("--n",       type=int, default=200, help="Liczba ostatnich meczów do kalibracji (domyślnie: 200)")
    parser.add_argument("--quiet",   action="store_true",   help="Pomiń logi")
    args = parser.parse_args()

    res = run_calibration(n_matches=args.n, verbose=not args.quiet)
    if res and "factor_home" in res:
        print(f"\nGotowe. factor_home={res['factor_home']}, factor_away={res['factor_away']}")
    sys.exit(0 if res else 1)
