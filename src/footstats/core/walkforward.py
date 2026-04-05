"""
walkforward.py – Walk-forward backtest modelu FootStats na danych historycznych.

Dla każdego meczu w df_hist:
  - Historia = wszystkie mecze PRZED tą datą (no lookahead)
  - Predykcja = Poisson lambda z historii + prosty model formy
  - Porównanie z rzeczywistym wynikiem
  - Zapis do SQLite (tabela wf_results)

Użycie:
    python -m footstats.core.walkforward --liga "NED-Eredivisie" --sezon 2024
    python -m footstats.core.walkforward --all --top 5
"""

import json
import sqlite3
import sys
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd

DB_PATH  = Path(__file__).parents[3] / "data" / "footstats_backtest.db"
MIN_HIST = 5   # min meczów drużyny w historii żeby liczyć lambdę


# ── DB ────────────────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_wf_table() -> None:
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS wf_results (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                run_at       TEXT NOT NULL DEFAULT (datetime('now')),
                league       TEXT NOT NULL,
                match_date   TEXT NOT NULL,
                home         TEXT NOT NULL,
                away         TEXT NOT NULL,
                actual_hg    INTEGER,
                actual_ag    INTEGER,
                actual_res   TEXT,
                pred_res     TEXT,
                pred_conf    REAL,
                pred_tip     TEXT,
                lambda_h     REAL,
                lambda_a     REAL,
                form_h       REAL,
                form_a       REAL,
                elo_diff     REAL,
                correct      INTEGER,
                market       TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_wf_league ON wf_results(league)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_wf_correct ON wf_results(correct)")


# ── Predykcja oparta na historii ─────────────────────────────────────────

def _lambda(hist: pd.DataFrame, team: str, as_home: bool, n: int = 10) -> float | None:
    """Średnia goli strzelonych przez drużynę w ostatnich n meczach."""
    if as_home:
        sub = hist[hist["home"] == team]["hg"]
    else:
        sub = hist[hist["away"] == team]["ag"]
    sub = sub.dropna().tail(n)
    return float(sub.mean()) if len(sub) >= MIN_HIST else None


def _forma(hist: pd.DataFrame, team: str, n: int = 5) -> float:
    """Średnie punkty na mecz z ostatnich n gier (3=W, 1=D, 0=L)."""
    h_games = hist[hist["home"] == team][["result"]].copy()
    h_games["pts"] = h_games["result"].map({"H": 3, "D": 1, "A": 0})
    a_games = hist[hist["away"] == team][["result"]].copy()
    a_games["pts"] = a_games["result"].map({"A": 3, "D": 1, "H": 0})
    all_pts = pd.concat([h_games["pts"], a_games["pts"]]).dropna().tail(n)
    return float(all_pts.mean()) if len(all_pts) > 0 else 1.0


def _poisson_probs(lam_h: float, lam_a: float, max_g: int = 6) -> tuple[float, float, float]:
    """Zwraca (P_home_win, P_draw, P_away_win) na podstawie Poisson."""
    from math import exp, factorial
    p = [[exp(-lam_h) * lam_h**i / factorial(i) *
          exp(-lam_a) * lam_a**j / factorial(j)
          for j in range(max_g + 1)]
         for i in range(max_g + 1)]
    pw = sum(p[i][j] for i in range(max_g + 1) for j in range(max_g + 1) if i > j)
    pr = sum(p[i][i] for i in range(max_g + 1))
    pp = 1.0 - pw - pr
    return round(pw, 4), round(pr, 4), round(pp, 4)


def predict_single(hist: pd.DataFrame, home: str, away: str) -> dict | None:
    """Predykcja dla jednego meczu na podstawie historii."""
    lh = _lambda(hist, home, as_home=True)
    la = _lambda(hist, away, as_home=False)
    if lh is None or la is None:
        return None

    # Prosta korekta formą
    fh = _forma(hist, home)
    fa = _forma(hist, away)
    form_ratio = (fh + 0.1) / (fa + 0.1)
    lh_adj = lh * min(max(form_ratio ** 0.3, 0.7), 1.4)
    la_adj = la / min(max(form_ratio ** 0.3, 0.7), 1.4)

    pw, pr, pp = _poisson_probs(lh_adj, la_adj)
    max_p = max(pw, pr, pp)
    if max_p == pw:
        tip, conf = "1", pw
    elif max_p == pr:
        tip, conf = "X", pr
    else:
        tip, conf = "2", pp

    # Over 2.5 Poisson
    from math import exp, factorial
    p_under3 = sum(
        exp(-lh_adj) * lh_adj**i / factorial(i) *
        exp(-la_adj) * la_adj**j / factorial(j)
        for i in range(4) for j in range(4) if i + j <= 2
    )
    over25 = round(1 - p_under3, 4)

    elo_diff = None
    if "elo_home" in hist.columns:
        elo_h_vals = hist[hist["home"] == home]["elo_home"].dropna().tail(3)
        elo_a_vals = hist[hist["away"] == away]["elo_away"].dropna().tail(3)
        if len(elo_h_vals) and len(elo_a_vals):
            elo_diff = float(elo_h_vals.mean() - elo_a_vals.mean())

    return {
        "tip": tip, "conf": round(conf, 4),
        "pw": pw, "pr": pr, "pp": pp,
        "lh": round(lh_adj, 3), "la": round(la_adj, 3),
        "over25": over25,
        "form_h": round(fh, 2), "form_a": round(fa, 2),
        "elo_diff": elo_diff,
    }


# ── Główna pętla walk-forward ─────────────────────────────────────────────

def run_walkforward(
    df: pd.DataFrame,
    league: str | None = None,
    max_matches: int | None = None,
    min_date: str | None = None,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    Uruchamia walk-forward backtest.

    df      – pełny DataFrame z historical_loader (wszystkie mecze)
    league  – ogranicz do jednej ligi (None = wszystkie)
    max_matches – limit meczów (None = wszystkie)
    min_date – start backtesту (YYYY-MM-DD), domyślnie od 20% danych
    """
    _init_wf_table()

    if league:
        df_wf = df[df["league"] == league].copy()
    else:
        df_wf = df.copy()

    df_wf = df_wf.sort_values("date").reset_index(drop=True)

    if min_date:
        df_wf = df_wf[df_wf["date"] >= pd.Timestamp(min_date)]
    else:
        # Zacznij od 20% żeby mieć historię
        start_idx = max(50, len(df_wf) // 5)
        df_wf = df_wf.iloc[start_idx:].reset_index(drop=True)

    if max_matches:
        df_wf = df_wf.head(max_matches)

    if verbose:
        print(f"[WalkForward] Liga: {league or 'wszystkie'} | Meczów do backtestу: {len(df_wf):,}")

    records = []
    correct_res = correct_over = total_res = total_over = 0

    for idx, row in df_wf.iterrows():
        # Historia = wszystkie mecze PRZED tą datą (w tej lidze jeśli liga filtr)
        hist = df[df["date"] < row["date"]]
        if league:
            hist = hist[hist["league"] == league]

        pred = predict_single(hist, row["home"], row["away"])
        if pred is None:
            continue

        actual_res = row.get("result", "")
        actual_hg  = int(row["hg"]) if not pd.isna(row.get("hg", float("nan"))) else None
        actual_ag  = int(row["ag"]) if not pd.isna(row.get("ag", float("nan"))) else None

        # Sprawdź wynik 1X2
        correct_1x2 = None
        if actual_res in ("H", "D", "A"):
            tip_map = {"1": "H", "X": "D", "2": "A"}
            correct_1x2 = 1 if tip_map.get(pred["tip"]) == actual_res else 0
            total_res += 1
            correct_res += correct_1x2

        # Sprawdź Over 2.5
        correct_o25 = None
        if actual_hg is not None and actual_ag is not None:
            actual_over = 1 if (actual_hg + actual_ag) > 2.5 else 0
            pred_over   = 1 if pred["over25"] > 0.5 else 0
            correct_o25 = 1 if actual_over == pred_over else 0
            total_over += 1
            correct_over += correct_o25

        records.append({
            "league":      row.get("league", ""),
            "match_date":  str(row["date"])[:10],
            "home":        row["home"],
            "away":        row["away"],
            "actual_hg":   actual_hg,
            "actual_ag":   actual_ag,
            "actual_res":  actual_res,
            "pred_res":    pred["tip"],
            "pred_conf":   pred["conf"],
            "lambda_h":    pred["lh"],
            "lambda_a":    pred["la"],
            "form_h":      pred["form_h"],
            "form_a":      pred["form_a"],
            "elo_diff":    pred["elo_diff"],
            "correct_1x2": correct_1x2,
            "correct_o25": correct_o25,
            "over25_pred": pred["over25"],
        })

    df_out = pd.DataFrame(records)

    # Zapisz do SQLite
    with _connect() as conn:
        for r in records:
            conn.execute("""
                INSERT INTO wf_results
                  (league, match_date, home, away, actual_hg, actual_ag, actual_res,
                   pred_res, pred_conf, lambda_h, lambda_a, form_h, form_a, elo_diff,
                   correct, market)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                r["league"], r["match_date"], r["home"], r["away"],
                r["actual_hg"], r["actual_ag"], r["actual_res"],
                r["pred_res"], r["pred_conf"], r["lambda_h"], r["lambda_a"],
                r["form_h"], r["form_a"], r["elo_diff"],
                r["correct_1x2"], "1X2",
            ))

    acc_1x2 = round(correct_res / total_res * 100, 1) if total_res else None
    acc_o25  = round(correct_over / total_over * 100, 1) if total_over else None

    if verbose:
        print(f"[WalkForward] Accuracy 1X2:   {acc_1x2}% (n={total_res})")
        print(f"[WalkForward] Accuracy Over2.5: {acc_o25}% (n={total_over})")

    df_out.attrs["acc_1x2"] = acc_1x2
    df_out.attrs["acc_o25"] = acc_o25
    return df_out


