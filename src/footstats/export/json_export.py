"""
json_export.py – Eksport danych kuponów i wyników do formatu JSON.

Wersja: v3.2
Umożliwia eksport:
  - Historii kuponów z wynikami
  - Statystyk bankrolla
  - Raportu dziennego
"""

import json
import sqlite3
from datetime import datetime
from typing import Any
from pathlib import Path


def _get_db_path() -> Path:
    """Zwraca ścieżkę do bazy danych."""
    return Path(__file__).parents[3] / "data" / "footstats_backtest.db"


def _connect_db() -> sqlite3.Connection:
    """Nawiązuje połączenie z bazą danych."""
    db_path = _get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def export_coupons_to_json(
    output_path: str | Path = "data/coupons_export.json",
    status_filter: str | None = None,
) -> dict[str, Any]:
    """
    Eksportuje kupony do formatu JSON.

    Args:
        output_path: Ścieżka do pliku wyjściowego
        status_filter: Filtruj po statusie (DRAFT, ACTIVE, WIN, LOSE) lub None dla wszystkich

    Returns:
        Słownik z metadanymi eksportu
    """
    output_path = Path(output_path)
    db = _connect_db()
    cursor = db.cursor()

    query = "SELECT coupon_id, date_created, status, legs_count, total_odds, stake_pln, result FROM coupons"
    params = []

    if status_filter:
        query += " WHERE status = ?"
        params.append(status_filter)

    query += " ORDER BY date_created DESC"

    cursor.execute(query, params)
    rows = cursor.fetchall()

    coupons = []
    for row in rows:
        coupon_id, date_created, status, legs_count, total_odds, stake_pln, result = row
        coupons.append({
            "coupon_id": coupon_id,
            "date_created": date_created,
            "status": status,
            "legs_count": legs_count,
            "total_odds": float(total_odds) if total_odds else None,
            "stake_pln": float(stake_pln) if stake_pln else None,
            "result": result,
        })

    export_data = {
        "metadata": {
            "exported_at": datetime.now().isoformat(),
            "total_coupons": len(coupons),
            "status_filter": status_filter,
        },
        "coupons": coupons,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)

    db.close()

    return {
        "success": True,
        "file": str(output_path),
        "total_records": len(coupons),
        "status_filter": status_filter,
    }


def export_bankroll_history_to_json(
    output_path: str | Path = "data/bankroll_history.json",
) -> dict[str, Any]:
    """
    Eksportuje historię bankrolla do JSON.

    Returns:
        Słownik z metadanymi eksportu
    """
    output_path = Path(output_path)
    db = _connect_db()
    cursor = db.cursor()

    cursor.execute(
        "SELECT timestamp, bankroll_pln, total_stake, total_win, total_loss "
        "FROM bankroll_state "
        "ORDER BY timestamp DESC"
    )
    rows = cursor.fetchall()

    states = []
    for row in rows:
        timestamp, bankroll_pln, total_stake, total_win, total_loss = row
        states.append({
            "timestamp": timestamp,
            "bankroll_pln": float(bankroll_pln) if bankroll_pln else None,
            "total_stake": float(total_stake) if total_stake else None,
            "total_win": float(total_win) if total_win else None,
            "total_loss": float(total_loss) if total_loss else None,
        })

    export_data = {
        "metadata": {
            "exported_at": datetime.now().isoformat(),
            "total_records": len(states),
        },
        "bankroll_history": states,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)

    db.close()

    return {
        "success": True,
        "file": str(output_path),
        "total_records": len(states),
    }


def export_ai_feedback_to_json(
    output_path: str | Path = "data/ai_feedback_export.json",
) -> dict[str, Any]:
    """
    Eksportuje feedback AI (wnioski z porażek) do JSON.

    Returns:
        Słownik z metadanymi eksportu
    """
    output_path = Path(output_path)
    db = _connect_db()
    cursor = db.cursor()

    cursor.execute(
        "SELECT feedback_id, coupon_id, lesson_text, ai_model, created_at "
        "FROM ai_feedback "
        "ORDER BY created_at DESC"
    )
    rows = cursor.fetchall()

    feedbacks = []
    for row in rows:
        feedback_id, coupon_id, lesson_text, ai_model, created_at = row
        feedbacks.append({
            "feedback_id": feedback_id,
            "coupon_id": coupon_id,
            "lesson": lesson_text,
            "ai_model": ai_model,
            "created_at": created_at,
        })

    export_data = {
        "metadata": {
            "exported_at": datetime.now().isoformat(),
            "total_feedback_entries": len(feedbacks),
        },
        "ai_feedback": feedbacks,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)

    db.close()

    return {
        "success": True,
        "file": str(output_path),
        "total_records": len(feedbacks),
    }


def export_daily_summary_to_json(
    output_path: str | Path = "data/daily_summary.json",
) -> dict[str, Any]:
    """
    Eksportuje dzienny raport do JSON.

    Returns:
        Słownik z metadanymi eksportu
    """
    db = _connect_db()
    cursor = db.cursor()

    # Pobierz dzisiejsze kupony
    cursor.execute(
        "SELECT COUNT(*), SUM(total_odds), SUM(stake_pln) "
        "FROM coupons "
        "WHERE DATE(date_created) = DATE('now')"
    )
    today_stats = cursor.fetchone()

    # Pobierz ostatnią historię bankrolla
    cursor.execute(
        "SELECT bankroll_pln, total_stake, total_win, total_loss "
        "FROM bankroll_state "
        "ORDER BY timestamp DESC "
        "LIMIT 1"
    )
    bankroll_latest = cursor.fetchone()

    export_data = {
        "metadata": {
            "exported_at": datetime.now().isoformat(),
            "date": datetime.now().strftime("%Y-%m-%d"),
        },
        "today_summary": {
            "coupons_created": today_stats[0] or 0,
            "avg_odds": float(today_stats[1] / today_stats[0]) if today_stats[0] else 0,
            "total_stake": float(today_stats[2]) if today_stats[2] else 0,
        },
        "current_bankroll": {
            "bankroll_pln": float(bankroll_latest[0]) if bankroll_latest and bankroll_latest[0] else None,
            "total_stake": float(bankroll_latest[1]) if bankroll_latest and bankroll_latest[1] else None,
            "total_win": float(bankroll_latest[2]) if bankroll_latest and bankroll_latest[2] else None,
            "total_loss": float(bankroll_latest[3]) if bankroll_latest and bankroll_latest[3] else None,
        } if bankroll_latest else None,
    }

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)

    db.close()

    return {
        "success": True,
        "file": str(output_path),
    }
