"""
backtest_engine.py – Silnik backtestowania historycznych meczów z feedback do RAG.

Proces:
1. Pobiera zakończone mecze z API-Football dla zadanego zakresu dat
2. Dla każdego meczu uruchamia ai_analiza_pewniaczki() (symulacja historyczna)
3. Porównuje tip AI z rzeczywistym wynikiem (_oblicz_tip_correct)
4. WIN → zapisuje do predictions jako trafiony
5. LOSE → generuje lekcję RAG i zapisuje do ai_feedback

Użycie:
    python -m footstats.core.backtest_engine --days 7
    python scripts/run_backtest.py --days 7
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
#  Langfuse — opcjonalny tracing (jeśli klucze w .env)
# ---------------------------------------------------------------------------

_langfuse = None


def _init_langfuse():
    """Inicjalizuje Langfuse jeśli klucze dostępne. Bezpieczne — nie rzuca wyjątku."""
    global _langfuse
    if _langfuse is not None:
        return _langfuse
    try:
        pk = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
        sk = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
        if pk and sk:
            from langfuse import Langfuse
            _langfuse = Langfuse(
                public_key=pk,
                secret_key=sk,
                host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
            )
            logger.info("Langfuse aktywny — trace'y będą logowane")
        else:
            _langfuse = False  # sentinel: brak kluczy
    except Exception as e:
        logger.warning(f"Langfuse niedostępny: {e}")
        _langfuse = False
    return _langfuse


class _LangfuseTrace:
    """Context manager do opcjonalnego trace'owania. No-op gdy brak Langfuse."""

    def __init__(self, name: str, metadata: dict | None = None):
        self.name = name
        self.metadata = metadata or {}
        self._trace = None

    def __enter__(self):
        lf = _init_langfuse()
        if lf and lf is not False:
            try:
                self._trace = lf.trace(name=self.name, metadata=self.metadata)
            except Exception:
                pass
        return self

    def __exit__(self, *args):
        pass

    def event(self, name: str, **kwargs):
        if self._trace:
            try:
                self._trace.event(name=name, metadata=kwargs)
            except Exception:
                pass


# ---------------------------------------------------------------------------
#  API-Football — pobieranie historycznych wyników
# ---------------------------------------------------------------------------

def _get_api_client():
    """Zwraca skonfigurowany APIFootball client lub None."""
    from footstats.config import ENV_APISPORTS
    key = os.getenv(ENV_APISPORTS, "").strip()
    if not key:
        logger.error("Brak APISPORTS_KEY w .env — backtest wymaga API-Football")
        return None
    from footstats.scrapers.api_football import APIFootball
    return APIFootball(key)


def _fetch_fixtures_for_date(client, date_str: str) -> list[dict]:
    """
    Pobiera zakończone mecze z API-Football dla konkretnej daty.
    Zwraca listę dict z kluczami: fixture_id, home, away, league, league_id,
    goals_home, goals_away, score_str, date, time.
    """
    from footstats.scrapers.api_football import _APISPORTS_LIGI
    from footstats.utils.helpers import _s

    dane = client._get("/fixtures", params={"date": date_str, "status": "FT"})
    if not dane:
        return []

    matches = []
    tracked_ids = set(_APISPORTS_LIGI.keys())

    for m in dane.get("response", []):
        league_id = m.get("league", {}).get("id")
        # Filtruj do śledzonych lig — oszczędzamy tokeny Groq
        if league_id not in tracked_ids:
            continue

        fixture = m.get("fixture", {})
        teams = m.get("teams", {})
        goals = m.get("goals", {})
        gh = goals.get("home")
        ga = goals.get("away")
        if gh is None or ga is None:
            continue

        home = _s(teams.get("home", {}).get("name", ""))
        away = _s(teams.get("away", {}).get("name", ""))
        league_name = _APISPORTS_LIGI.get(league_id, {}).get("nazwa", str(league_id))
        date_full = fixture.get("date", "")

        matches.append({
            "fixture_id": fixture.get("id"),
            "home": home,
            "away": away,
            "league": league_name,
            "league_id": league_id,
            "goals_home": int(gh),
            "goals_away": int(ga),
            "score_str": f"{gh}-{ga}",
            "date": date_str,
            "time": date_full[11:16] if len(date_full) > 16 else "00:00",
        })

    logger.info(f"[{date_str}] Pobrano {len(matches)} zakończonych meczów z śledzonych lig")
    return matches


