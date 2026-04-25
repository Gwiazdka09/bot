"""
results_updater.py – automatyczne pobieranie wyników zakończonych meczów.

Pobiera wyniki dla meczów z backtest.db (actual_result IS NULL, data < dziś)
korzystając z API-Football (api-sports.io, 100 req/dzień).

Użycie:
    python -m footstats.scrapers.results_updater          # aktualizuj pending
    python -m footstats.scrapers.results_updater --dry    # pokaż co by zaktualizował
    python -m footstats.scrapers.results_updater --dni 3  # cofnij się 3 dni
"""

import json
import os
import re
import sys
import time
import logging
import unicodedata
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from dotenv import load_dotenv

import requests

load_dotenv()
log = logging.getLogger(__name__)

API_BASE    = "https://v3.football.api-sports.io"
API_KEY_ENV = "APISPORTS_KEY"

# Ligi do sprawdzania w API-Football (id → czytelna nazwa)
_LIGI_IDS = {
    # Główne europejskie
    39:  "Premier League",
    40:  "Championship",
    78:  "Bundesliga",
    135: "Serie A",
    140: "La Liga",
    61:  "Ligue 1",
    88:  "Eredivisie",
    106: "Ekstraklasa",
    94:  "Primeira Liga",
    144: "Pro League",          # Belgia
    119: "Superliga",           # Dania
    179: "Scottish Premiership",
    197: "Super League",        # Grecja (Stoiximan Super League)
    203: "Super Lig",           # Turcja
    218: "Allsvenskan",         # Szwecja
    103: "Eliteserien",         # Norwegia
    113: "Veikkausliiga",       # Finlandia
    271: "Fortuna Liga",        # Czechy
    345: "SuperLiga",           # Serbia
    # Europejskie puchary
    2:   "Champions League",
    3:   "Europa League",
    848: "Conference League",
    # Ameryki
    13:  "Copa Libertadores",
    11:  "Copa Sudamericana",
    253: "MLS",
    71:  "Serie A",             # Brazylia — kolizja z ITA, obsługiwana przez fuzzy
    # Azja / Bliski Wschód
    307: "Saudi Pro League",
    # Afryka
    332: "NPFL",                # Nigeria Premier Football League
    # Bałkany / Europa Wschodnia
    172: "Parva Liga",          # Bułgaria
}

# Aliasy: alternatywne nazwy z DB → znormalizowana nazwa do fuzzy-match
_ALIASY: dict[str, str] = {
    "stoiximan super league": "super league",
    "trendyol super lig":     "super lig",
    "nigeria premier football league": "npfl",
    "europa league":          "europa league",
    "champions league":       "champions league",
    "conference league":      "conference league",
}


def _get_api_key() -> str | None:
    return (os.getenv(API_KEY_ENV) or "").strip() or None


def _norm(s: str) -> str:
    """Normalizuje tekst: Unicode → ASCII, lowercase, tylko alfanumeryczne."""
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def _similar(a: str, b: str) -> float:
    """Podobieństwo nazw (0–1). Obsługuje akcenty i skróty."""
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _liga_ids_dla_nazwy(league_str: str) -> list[int]:
    """
    Zwraca listę league_id do sprawdzenia dla danej nazwy ligi z DB.
    Używa fuzzy-match zamiast exact-match aby obsłużyć warianty nazw.
    """
    # Ligi do śledzenia (tylko te będą odpytywane przez API w pierwszej kolejności)
    TRACKED_LEAGUES_NAMES = [
        'Premier League', 'La Liga', 'Bundesliga', 'Serie A', 
        'Ligue 1', 'Ekstraklasa', 'Eredivisie', 'Primeira Liga'
    ]
    tracked_ids = [lid for lid, name in _LIGI_IDS.items() if name in TRACKED_LEAGUES_NAMES]
    
    if not league_str:
        return tracked_ids

    # Spróbuj alias
    normalized = _ALIASY.get(_norm(league_str), _norm(league_str))

    # Szukaj najlepszego dopasowania wśród znanych lig
    best_id: int | None = None
    best_score = 0.0
    for lid, lname in _LIGI_IDS.items():
        score = _similar(normalized, lname)
        if score > best_score:
            best_score = score
            best_id = lid

    if best_id is not None and best_score >= 0.55:
        if best_id in tracked_ids:
            return [best_id]
        
        log.debug("Liga '%s' (id=%d) znaleziona, ale nie jest w TRACKED_LEAGUES — pomijam API.", league_str, best_id)
        return []
            
    # Nieznana liga — nie marnujemy limitu API na strzelanie w ciemno
    log.debug("Nieznana liga '%s' (best=%.2f) — pomijam API.", league_str, best_score)
    return []


