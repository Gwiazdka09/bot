"""
Etap 6: Kalibracja stawki na podstawie historii kuponów.

Dwa poziomy kalibracji:
  1. Hit-rate (ostatnie 10 kuponów):
       hit_rate > 0.80  → multiplier = 1.2
       hit_rate < 0.50  → multiplier = 0.5
       pomiędzy         → multiplier = 1.0

  2. Forma Bota (ostatnie 3 kupony — sygnał krótkoterminowy):
       3x WIN  → multiplier = 1.1  (seria — lekka agresja)
       3x LOSE → multiplier = 0.7  (seria strat — ochrona kapitału)
       mix     → multiplier = 1.0

Priorytet: jeśli mamy ≥3 rozliczone kupony, Forma Bota nadpisuje kalibrację
długoterminową (bo ostatnie 3 mecze są silniejszym sygnałem krótkoterm.).
Multiplier jest stosowany jako czynnik do efektywnego bankrollu przed Kelly.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parents[3] / "data" / "footstats_backtest.db"

# Kalibracja długoterminowa (10 kuponów)
MULTIPLIER_HIGH    = 1.2
MULTIPLIER_LOW     = 0.5
MULTIPLIER_NEUTRAL = 1.0
HIGH_THRESHOLD     = 0.80
LOW_THRESHOLD      = 0.50
LOOKBACK_N         = 10

# Forma Bota (3 kupony)
FORMA_WIN_MULTIPLIER  = 1.1   # 3x WIN z rzędu
FORMA_LOSE_MULTIPLIER = 0.7   # 3x LOSE z rzędu
FORMA_LOOKBACK        = 3


def _last_coupon_statuses(n: int) -> list[str]:
    """Zwraca statusy ostatnich n rozliczonych kuponów (WON/LOST), od najnowszego."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT status FROM coupons
               WHERE status IN ('WON','LOST')
               ORDER BY created_at DESC, id DESC
               LIMIT ?""",
            (n,),
        ).fetchall()
        conn.close()
        return [r["status"] for r in rows]
    except Exception:
        return []


def get_forma_multiplier() -> float:
    """
    Forma Bota: mnożnik na podstawie ostatnich 3 rozliczonych kuponów.

    3x WIN  → 1.1  (seria — lekka agresja)
    3x LOSE → 0.7  (seria strat — ochrona kapitału)
    mix/brak danych → 1.0
    """
    statuses = _last_coupon_statuses(FORMA_LOOKBACK)
    if len(statuses) < FORMA_LOOKBACK:
        return MULTIPLIER_NEUTRAL
    if all(s == "WON" for s in statuses):
        return FORMA_WIN_MULTIPLIER
    if all(s == "LOST" for s in statuses):
        return FORMA_LOSE_MULTIPLIER
    return MULTIPLIER_NEUTRAL


def get_stake_multiplier(n: int = LOOKBACK_N) -> float:
    """
    Oblicza stake_multiplier łącząc dwa poziomy kalibracji:

    1. Forma Bota (3 kupony) — priorytet gdy wyraźny sygnał (≠ 1.0)
    2. Hit-rate długoterminowy (ostatnie n kuponów) — fallback

    Zwraca float (zazwyczaj 0.5 / 0.7 / 1.0 / 1.1 / 1.2).
    Nigdy nie zwraca None — minimalny zwrot to MULTIPLIER_NEUTRAL.
    """
    # Priorytet: Forma Bota (ostatnie 3 kupony)
    forma = get_forma_multiplier()
    if forma != MULTIPLIER_NEUTRAL:
        return forma

    # Fallback: hit-rate na ostatnich n kuponach
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT status FROM coupons WHERE status IN ('WON','LOST') ORDER BY created_at DESC, id DESC LIMIT ?",
            (n,),
        ).fetchall()
        conn.close()
    except Exception:
        return MULTIPLIER_NEUTRAL

    if not rows:
        return MULTIPLIER_NEUTRAL

    won      = sum(1 for r in rows if r["status"] == "WON")
    hit_rate = won / len(rows)

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

    forma_mult = get_forma_multiplier()
    forma_note = (
        "3x WIN z rzędu — lekka agresja"       if forma_mult > 1.0 else
        "3x LOSE z rzędu — ochrona kapitału"   if forma_mult < 1.0 else
        "Forma mieszana"
    )

    return {
        "n":           total,
        "won":         won,
        "lost":        total - won,
        "hit_rate":    round(hit_rate, 3),
        "avg_roi_pct": round(avg_roi, 1),
        "multiplier":  multiplier,
        "forma_multiplier": forma_mult,
        "note": (
            "Forma wysoka — gramy odważniej"        if multiplier > 1 else
            "Forma niska — minimalizujemy straty"   if multiplier < 1 else
            "Forma neutralna"
        ),
        "forma_note": forma_note,
    }