def _fixture_to_wynik(fixture: dict) -> dict:
    """
    Konwertuje fixture z API-Football do formatu kompatybilnego
    z ai_analiza_pewniaczki() (format Bzzoiro/quick_picks).
    """
    return {
        "gospodarz": fixture["home"],
        "goscie": fixture["away"],
        "liga": fixture["league"],
        "data": fixture["date"],
        "godzina": fixture["time"],
        "pw": 50.0,   # placeholder — Groq decyduje sam
        "pr": 25.0,
        "pp": 25.0,
        "o25": 50.0,
        "bt": 45.0,
        "odds": {},
        "metoda": "BACKTEST",
        "typy": [("1", 0.50), ("X", 0.25), ("2", 0.25)],
    }


# ---------------------------------------------------------------------------
#  Symulacja analizy AI
# ---------------------------------------------------------------------------

def _run_ai_analysis(wyniki_batch: list[dict], stawka: float = 5.0) -> dict | None:
    """
    Wywołuje ai_analiza_pewniaczki() na batchu meczów.
    Dodaje flagę [BACKTEST] do kontekstu RAG.
    Zwraca dict z top3, kupon_a, kupon_b lub None.

    Error handling: obsługuje 429 (Rate Limit) gracefully — czeka i loguje do Langfuse zamiast wywalać.
    """
    if not wyniki_batch:
        return None

    try:
        from footstats.ai.analyzer import ai_analiza_pewniaczki
        result = ai_analiza_pewniaczki(
            wyniki=wyniki_batch,
            pobierz_forme=False,  # historyczne — forma nieadekwatna
            stawka=stawka,
        )
        return result
    except Exception as e:
        err_str = str(e).lower()
        # 429 / Rate Limit — czekaj i loguj, nie wywalaj
        if "429" in err_str or "rate" in err_str or "too many requests" in err_str:
            logger.warning(f"[429] Groq rate limit — czekamy 30s i pomijamy batch: {e}")
            lf = _init_langfuse()
            if lf and lf is not False:
                try:
                    lf.trace(name="backtest_rate_limit",
                             metadata={"batch_size": len(wyniki_batch), "error": str(e)}).event(
                        name="groq_429_hit")
                except Exception:
                    pass
            time.sleep(30)  # Czekaj przed następnym batchemm
            return None
        else:
            logger.error(f"Błąd ai_analiza_pewniaczki (nie-rate-limit): {e}")
            return None


def _extract_tips_from_analysis(analysis: dict) -> list[dict]:
    """
    Wyciąga poszczególne tipy z odpowiedzi AI.
    Zwraca listę: [{"mecz": str, "typ": str, "kurs": float, "pewnosc": int, "source": str}]
    """
    tips = []
    _TYP_NORM = {"Over": "Over 2.5", "Under": "Under 2.5",
                 "OVER": "Over 2.5", "UNDER": "Under 2.5"}

    for item in analysis.get("top3") or []:
        tips.append({
            "mecz": item.get("mecz", ""),
            "typ": _TYP_NORM.get(item.get("typ", ""), item.get("typ", "")),
            "kurs": item.get("kurs"),
            "pewnosc": item.get("pewnosc_pct", 65),
            "source": "top3",
        })

    for kupon_key in ("kupon_a", "kupon_b"):
        kupon = analysis.get(kupon_key) or {}
        for item in kupon.get("zdarzenia") or []:
            tips.append({
                "mecz": item.get("mecz", ""),
                "typ": _TYP_NORM.get(item.get("typ", ""), item.get("typ", "")),
                "kurs": item.get("kurs"),
                "pewnosc": item.get("pewnosc_pct", 65),
                "source": kupon_key,
            })

    return tips


