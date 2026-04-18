"""
coupon_settlement.py – Rozliczanie ACTIVE kuponów z fallback na FlashScore.

Gdy API-Football brakuje wyniku, fallback na scraper FlashScore.
Po rozliczeniu:
  - WIN: zaktualizuj bankroll
  - LOSE: wyślij do post_match_analyzer (RAG feedback)

Użycie:
    from footstats.core.coupon_settlement import settle_active_coupons
    settle_active_coupons(days_back=3, dry_run=False, verbose=True)
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)


def _oblicz_tip_correct(tip: str, wynik: str) -> int | None:
    """
    Sprawdza czy tip jest trafiony (1) czy nie (0) na podstawie wyniku.

    tip: np. "Over 2.5", "1", "Home", "2-2 Draw", itp.
    wynik: np. "2-1"

    Returns: 1 (trafiony), 0 (nie trafiony), None (nie można ocenić)
    """
    if not wynik or "-" not in wynik:
        return None

    try:
        home_g, away_g = map(int, wynik.split("-"))
        total_goals = home_g + away_g
    except ValueError:
        return None

    tip_lower = tip.lower().strip()

    # Over / Under
    if "over" in tip_lower:
        threshold = 2.5 if "2.5" in tip_lower else 3.5
        return 1 if total_goals > threshold else 0

    if "under" in tip_lower:
        threshold = 2.5 if "2.5" in tip_lower else 3.5
        return 1 if total_goals < threshold else 0

    # 1X2
    if tip_lower in ("1", "home"):
        return 1 if home_g > away_g else 0
    if tip_lower in ("2", "away"):
        return 1 if away_g > home_g else 0
    if tip_lower in ("x", "draw"):
        return 1 if home_g == away_g else 0

    # Both to score
    if "both" in tip_lower or "btts" in tip_lower:
        return 1 if home_g > 0 and away_g > 0 else 0

    # Dokładny wynik (np. "2-1 Home")
    if "-" in tip_lower:
        parts = tip_lower.split()
        if parts[0].replace("-", "").isdigit():
            return 1 if wynik == parts[0] else 0

    log.warning("Nie umiem ocenić tip: %s (wynik: %s)", tip, wynik)
    return None


def _get_fixtures_api(api_key: str, date_str: str) -> list[dict]:
    """Pobiera fixtures z API-Football dla całej daty (bez filtrowania po lidze)."""
    import requests
    try:
        r = requests.get(
            "https://v3.football.api-sports.io/fixtures",
            headers={"x-apisports-key": api_key},
            params={"date": date_str},
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("response", [])
    except Exception as e:
        log.debug("API-Football error for date %s: %s", date_str, e)
        return []


def settle_active_coupons(
    days_back: int = 3,
    dry_run: bool = False,
    verbose: bool = True,
) -> dict:
    """
    Rozlicza ACTIVE kupony z fallback na FlashScore.

    Args:
        days_back: Ile dni wstecz sprawdzać
        dry_run: Tylko pokaż co by zmienił
        verbose: Drukuj log

    Returns:
        {"settled": N, "partial": M, "errors": K}
    """
    from footstats.core.backtest import _connect, init_db
    from footstats.scrapers.results_updater import _get_api_key, _znajdz_wynik
    from footstats.scrapers.flashscore_results import get_match_result

    init_db()

    today = datetime.now().date()
    cutoff = today - timedelta(days=days_back)

    with _connect() as conn:
        rows = conn.execute(
            """SELECT id, legs_json, total_odds, stake_pln, match_date_first
               FROM coupons
               WHERE status = 'ACTIVE'
               AND created_at < ?""",
            (today.isoformat(),),
        ).fetchall()

    if not rows:
        if verbose:
            print("[CouponSettlement] Brak ACTIVE kuponów do rozliczenia.")
        return {"settled": 0, "partial": 0, "errors": 0}

    if verbose:
        print(f"[CouponSettlement] ACTIVE kuponów do sprawdzenia: {len(rows)}")

    api_key = _get_api_key()
    stats = {"settled": 0, "partial": 0, "errors": 0}
    fixtures_cache: dict[str, list] = {}

    for row in rows:
        coupon_id = row["id"]
        legs = json.loads(row["legs_json"])
        total_odds = row["total_odds"]
        stake = row["stake_pln"]
        match_date = row["match_date_first"]

        # Sprawdź czy data nie za stara
        try:
            leg_date = datetime.fromisoformat(match_date).date()
            if leg_date < cutoff:
                if verbose:
                    print(f"  [SKIP] Kupon #{coupon_id} — data {match_date} za stara (>{days_back}d)")
                continue
        except (ValueError, TypeError):
            pass

        leg_results: list[int | None] = []

        for leg in legs:
            home = leg.get("home") or leg.get("home_team") or ""
            away = leg.get("away") or leg.get("away_team") or ""
            mecz = leg.get("mecz", "")

            # Fallback: parsuj z pola "mecz" jeśli brak home/away
            if not home or not away:
                if " vs " in mecz:
                    home, away = mecz.split(" vs ", 1)
                elif " - " in mecz:
                    home, away = mecz.split(" - ", 1)

            home = (home or "").strip()
            away = (away or "").strip()
            tip = leg.get("tip", leg.get("type", ""))

            if not home or not away:
                leg_results.append(None)
                if verbose:
                    print(f"    [SKIP] Brak nazw drużyn w kuponie #{coupon_id}")
                continue

            wynik = None

            # Krok 1: Spróbuj API-Football (jeśli dostępny)
            if api_key:
                try:
                    date_key = match_date[:10]
                    if date_key not in fixtures_cache:
                        fixtures_cache[date_key] = _get_fixtures_api(api_key, date_key)
                    fixtures = fixtures_cache[date_key]
                    pending_mock = {"team_home": home, "team_away": away}
                    wynik = _znajdz_wynik(pending_mock, fixtures)
                except Exception as e:
                    log.debug("API-Football error: %s", e)

            # Krok 2: Fallback na FlashScore
            if not wynik:
                wynik = get_match_result(home, away, match_date[:10], cache_enabled=True)

            if wynik:
                correct = _oblicz_tip_correct(tip, wynik)
                leg_results.append(correct)
                if verbose:
                    symbol = "✓" if correct == 1 else ("✗" if correct == 0 else "?")
                    print(f"    [{symbol}] {home} vs {away} → {wynik} (tip: {tip})")
            else:
                leg_results.append(None)
                if verbose:
                    print(f"    [NOT FOUND] {home} vs {away} ({match_date[:10]})")

        # Oceń kupon
        if None in leg_results:
            stats["partial"] += 1
            if verbose:
                print(f"  [PARTIAL] Kupon #{coupon_id} — czekam na brakujące wyniki\n")
            continue

        all_correct = all(r == 1 for r in leg_results)
        new_status = STATUS_WON if all_correct else STATUS_LOSE
        payout = round(stake * total_odds, 2) if all_correct else 0.0
        roi = round((payout - stake) / stake * 100, 1) if stake else 0.0

        if verbose:
            tag = "DRY" if dry_run else "SETTLE"
            print(f"  [{tag}] Kupon #{coupon_id} → {new_status} | wypłata: {payout} PLN | ROI: {roi}%\n")

        if not dry_run:
            try:
                with _connect() as conn:
                    # Aktualizuj status kuponu
                    conn.execute(
                        "UPDATE coupons SET status=?, payout_pln=?, roi_pct=? WHERE id=?",
                        (new_status, payout, roi, coupon_id),
                    )

                    # Dla WIN: aktualizuj bankroll
                    if all_correct and payout > 0:
                        cur_balance = conn.execute(
                            "SELECT balance FROM bankroll_state ORDER BY id DESC LIMIT 1"
                        ).fetchone()
                        if cur_balance:
                            new_balance = round(cur_balance["balance"] + payout, 2)
                            conn.execute(
                                "UPDATE bankroll_state SET balance=?, updated_at=? "
                                "WHERE id=(SELECT MAX(id) FROM bankroll_state)",
                                (new_balance, datetime.now().isoformat()),
                            )
                            conn.execute(
                                "INSERT INTO bankroll_history "
                                "(timestamp, change_pln, new_balance, type, description) "
                                "VALUES (?,?,?,?,?)",
                                (
                                    datetime.now().isoformat(),
                                    payout,
                                    new_balance,
                                    "WIN",
                                    f"Kupon #{coupon_id} WIN",
                                ),
                            )

                    # Dla LOSE: wyślij do RAG feedback
                    if not all_correct:
                        _send_to_rag_feedback(coupon_id, legs, wynik, verbose=verbose)

                stats["settled"] += 1
            except Exception as e:
                log.error("Błąd rozliczania kuponu ID=%s: %s", coupon_id, e)
                stats["errors"] += 1

    if verbose:
        print(
            f"\n[CouponSettlement] Rozliczonych: {stats['settled']} | "
            f"Częściowych: {stats['partial']} | Błędów: {stats['errors']}"
        )
    return stats


def _send_to_rag_feedback(coupon_id: int, legs: list, results: str | None, verbose: bool = True):
    """
    Wysyła info o LOSE kuponie do post_match_analyzer (RAG feedback).
    """
    try:
        from footstats.ai.post_match_analyzer import uczy_sie_z_porażek

        lesson = _generate_lesson(legs, results)
        uczy_sie_z_porażek(
            coupon_id=coupon_id,
            lesson_text=lesson,
            ai_model="manual_settlement",
        )

        if verbose:
            log.info("Wysłano feedback do RAG dla kuponu #%s", coupon_id)
    except Exception as e:
        log.warning("Błąd wysyłania feedback do RAG: %s", e)


def _generate_lesson(legs: list, results: str | None) -> str:
    """
    Generuje krótki wniosek z porażki dla RAG.
    """
    lessons = []
    for leg in legs:
        mecz = leg.get("mecz", "?")
        tip = leg.get("tip", "?")
        lessons.append(f"• {mecz}: {tip} (wynik: {results})")

    return "Kupon nietrafiany:\n" + "\n".join(lessons)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    settle_active_coupons(days_back=3, dry_run=False, verbose=True)
