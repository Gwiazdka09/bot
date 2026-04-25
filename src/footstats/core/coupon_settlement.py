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

from footstats.utils.betting import oblicz_tip_correct, normalize_team_name


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
               WHERE status = 'ACTIVE'""",
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
        mdate = match_date[:10]

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
        any_leg_lost = False  # Flaga dla AKO: wystarczy JEDEN przegrany, aby cały kupon przegrał

        for leg_idx, leg in enumerate(legs):
            home = leg.get("home", "")
            away = leg.get("away", "")
            tip_val = leg.get("tip", "")

            if not home or not away:
                # Fallback: parsuj z pola "mecz" jeśli brak home/away
                mecz = leg.get("mecz", "")
                if " vs " in mecz:
                    home, away = mecz.split(" vs ", 1)
                elif " - " in mecz:
                    home, away = mecz.split(" - ", 1)
                home, away = home.strip(), away.strip()

            # Pobierz fixtures dla daty (cache)
            if mdate not in fixtures_cache:
                fixtures_cache[mdate] = _get_fixtures_api(api_key, mdate) if api_key else []

            # Zbuduj pending_mock zgodnie z sygnaturą _znajdz_wynik(pending_dict, fixtures_list)
            pending_mock = {"team_home": home, "team_away": away}
            res = _znajdz_wynik(pending_mock, fixtures_cache[mdate])

            # Próba z normalizedymi nazwami
            if not res:
                norm_home = normalize_team_name(home)
                norm_away = normalize_team_name(away)
                if norm_home != home.lower() or norm_away != away.lower():
                    norm_mock = {"team_home": norm_home, "team_away": norm_away}
                    res = _znajdz_wynik(norm_mock, fixtures_cache[mdate])

            # Fallback na FlashScore
            if not res:
                res = get_match_result(home, away, mdate, cache_enabled=True)

            correct = oblicz_tip_correct(leg["tip"], res)
            leg_results.append(correct)

            if verbose:
                status_text = "OK" if correct == 1 else "MISS" if correct == 0 else "WAITING"
                print(f"    - {leg['home']} vs {leg['away']} (Tip: {leg['tip']}, Res: {res or '?'}) -> {status_text}")

            # ⚡ REGUŁA AKO: Jeśli JAKIKOLWIEK leg przegrał (correct == 0),
            # cały kupon natychmiast przegrywa — nie czekamy na pozostałe
            if correct == 0:
                any_leg_lost = True
                if verbose:
                    print(f"    [LOSE] Leg #{leg_idx + 1} przegrany — cały kupon AKO przegrywa!")
                break

        # Oceń kupon
        if any_leg_lost:
            # ⚡ AKO RULE: Wystarczy JEDEN leg LOSE, aby cały kupon był LOSE
            new_status = "LOSE"
            payout = 0.0
            roi = -100.0

            if verbose:
                tag = "DRY" if dry_run else "SETTLE"
                print(f"  [{tag}] Kupon #{coupon_id} → {new_status} | wypłata: {payout} PLN | ROI: {roi}%\n")

            if not dry_run:
                try:
                    with _connect() as conn:
                        conn.execute(
                            "UPDATE coupons SET status=?, payout_pln=?, roi_pct=? WHERE id=?",
                            (new_status, payout, roi, coupon_id),
                        )
                    _send_to_rag_feedback(coupon_id, legs, f"Leg #{leg_idx + 1} przegrany", verbose=verbose)
                    stats["settled"] += 1
                except Exception as e:
                    log.error("Błąd rozliczania kuponu ID=%s: %s", coupon_id, e)
                    stats["errors"] += 1
            else:
                stats["settled"] += 1
            continue

        if None in leg_results:
            stats["partial"] += 1
            if verbose:
                print(f"  [PARTIAL] Kupon #{coupon_id} — czekam na brakujące wyniki\n")
            continue

        all_correct = all(r == 1 for r in leg_results)
        new_status = "WIN" if all_correct else "LOSE"
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


def _send_to_rag_feedback(coupon_id: int, legs: list, reason: str, verbose: bool = True):
    """
    Wysyła info o LOSE kuponie do ai_feedback (RAG learning).

    Args:
        coupon_id: ID kuponu (użyty jako match_id dla feedback)
        legs: Lista leg'ów kuponu
        reason: Powód porażki (np. "Leg #1 przegrany")
        verbose: Drukuj log
    """
    try:
        from footstats.ai.post_match_analyzer import _zapisz_feedback

        # Stwórz prediction_details z informacją o tipach w kuponie
        prediction_details = {
            "coupon_id": coupon_id,
            "legs_count": len(legs),
            "tips": [leg.get("tip", "?") for leg in legs],
        }

        _zapisz_feedback(
            match_id=coupon_id,
            prediction_details=prediction_details,
            reason=reason,
        )

        if verbose:
            log.info("Wysłano feedback do RAG dla kuponu #%s: %s", coupon_id, reason)
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