def _match_tip_to_fixture(tip: dict, fixtures: list[dict]) -> dict | None:
    """Dopasowuje tip AI (np. 'Bayern vs Dortmund') do fixture z API-Football."""
    mecz_lower = tip.get("mecz", "").lower()
    for f in fixtures:
        if f["home"].lower() in mecz_lower or f["away"].lower() in mecz_lower:
            return f
    return None


# ---------------------------------------------------------------------------
#  Pętla porównania + RAG feedback
# ---------------------------------------------------------------------------

def _evaluate_tip(tip: dict, fixture: dict) -> dict:
    """
    Porównuje tip AI z wynikiem meczu.
    Zwraca dict z wynikiem ewaluacji.
    """
    from footstats.core.backtest import _oblicz_tip_correct

    score_str = fixture["score_str"]
    ai_tip = tip["typ"]
    kurs = tip.get("kurs") or 1.0

    tip_correct = _oblicz_tip_correct(ai_tip, score_str)
    is_win = tip_correct == 1

    return {
        "fixture_id": fixture["fixture_id"],
        "home": fixture["home"],
        "away": fixture["away"],
        "league": fixture["league"],
        "date": fixture["date"],
        "score": score_str,
        "ai_tip": ai_tip,
        "kurs": kurs,
        "pewnosc": tip.get("pewnosc", 65),
        "tip_correct": tip_correct,
        "is_win": is_win,
        "source": tip.get("source", ""),
    }


def _save_prediction_and_result(eval_result: dict, stawka: float) -> int | None:
    """Zapisuje predykcję + wynik do tabeli predictions. Zwraca ID."""
    from footstats.core.backtest import save_prediction, update_result

    try:
        pred_id = save_prediction(
            match_date=eval_result["date"],
            team_home=eval_result["home"],
            team_away=eval_result["away"],
            ai_tip=eval_result["ai_tip"],
            ai_confidence=eval_result["pewnosc"],
            league=eval_result["league"],
            odds=eval_result["kurs"],
            kupon_type=f"backtest_{eval_result['source']}",
            prompt_version="backtest_v1",
        )
        update_result(pred_id, eval_result["score"])
        return pred_id
    except Exception as e:
        logger.error(f"Błąd zapisu prediction: {e}")
        return None


def _generate_rag_lesson(eval_result: dict) -> str:
    """Generuje lekcję RAG z przegranej predykcji (bez Groq — deterministycznie)."""
    home = eval_result["home"]
    away = eval_result["away"]
    tip = eval_result["ai_tip"]
    score = eval_result["score"]
    league = eval_result["league"]
    pewnosc = eval_result["pewnosc"]

    # Analiza dlaczego pudło
    gh, ga = [int(x) for x in score.split("-")]
    total = gh + ga

    reason_parts = []
    tip_upper = tip.upper()

    if tip_upper in ("1", "X", "2"):
        if gh > ga:
            actual = "1"
        elif gh == ga:
            actual = "X"
        else:
            actual = "2"
        reason_parts.append(
            f"Typowaliśmy {tip} ({pewnosc}% pewności), wynik {score} → {actual}."
        )
    elif "OVER" in tip_upper:
        threshold = 2.5
        if "1.5" in tip:
            threshold = 1.5
        elif "3.5" in tip:
            threshold = 3.5
        reason_parts.append(
            f"Typowaliśmy {tip}, ale padło {total} goli (próg {threshold})."
        )
    elif "BTTS" in tip_upper:
        btts = gh > 0 and ga > 0
        reason_parts.append(
            f"Typowaliśmy BTTS={'Tak' if 'NO' not in tip_upper else 'Nie'}, "
            f"wynik {score} → BTTS={'Tak' if btts else 'Nie'}."
        )

    reason_parts.append(f"Liga: {league}. Zweryfikuj formę drużyn przed typowaniem w tej lidze.")

    return f"[BACKTEST] {home} vs {away}: " + " ".join(reason_parts)


def _save_rag_feedback(pred_id: int, eval_result: dict, lesson: str):
    """Zapisuje lekcję do ai_feedback (kompatybilnie z post_match_analyzer)."""
    from footstats.core.backtest import _connect

    prediction_details = json.dumps({
        "tip": eval_result["ai_tip"],
        "confidence": eval_result["pewnosc"],
        "odds": eval_result["kurs"],
        "result": eval_result["score"],
        "source": "backtest",
    }, ensure_ascii=False)

    with _connect() as conn:
        conn.execute(
            """INSERT INTO ai_feedback (match_id, prediction_details, reason_for_failure)
               VALUES (?, ?, ?)""",
            (pred_id, prediction_details, lesson),
        )


