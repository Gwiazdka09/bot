"""
weekly_report.py – tygodniowy raport FootStats z accuracy/ROI.

Pobiera statystyki kuponów z ostatnich 7 dni z bazy SQLite,
buduje prompt dla Groq i opcjonalnie wysyła raport przez Telegram.

Użycie CLI:
    python -m footstats.weekly_report
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from footstats.utils.console import console

_DEFAULT_DB = Path(__file__).parents[2] / "data" / "footstats_backtest.db"


def get_stats_7_dni(db_path: Path = None) -> dict:
    """Statystyki kuponów z ostatnich 7 dni.

    Zwraca słownik z kluczami:
        total, won, lost, partial, void,
        accuracy_pct, total_stake, total_payout, roi_pct
    """
    path = db_path or _DEFAULT_DB
    _empty = {
        "total": 0,
        "won": 0,
        "lost": 0,
        "partial": 0,
        "void": 0,
        "accuracy_pct": 0.0,
        "total_stake": 0.0,
        "total_payout": 0.0,
        "roi_pct": 0.0,
    }

    if not path.exists():
        return _empty

    cutoff = (datetime.now() - timedelta(days=7)).isoformat()
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT status, stake_pln, payout_pln FROM coupons WHERE created_at >= ?",
            (cutoff,),
        ).fetchall()
    except sqlite3.OperationalError:
        return _empty
    finally:
        conn.close()

    counts: dict[str, int] = {}
    total_stake = 0.0
    total_payout = 0.0
    for r in rows:
        st = r["status"]
        counts[st] = counts.get(st, 0) + 1
        total_stake += r["stake_pln"] or 0.0
        total_payout += r["payout_pln"] or 0.0

    total = len(rows)
    won = counts.get("WON", 0)
    lost = counts.get("LOST", 0)
    partial = counts.get("PARTIAL", 0)
    decided = won + lost + partial
    accuracy = round(won / decided * 100, 1) if decided > 0 else 0.0
    roi = round((total_payout - total_stake) / total_stake * 100, 1) if total_stake > 0 else 0.0

    return {
        "total": total,
        "won": won,
        "lost": lost,
        "partial": partial,
        "void": counts.get("VOID", 0),
        "accuracy_pct": accuracy,
        "total_stake": round(total_stake, 2),
        "total_payout": round(total_payout, 2),
        "roi_pct": roi,
    }


def build_raport_prompt(stats: dict) -> str:
    """Buduje prompt dla Groq na podstawie statystyk tygodniowych."""
    return (
        f"Analiza tygodniowa FootStats:\n"
        f"- Kupony: {stats['total']} | WON: {stats['won']} | LOST: {stats['lost']}\n"
        f"- Accuracy: {stats['accuracy_pct']}% | ROI: {stats['roi_pct']}%\n"
        f"- Stawka: {stats['total_stake']} PLN | Wyplata: {stats['total_payout']} PLN\n\n"
        "Ocen wyniki, wskazz wzorce bledow i podaj 2-3 rekomendacje poprawy strategii typowania."
    )


def run_weekly_report(
    api_key_groq: str | None = None,
    send_telegram: bool = True,
    db_path: Path | None = None,
) -> dict:
    """Uruchamia pełny raport tygodniowy.

    Pobiera statystyki, opcjonalnie analizuje przez Groq i wysyła na Telegram.
    Zawsze zwraca słownik stats (+ klucz 'groq_analysis').
    """
    stats = get_stats_7_dni(db_path=db_path)

    console.print(
        f"[cyan]Weekly Report: {stats['total']} kuponow, "
        f"accuracy={stats['accuracy_pct']}%, ROI={stats['roi_pct']}%[/cyan]"
    )

    groq_analysis: str | None = None
    if api_key_groq:
        try:
            from groq import Groq  # type: ignore

            client = Groq(api_key=api_key_groq)
            prompt = build_raport_prompt(stats)
            resp = client.chat.completions.create(
                model="meta-llama/llama-4-scout-17b-16e-instruct",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
            )
            groq_analysis = resp.choices[0].message.content
            console.print(f"[green]Groq analiza:[/green]\n{groq_analysis}")
        except Exception as e:
            console.print(f"[yellow]Groq unavailable: {e}[/yellow]")

    stats["groq_analysis"] = groq_analysis

    if send_telegram and groq_analysis:
        try:
            from footstats.utils.telegram_notify import send_message  # type: ignore

            msg = f"Raport tygodniowy FootStats\n\n{groq_analysis}"
            send_message(msg)
        except Exception:
            pass

    return stats


if __name__ == "__main__":
    import os

    from dotenv import load_dotenv  # type: ignore

    load_dotenv()
    run_weekly_report(api_key_groq=os.getenv("GROQ_API_KEY"))