def _fetch_fixtures(api_key: str, league_id: int, date_str: str) -> list[dict]:
    """Pobiera fixtures z API-Football dla danej ligi i daty (YYYY-MM-DD)."""
    try:
        r = requests.get(
            f"{API_BASE}/fixtures",
            headers={"x-apisports-key": api_key},
            params={"league": league_id, "date": date_str},
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("response", [])
    except Exception as e:
        log.warning("API-Football fixtures error (liga=%s, date=%s): %s", league_id, date_str, e)
        return []


def _fixture_to_result(fixture: dict, api_key: str = None) -> tuple[str, str, str, dict] | None:
    """
    Zwraca (home_name, away_name, wynik, stats) np. ("PSG", "Lyon", "2-1", {"xG": ...}).
    Zwraca None jeśli mecz nie jest ukończony.
    """
    status = fixture.get("fixture", {}).get("status", {}).get("short", "")
    if status not in ("FT", "AET", "PEN"):
        return None
    goals  = fixture.get("goals", {})
    home_g = goals.get("home")
    away_g = goals.get("away")
    if home_g is None or away_g is None:
        return None
    teams  = fixture.get("teams", {})
    home   = teams.get("home", {}).get("name", "")
    away   = teams.get("away", {}).get("name", "")
    
    # Pobierz statystyki jeśli mamy klucz
    match_id = fixture.get("fixture", {}).get("id")
    stats = {}
    if api_key and match_id:
        stats = _fetch_match_stats(api_key, match_id)

    return home, away, f"{home_g}-{away_g}", stats


def _fetch_match_stats(api_key: str, fixture_id: int) -> dict:
    """Pobiera statystyki (xG, strzały) dla konkretnego meczu."""
    try:
        r = requests.get(
            f"{API_BASE}/fixtures/statistics",
            headers={"x-apisports-key": api_key},
            params={"fixture": fixture_id},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json().get("response", [])
        
        res = {}
        for team_stat in data:
            t_name = team_stat.get("team", {}).get("name", "?")
            s_list = team_stat.get("statistics", [])
            t_stats = {s["type"]: s["value"] for s in s_list}
            res[t_name] = t_stats
        return res
    except Exception as e:
        log.debug("Match stats error (id=%s): %s", fixture_id, e)
        return {}


def _znajdz_wynik(
    pending: dict,
    fixtures: list[dict],
    api_key: str = None,
    min_similarity: float = 0.70,
) -> tuple[str, dict] | None:
    """
    Dopasowuje pending mecz (team_home, team_away) do listy fixtures API.
    Zwraca (wynik, stats) lub None jeśli brak dopasowania.
    """
    ph = pending["team_home"]
    pa = pending["team_away"]

    for fix in fixtures:
        parsed = _fixture_to_result(fix, api_key)
        if parsed is None:
            continue
        fh, fa, wynik, stats = parsed
        sim_h = _similar(ph, fh)
        sim_a = _similar(pa, fa)
        if sim_h >= min_similarity and sim_a >= min_similarity:
            return wynik, stats

    return None


def update_pending(
    days_back: int = 2,
    dry_run: bool = False,
    verbose: bool = True,
) -> dict:
    """
    Główna funkcja: pobiera pending mecze z backtest.db i aktualizuje wyniki.

    Zwraca: {"updated": N, "not_found": M, "errors": K}
    """
    api_key = _get_api_key()
    if not api_key:
        print("[ResultsUpdater] Brak APISPORTS_KEY w .env — pomijam auto-update.")
        return {"updated": 0, "not_found": 0, "errors": 0}

    from footstats.core.backtest import get_pending_results, update_result, init_db
    init_db()
    pending_all = get_pending_results()

    # Filtruj tylko mecze które już się odbyły (data < dziś)
    today = datetime.now().date()
    cutoff = today - timedelta(days=days_back)
    pending = [
        p for p in pending_all
        if p.get("match_date") and datetime.fromisoformat(p["match_date"]).date() < today
        and datetime.fromisoformat(p["match_date"]).date() >= cutoff
    ]

    if not pending:
        if verbose:
            print("[ResultsUpdater] Brak pending meczów do aktualizacji.")
        return {"updated": 0, "not_found": 0, "errors": 0}

    if verbose:
        print(f"[ResultsUpdater] Pending meczów do sprawdzenia: {len(pending)}")

    # Grupuj po dacie żeby minimalizować requesty API
    dates_needed: set[str] = set()
    for p in pending:
        dates_needed.add(p["match_date"][:10])

    # Pobierz fixtures per data per liga (cache per (date, liga))
    fixtures_cache: dict[tuple, list] = {}
    req_count = 0

    stats = {"updated": 0, "not_found": 0, "errors": 0}

    for p in pending:
        match_date = p["match_date"][:10]
        league_str = p.get("league", "")

        # Fuzzy-dopasowanie nazwy ligi do listy API-Football
        league_ids_to_try = _liga_ids_dla_nazwy(league_str)

        wynik_found = None

        for league_id in league_ids_to_try:
            cache_key = (match_date, league_id)
            if cache_key not in fixtures_cache:
                if req_count >= 75:  # Limit 75 requestów (zostaw bufor 25)
                    if verbose:
                        print("[ResultsUpdater] Limit 75 requestów osiągnięty — przechodzę na Scraper.")
                    break
                fixtures_cache[cache_key] = _fetch_fixtures(api_key, league_id, match_date)
                req_count += 1
                time.sleep(0.5)  # rate limit

            wynik_data = _znajdz_wynik(p, fixtures_cache[cache_key], api_key)
            if wynik_data:
                wynik_found, stats_found = wynik_data
                break

        # FALLBACK: Scraper jeśli API nie znalazło lub limit osiągnięty
        if not wynik_found:
            try:
                from footstats.scrapers.flashscore_results import get_match_result
                if verbose:
                    reason = "Limit API" if req_count >= 75 else "Brak w API"
                    print(f"  [SCRAPER FALLBACK] {p['team_home']} vs {p['team_away']} ({reason})...")
                
                wynik_found = get_match_result(p["team_home"], p["team_away"], match_date)
                if wynik_found:
                    stats_found = {}  # Scraper nie dostarcza pełnych statystyk xG
            except Exception as e:
                log.debug("Fallback scraper error: %s", e)

        if wynik_found:
            if verbose:
                status = "DRY" if dry_run else "UPDATE"
                print(f"  [{status}] {p['team_home']} vs {p['team_away']} → {wynik_found} (+stats)")
            if not dry_run:
                try:
                    info = update_result(p["id"], wynik_found, stats_found)
                    stats["updated"] += 1
                    # Powiadomienie Telegram jeśli dostępne
                    try:
                        from footstats.utils.telegram_notify import send_wynik_update, telegram_dostepny
                        if telegram_dostepny():
                            send_wynik_update(
                                p["id"],
                                f"{p['team_home']} vs {p['team_away']}",
                                p.get("ai_tip", "?"),
                                wynik_found,
                                info.get("tip_correct"),
                            )
                    except Exception:
                        pass
                except Exception as e:
                    log.error("Błąd update_result ID=%s: %s", p["id"], e)
                    stats["errors"] += 1
            else:
                stats["updated"] += 1
        else:
            if verbose:
                print(f"  [NOT FOUND] {p['team_home']} vs {p['team_away']} ({match_date})")
            stats["not_found"] += 1

    if verbose:
        print(f"\n[ResultsUpdater] Zaktualizowano: {stats['updated']} | "
              f"Nie znaleziono: {stats['not_found']} | "
              f"Błędy: {stats['errors']} | "
              f"Requesty API: {req_count}")
    return stats


def update_active_coupons(
    days_back: int = 3,
    dry_run: bool = False,
    verbose: bool = True,
) -> dict:
    """
    Zamyka ACTIVE kupony w tabeli coupons po zakończeniu meczów.

    Dla każdego kuponu:
      - pobiera wynik każdego leg'a z API-Football
      - ocenia tip (WIN/LOSE) używając tej samej logiki co backtest.py
      - jeśli WSZYSTKIE nogi ocenione → ustawia WIN lub LOSE
      - aktualizuje bankroll_state i bankroll_history przy WIN
    """
    api_key = _get_api_key()
    if not api_key:
        print("[CouponUpdater] Brak APISPORTS_KEY — pomijam aktualizację kuponów.")
        return {"closed": 0, "partial": 0, "errors": 0}

    from footstats.core.backtest import _connect, init_db
    from footstats.utils.betting import oblicz_tip_correct
    init_db()

    today = datetime.now().date()
    cutoff = today - timedelta(days=days_back)

    with _connect() as conn:
        rows = conn.execute(
            """SELECT id, legs_json, total_odds, stake_pln, match_date_first
               FROM coupons
               WHERE status = 'ACTIVE'
               AND match_date_first < ?""",
            (today.isoformat(),)
        ).fetchall()

    if not rows:
        if verbose:
            print("[CouponUpdater] Brak aktywnych kuponów do rozliczenia.")
        return {"closed": 0, "partial": 0, "errors": 0}

    if verbose:
        print(f"[CouponUpdater] Aktywnych kuponów do sprawdzenia: {len(rows)}")

    # Jeden request na datę (bez filtra ligi — free plan API-Football tego wymaga)
    date_cache: dict[str, list] = {}
    req_count = 0
    stats = {"closed": 0, "partial": 0, "errors": 0}

    def _get_fixtures_for_date(date_str: str) -> list[dict]:
        nonlocal req_count
        if date_str in date_cache:
            return date_cache[date_str]
        if req_count >= 80:
            date_cache[date_str] = []
            return []
        try:
            r = requests.get(
                f"{API_BASE}/fixtures",
                headers={"x-apisports-key": api_key},
                params={"date": date_str},
                timeout=15,
            )
            r.raise_for_status()
            date_cache[date_str] = r.json().get("response", [])
        except Exception as e:
            log.warning("API-Football date-fetch error (date=%s): %s", date_str, e)
            date_cache[date_str] = []
        req_count += 1
        time.sleep(0.3)
        return date_cache[date_str]

    for row in rows:
        coupon_id = row["id"]
        legs = json.loads(row["legs_json"])
        total_odds = row["total_odds"]
        stake = row["stake_pln"]
        match_date = row["match_date_first"]

        # Sprawdź czy data nie jest za stara
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
            home = leg.get("home", leg.get("mecz", "").split(" vs ")[0])
            away = leg.get("away", leg.get("mecz", "").split(" vs ")[-1])
            tip = leg.get("tip", "")

            fixtures = []
            if req_count < 75:
                fixtures = _get_fixtures_for_date(match_date[:10])
            
            pending_mock = {"team_home": home, "team_away": away}
            wynik = _znajdz_wynik(pending_mock, fixtures)

            # FALLBACK: Scraper dla kuponu (krytyczne!)
            if not wynik:
                try:
                    from footstats.scrapers.flashscore_results import get_match_result
                    if verbose:
                        reason = "Limit API" if req_count >= 75 else "Brak w API"
                        print(f"  [COUPON SCRAPER FALLBACK] {home} vs {away} ({reason})...")
                    wynik = get_match_result(home, away, match_date[:10])
                except Exception as e:
                    log.debug("Coupon fallback scraper error: %s", e)

            if wynik:
                correct = oblicz_tip_correct(tip, wynik)
                leg_results.append(correct)
                if verbose:
                    symbol = "✓" if correct == 1 else ("✗" if correct == 0 else "?")
                    print(f"  [{symbol}] {home} vs {away} → {wynik} (typ: {tip})")
            else:
                leg_results.append(None)
                if verbose:
                    print(f"  [NOT FOUND] {home} vs {away} ({match_date[:10]})")

        # Oceń kupon
        if None in leg_results:
            stats["partial"] += 1
            if verbose:
                print(f"  [PARTIAL] Kupon #{coupon_id} — czekam na brakujące wyniki")
            continue

        all_correct = all(r == 1 for r in leg_results)
        new_status = "WIN" if all_correct else "LOSE"
        payout = round(stake * total_odds, 2) if all_correct else 0.0
        roi = round((payout - stake) / stake * 100, 1) if stake else 0.0

        if verbose:
            tag = "DRY" if dry_run else "CLOSE"
            print(f"  [{tag}] Kupon #{coupon_id} → {new_status} | wypłata: {payout} PLN | ROI: {roi}%")

        if not dry_run:
            try:
                with _connect() as conn:
                    conn.execute(
                        "UPDATE coupons SET status=?, payout_pln=?, roi_pct=? WHERE id=?",
                        (new_status, payout, roi, coupon_id),
                    )
                    # Aktualizuj bankroll przy wygranej
                    if all_correct and payout > 0:
                        cur_balance = conn.execute(
                            "SELECT balance FROM bankroll_state ORDER BY id DESC LIMIT 1"
                        ).fetchone()
                        if cur_balance:
                            new_balance = round(cur_balance["balance"] + payout, 2)
                            conn.execute(
                                "UPDATE bankroll_state SET balance=?, updated_at=? WHERE id=(SELECT MAX(id) FROM bankroll_state)",
                                (new_balance, datetime.now().isoformat()),
                            )
                            conn.execute(
                                "INSERT INTO bankroll_history (timestamp, change_pln, new_balance, type, description) VALUES (?,?,?,?,?)",
                                (datetime.now().isoformat(), payout, new_balance, "WIN", f"Kupon #{coupon_id} WIN"),
                            )
                stats["closed"] += 1
            except Exception as e:
                log.error("Błąd zamykania kuponu ID=%s: %s", coupon_id, e)
                stats["errors"] += 1

    if verbose:
        print(f"\n[CouponUpdater] Zamknięte: {stats['closed']} | Częściowe: {stats['partial']} | Błędy: {stats['errors']}")
    return stats


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.WARNING)

    parser = argparse.ArgumentParser(description="FootStats Results Updater")
    parser.add_argument("--dry",  action="store_true", help="Tylko pokaż co by zaktualizował")
    parser.add_argument("--dni",  type=int, default=2,  help="Ile dni wstecz sprawdzać (domyślnie 2)")
    args = parser.parse_args()

    update_pending(days_back=args.dni, dry_run=args.dry, verbose=True)
    print()
    update_active_coupons(days_back=args.dni, dry_run=args.dry, verbose=True)