# ---------------------------------------------------------------------------
#  Główna pętla backtestowa
# ---------------------------------------------------------------------------

def backtest_period(
    days_back: int = 7,
    stawka: float = 5.0,
    batch_size: int = 5,
    dry_run: bool = False,
) -> dict:
    """
    Backtestuje ostatnie N dni.

    Args:
        days_back: ile dni wstecz (domyślnie 7)
        stawka: stawka PLN na zakład (domyślnie 5)
        batch_size: ile meczów w jednym batchu do Groq (domyślnie 10)
        dry_run: jeśli True — nie zapisuje do DB, tylko wyświetla

    Returns:
        {
            "days_analyzed": int,
            "total_fixtures": int,
            "total_tips": int,
            "wins": int,
            "losses": int,
            "unknown": int,
            "accuracy_pct": float,
            "theoretical_profit_pln": float,
            "new_rag_lessons": int,
            "details": [...]
        }
    """
    client = _get_api_client()
    if not client:
        return {"error": "Brak APISPORTS_KEY — ustaw klucz w .env"}

    today = datetime.now()
    stats = {
        "days_analyzed": 0,
        "total_fixtures": 0,
        "total_tips": 0,
        "wins": 0,
        "losses": 0,
        "unknown": 0,
        "accuracy_pct": 0.0,
        "theoretical_profit_pln": 0.0,
        "new_rag_lessons": 0,
        "details": [],
    }

    for day_offset in range(1, days_back + 1):
        date = today - timedelta(days=day_offset)
        date_str = date.strftime("%Y-%m-%d")

        with _LangfuseTrace("backtest_day", {"date": date_str, "stawka": stawka}) as trace:

            # Zlicz dzień na START (niezależnie od liczby meczów)
            stats["days_analyzed"] += 1

            # 1. Pobierz zakończone mecze
            fixtures = _fetch_fixtures_for_date(client, date_str)
            if not fixtures:
                logger.info(f"[{date_str}] Brak meczów — pomijam")
                continue
            stats["total_fixtures"] += len(fixtures)
            trace.event("fixtures_fetched", count=len(fixtures))

            # 2. Deduplikuj mecze na podstawie fixture_id (usuwamy duplikaty z API)
            seen_fixture_ids = set()
            unique_fixtures = []
            for f in fixtures:
                fid = f.get("fixture_id")
                if fid not in seen_fixture_ids:
                    seen_fixture_ids.add(fid)
                    unique_fixtures.append(f)

            if len(unique_fixtures) < len(fixtures):
                logger.info(f"[{date_str}] Usunięto {len(fixtures) - len(unique_fixtures)} duplikatów. "
                           f"Zostały {len(unique_fixtures)} unikalnych meczów.")

            # Konwertuj do formatu Bzzoiro i wyślij do AI w batchach
            wyniki_all = [_fixture_to_wynik(f) for f in unique_fixtures]

            for batch_start in range(0, len(wyniki_all), batch_size):
                batch = wyniki_all[batch_start:batch_start + batch_size]
                batch_fixtures = fixtures[batch_start:batch_start + batch_size]

                if dry_run:
                    for f in batch_fixtures:
                        print(f"  [DRY] {f['date']} {f['home']} vs {f['away']} → {f['score_str']}")
                    continue

                # Throttle — Groq rate limit
                if batch_start > 0:
                    time.sleep(5)

                trace.event("ai_analysis_start", batch_size=len(batch))
                analysis = _run_ai_analysis(batch, stawka=stawka)

                if not analysis or "_raw" in analysis:
                    logger.warning(f"[{date_str}] AI nie zwróciło JSON — pomijam batch")
                    trace.event("ai_analysis_failed")
                    continue

                # 3. Wyciągnij tipy i ewaluuj
                tips = _extract_tips_from_analysis(analysis)
                trace.event("tips_extracted", count=len(tips))

                for tip in tips:
                    matched_fixture = _match_tip_to_fixture(tip, batch_fixtures)
                    if not matched_fixture:
                        stats["unknown"] += 1
                        continue

                    eval_result = _evaluate_tip(tip, matched_fixture)
                    stats["total_tips"] += 1

                    if eval_result["tip_correct"] is None:
                        stats["unknown"] += 1
                        continue

                    # 4. Zapisz predykcję + wynik
                    pred_id = _save_prediction_and_result(eval_result, stawka)

                    if eval_result["is_win"]:
                        stats["wins"] += 1
                        profit = stawka * (eval_result["kurs"] - 1) * 0.88  # po 12% podatku
                        stats["theoretical_profit_pln"] += profit
                        trace.event("tip_win", tip=eval_result["ai_tip"],
                                    match=f"{eval_result['home']} vs {eval_result['away']}")
                    else:
                        stats["losses"] += 1
                        stats["theoretical_profit_pln"] -= stawka
                        trace.event("tip_loss", tip=eval_result["ai_tip"],
                                    match=f"{eval_result['home']} vs {eval_result['away']}")

                        # 5. RAG feedback dla pudeł
                        if pred_id:
                            lesson = _generate_rag_lesson(eval_result)
                            _save_rag_feedback(pred_id, eval_result, lesson)
                            stats["new_rag_lessons"] += 1

                    stats["details"].append(eval_result)

    # Oblicz accuracy
    decided = stats["wins"] + stats["losses"]
    if decided > 0:
        stats["accuracy_pct"] = round(stats["wins"] / decided * 100, 1)

    stats["theoretical_profit_pln"] = round(stats["theoretical_profit_pln"], 2)
    return stats