def raport_walkforward(df_out: pd.DataFrame) -> str:
    """Formatuje raport z wyników walk-forward."""
    linie = ["=" * 60, "  WALK-FORWARD BACKTEST – FootStats", "=" * 60]
    linie.append(f"  Meczow przeanalizowanych: {len(df_out):,}")

    for liga, grp in df_out.groupby("league"):
        ev_1x2 = grp["correct_1x2"].dropna()
        ev_o25 = grp["correct_o25"].dropna()
        linie.append(f"\n  {liga}:")
        if len(ev_1x2):
            linie.append(f"    1X2  accuracy: {ev_1x2.mean()*100:.1f}% (n={len(ev_1x2)})")
        if len(ev_o25):
            linie.append(f"    Over accuracy: {ev_o25.mean()*100:.1f}% (n={len(ev_o25)})")

    # Per pasmo pewnosci
    if "pred_conf" in df_out.columns:
        linie.append("\n  Accuracy per pasmo pewnosci (1X2):")
        df_v = df_out.dropna(subset=["correct_1x2"])
        for lo, hi in [(0.33, 0.45), (0.45, 0.55), (0.55, 0.65), (0.65, 1.0)]:
            sub = df_v[(df_v["pred_conf"] >= lo) & (df_v["pred_conf"] < hi)]
            if len(sub) >= 10:
                acc = sub["correct_1x2"].mean() * 100
                linie.append(f"    {lo:.0%}–{hi:.0%}: {acc:.1f}% (n={len(sub)})")

    linie.append("=" * 60)
    return "\n".join(linie)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="FootStats Walk-Forward Backtest")
    parser.add_argument("--liga",  type=str,  default=None, help="Filtruj ligę")
    parser.add_argument("--max",   type=int,  default=None, help="Max meczów")
    parser.add_argument("--od",    type=str,  default=None, help="Od daty YYYY-MM-DD")
    args = parser.parse_args()

    import logging
    logging.basicConfig(level=logging.WARNING)
    sys.path.insert(0, str(Path(__file__).parents[3] / "src"))

    from footstats.data.historical_loader import load_cached
    df_hist = load_cached()
    df_res  = run_walkforward(df_hist, league=args.liga, max_matches=args.max, min_date=args.od)
    print(raport_walkforward(df_res))
