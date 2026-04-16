"""
post_match_analyzer.py – Analiza porażek AI (Pętla Feedbacku "Kij vs Ciastko")

Dla każdego rozliczonego meczu z tip_correct=0 (porażka), który nie ma jeszcze
wpisu w ai_feedback, odpytuje Groq o przyczynę błędu i zapisuje wniosek do DB.

Użycie:
    python -m footstats.ai.post_match_analyzer          # analiza ostatnich 14 dni
    python -m footstats.ai.post_match_analyzer --dni 30 # analiza ostatnich 30 dni
    python -m footstats.ai.post_match_analyzer --dry    # tylko pokaż co by przeanalizował
"""

import json
import logging
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

_PROMPT_ANALIZA = """
Jesteś analitykiem piłkarskim oceniającym dlaczego AI postawiła zły typ.

Mecz: {home} vs {away} ({league}, {date})
Typ AI: {tip} (pewność: {confidence}%)
Uzasadnienie AI: {reasoning}
Wynik meczu: {actual_result}
Czynniki analizowane: {factors}

W 2–3 zdaniach odpowiedz PO POLSKU:
1. Jaki był GŁÓWNY powód błędu? (np. forma, kontuzje, xG, kurs, niedoszacowanie rywala)
2. Czego AI NIE uwzględniła lub przeceniła?
3. Krótka rekomendacja na przyszłość (1 zdanie).

Odpowiedz TYLKO tekstem bez nagłówków ani wypunktowania.
""".strip()


def _pobierz_porazki(days_back: int) -> list[dict]:
    """Zwraca mecze tip_correct=0 bez wpisu w ai_feedback (nie przeanalizowane)."""
    from footstats.core.backtest import _connect
    cutoff = (datetime.now() - timedelta(days=days_back)).isoformat()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT p.id, p.match_date, p.team_home, p.team_away, p.league,
                   p.ai_tip, p.ai_confidence, p.ai_reasoning,
                   p.actual_result, p.factors
            FROM predictions p
            LEFT JOIN ai_feedback f ON f.match_id = p.id
            WHERE p.tip_correct = 0
              AND p.created_at >= ?
              AND f.id IS NULL
            ORDER BY p.match_date DESC
            """,
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


def _zapisz_feedback(match_id: int, prediction_details: dict, reason: str) -> None:
    """Zapisuje analizę do tabeli ai_feedback."""
    from footstats.core.backtest import _connect
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO ai_feedback (match_id, prediction_details, reason_for_failure)
            VALUES (?, ?, ?)
            """,
            (match_id, json.dumps(prediction_details, ensure_ascii=False), reason),
        )


def pobierz_ostatnie_wnioski(n: int = 3) -> list[str]:
    """
    Zwraca n ostatnich wniosków z ai_feedback.
    Używane przez daily_agent do wzbogacenia kontekstu Groq.
    """
    from footstats.core.backtest import _connect
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT f.reason_for_failure, p.team_home, p.team_away, p.match_date
            FROM ai_feedback f
            JOIN predictions p ON p.id = f.match_id
            ORDER BY f.created_at DESC
            LIMIT ?
            """,
            (n,),
        ).fetchall()
    return [
        f"[{r['match_date'][:10]}] {r['team_home']} vs {r['team_away']}: {r['reason_for_failure']}"
        for r in rows
    ]


def analizuj_porazki(days_back: int = 14, dry_run: bool = False) -> dict:
    """
    Główna funkcja. Analizuje nieprzetworzone porażki i zapisuje wnioski.
    Zwraca {"analyzed": N, "skipped": M, "errors": K}.
    """
    from footstats.ai.client import zapytaj_ai

    porazki = _pobierz_porazki(days_back)
    stats = {"analyzed": 0, "skipped": 0, "errors": 0}

    if not porazki:
        print("[PostMatchAnalyzer] Brak nowych porażek do przeanalizowania.")
        return stats

    print(f"[PostMatchAnalyzer] Porażki do analizy: {len(porazki)}")

    for p in porazki:
        label = f"{p['team_home']} vs {p['team_away']} ({p['match_date'][:10]})"
        if dry_run:
            print(f"  [DRY] {label} — tip={p['ai_tip']} wynik={p['actual_result']}")
            stats["analyzed"] += 1
            continue

        prompt = _PROMPT_ANALIZA.format(
            home=p["team_home"],
            away=p["team_away"],
            league=p.get("league", "?"),
            date=p["match_date"][:10],
            tip=p["ai_tip"],
            confidence=p["ai_confidence"],
            reasoning=p.get("ai_reasoning", "brak"),
            actual_result=p["actual_result"],
            factors=p.get("factors", "[]"),
        )

        try:
            reason = zapytaj_ai(prompt, max_tokens=300)
            reason = reason.strip()

            prediction_details = {
                "tip":        p["ai_tip"],
                "confidence": p["ai_confidence"],
                "odds":       None,
                "result":     p["actual_result"],
            }
            _zapisz_feedback(p["id"], prediction_details, reason)
            print(f"  [OK] {label} → {reason[:80]}…")
            stats["analyzed"] += 1
        except Exception as e:
            log.error("Błąd analizy ID=%s: %s", p["id"], e)
            print(f"  [ERR] {label} → {e}")
            stats["errors"] += 1

    print(
        f"\n[PostMatchAnalyzer] Przeanalizowano: {stats['analyzed']} | "
        f"Pominięto: {stats['skipped']} | Błędy: {stats['errors']}"
    )
    return stats


if __name__ == "__main__":
    import argparse
    import sys
    logging.basicConfig(level=logging.WARNING)

    from footstats.core.backtest import init_db
    init_db()

    parser = argparse.ArgumentParser(description="FootStats Post-Match Analyzer")
    parser.add_argument("--dry",  action="store_true", help="Tylko pokaż bez zapisu")
    parser.add_argument("--dni",  type=int, default=14, help="Dni wstecz (domyślnie 14)")
    args = parser.parse_args()

    analizuj_porazki(days_back=args.dni, dry_run=args.dry)