# ---------------------------------------------------------------------------
#  CLI
# ---------------------------------------------------------------------------

def print_report(stats: dict):
    """Wyświetla czytelny raport backtestu."""
    if "error" in stats:
        print(f"\n❌ BŁĄD: {stats['error']}")
        return

    print("\n" + "=" * 60)
    print("  📊 RAPORT BACKTESTU FootStats AI")
    print("=" * 60)
    print(f"  Dni przeanalizowanych:    {stats['days_analyzed']}")
    print(f"  Meczów z API-Football:    {stats['total_fixtures']}")
    print(f"  Tipów AI wygenerowanych:  {stats['total_tips']}")
    print(f"  Niedopasowanych:          {stats['unknown']}")
    print("-" * 60)
    print(f"  ✅ Trafione (WIN):        {stats['wins']}")
    print(f"  ❌ Pudła (LOSE):          {stats['losses']}")
    print(f"  🎯 AI Skuteczność:        {stats['accuracy_pct']}%")
    print("-" * 60)

    pnl = stats["theoretical_profit_pln"]
    pnl_icon = "📈" if pnl >= 0 else "📉"
    print(f"  {pnl_icon} Teoretyczny Zysk/Strata: {pnl:+.2f} PLN")
    print(f"  📚 Nowych lekcji w RAG:   {stats['new_rag_lessons']}")
    print("=" * 60)

    # Szczegóły per tip
    if stats["details"]:
        print("\n  Szczegóły tipów:")
        for d in stats["details"]:
            icon = "✅" if d["is_win"] else "❌"
            print(
                f"    {icon} [{d['date']}] {d['home']} vs {d['away']} "
                f"({d['score']}) — tip: {d['ai_tip']} @{d['kurs']}"
            )
    print()


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="FootStats Backtest Engine")
    parser.add_argument("--days", type=int, default=7, help="Ile dni wstecz (domyślnie 7)")
    parser.add_argument("--stawka", type=float, default=5.0, help="Stawka PLN (domyślnie 5)")
    parser.add_argument("--batch", type=int, default=5, help="Batch size dla Groq (domyślnie 5)")
    parser.add_argument("--dry-run", action="store_true", help="Bez zapisu do DB")
    args = parser.parse_args()

    result = backtest_period(
        days_back=args.days,
        stawka=args.stawka,
        batch_size=args.batch,
        dry_run=args.dry_run,
    )
    print_report(result)
