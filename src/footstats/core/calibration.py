"""
Etap 6: Kalibracja stawki na podstawie hit-rate z ostatnich N kuponów.

Logika:
  hit_rate > 0.80  → stake_multiplier = 1.2  (gramy odważniej)
  hit_rate < 0.50  → stake_multiplier = 0.5  (minimalizujemy straty)
  pomiędzy         → stake_multiplier = 1.0  (neutralny)

Multiplier jest stosowany jako dodatkowy czynnik do bankrollu przed Kelly.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parents[3] / "data" / "footstats_backtest.db"

MULTIPLIER_HIGH = 1.2   # hit_rate > HIGH_THRESHOLD
MULTIPLIER_LOW  = 0.5   # hit_rate < LOW_THRESHOLD
MULTIPLIER_NEUTRAL = 1.0

HIGH_THRESHOLD = 0.80
LOW_THRESHOLD  = 0.50
LOOKBACK_N     = 10     # ostatnie N rozliczonych kuponów


def get_stake_multiplier(n: int = LOOKBACK_N) -> float:
    """
    Oblicza stake_multiplier na podstawie hit-rate z ostatnich `n` kuponów WON/LOST.

    Zwraca 0.5 / 1.0 / 1.2 zależnie od skuteczności.
    Jeśli brak danych historycznych — zwraca 1.0 (brak kalibracji).
    """
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT status FROM coupons
            WHERE status IN ('WON', 'LOST')
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (n,),
        ).fetchall()
        conn.close()
    except Exception:
        return MULTIPLIER_NEUTRAL

    if not rows:
        return MULTIPLIER_NEUTRAL

    won  = sum(1 for r in rows if r["status"] == "WON")
    total = len(rows)
    hit_rate = won / total

    if hit_rate > HIGH_THRESHOLD:
        return MULTIPLIER_HIGH
    if hit_rate < LOW_THRESHOLD:
        return MULTIPLIER_LOW
    return MULTIPLIER_NEUTRAL


def calibration_summary(n: int = LOOKBACK_N) -> dict:
    """Zwraca słownik ze statystykami kalibracji — do logowania w agencie."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT status, stake_pln, payout_pln, roi_pct FROM coupons
            WHERE status IN ('WON', 'LOST')
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (n,),
        ).fetchall()
        conn.close()
    except Exception:
        return {"error": "Brak dostępu do DB", "multiplier": MULTIPLIER_NEUTRAL}

    if not rows:
        return {"n": 0, "hit_rate": None, "multiplier": MULTIPLIER_NEUTRAL, "note": "Brak historii"}

    won      = sum(1 for r in rows if r["status"] == "WON")
    total    = len(rows)
    hit_rate = won / total
    avg_roi  = sum((r["roi_pct"] or 0) for r in rows) / total
    multiplier = get_stake_multiplier(n)

    return {
        "n":           total,
        "won":         won,
        "lost":        total - won,
        "hit_rate":    round(hit_rate, 3),
        "avg_roi_pct": round(avg_roi, 1),
        "multiplier":  multiplier,
        "note": (
            "Forma wysoka — gramy odważniej"  if multiplier > 1 else
            "Forma niska — minimalizujemy straty" if multiplier < 1 else
            "Forma neutralna"
        ),
    }
