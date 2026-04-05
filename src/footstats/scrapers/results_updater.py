"""
results_updater.py – automatyczne pobieranie wyników zakończonych meczów.

Pobiera wyniki dla meczów z backtest.db (actual_result IS NULL, data < dziś)
korzystając z API-Football (api-sports.io, 100 req/dzień).

Użycie:
    python -m footstats.scrapers.results_updater          # aktualizuj pending
    python -m footstats.scrapers.results_updater --dry    # pokaż co by zaktualizował
    python -m footstats.scrapers.results_updater --dni 3  # cofnij się 3 dni
"""

import os
import re
import sys
import time
import logging
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from dotenv import load_dotenv

import requests

load_dotenv()
log = logging.getLogger(__name__)

API_BASE    = "https://v3.football.api-sports.io"
API_KEY_ENV = "APISPORTS_KEY"

# Ligi do sprawdzania w API-Football (id → kod wewnętrzny)
_LIGI_IDS = {
    39:  "ENG-Premier League",
    78:  "GER-Bundesliga",
    135: "ITA-Serie A",
    140: "ESP-La Liga",
    61:  "FRA-Ligue 1",
    88:  "NED-Eredivisie",
    106: "POL-Ekstraklasa",
    94:  "POR-Primeira Liga",
    2:   "UEFA-Champions League",
    3:   "UEFA-Europa League",
}

# Odwrotne mapowanie: nazwa ligi → id API
_NAZWA_DO_ID = {v: k for k, v in _LIGI_IDS.items()}


def _get_api_key() -> str | None:
    return (os.getenv(API_KEY_ENV) or "").strip() or None


def _similar(a: str, b: str) -> float:
    """Podobieństwo nazw (0–1). Porównuje lowercase bez znaków specjalnych."""
    def _norm(s):
        return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _fetch_fixtures(api_key: str, league_id: int, date_str: str) -> list[dict]:
    """Pobiera fixtures z API-Football dla danej ligi i daty (YYYY-MM-DD)."""
    try:
        r = requests.get(
            f"{API_BASE}/fixtures",
            headers={"x-apisports-key": api_key},
            params={"league": league_id, "date": date_str, "season": datetime.now().year},
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("response", [])
    except Exception as e:
        log.warning("API-Football fixtures error (liga=%s, date=%s): %s", league_id, date_str, e)
        return []


def _fixture_to_result(fixture: dict) -> tuple[str, str, str] | None:
    """
    Zwraca (home_name, away_name, wynik) np. ("PSG", "Lyon", "2-1").
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
    return home, away, f"{home_g}-{away_g}"


def _znajdz_wynik(
    pending: dict,
    fixtures: list[dict],
    min_similarity: float = 0.70,
) -> str | None:
    """
    Dopasowuje pending mecz (team_home, team_away) do listy fixtures API.
    Zwraca wynik np. "2-1" lub None jeśli brak dopasowania.
    """
    ph = pending["team_home"]
    pa = pending["team_away"]

    for fix in fixtures:
        parsed = _fixture_to_result(fix)
        if parsed is None:
            continue
        fh, fa, wynik = parsed
        sim_h = _similar(ph, fh)
        sim_a = _similar(pa, fa)
        if sim_h >= min_similarity and sim_a >= min_similarity:
            return wynik

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

        # Spróbuj znaleźć league_id na podstawie nazwy ligi
        league_ids_to_try = []
        if league_str in _NAZWA_DO_ID:
            league_ids_to_try = [_NAZWA_DO_ID[league_str]]
        else:
            # Jeśli nie znamy ligi — szukaj we wszystkich
            league_ids_to_try = list(_LIGI_IDS.keys())

        wynik_found = None

        for league_id in league_ids_to_try:
            cache_key = (match_date, league_id)
            if cache_key not in fixtures_cache:
                if req_count >= 80:  # zostaw bufor 20 req
                    if verbose:
                        print("[ResultsUpdater] Limit 80 requestów osiągnięty — stop.")
                    break
                fixtures_cache[cache_key] = _fetch_fixtures(api_key, league_id, match_date)
                req_count += 1
                time.sleep(0.5)  # rate limit

            wynik_found = _znajdz_wynik(p, fixtures_cache[cache_key])
            if wynik_found:
                break

        if wynik_found:
            if verbose:
                status = "DRY" if dry_run else "UPDATE"
                print(f"  [{status}] {p['team_home']} vs {p['team_away']} → {wynik_found}")
            if not dry_run:
                try:
                    info = update_result(p["id"], wynik_found)
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


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.WARNING)

    parser = argparse.ArgumentParser(description="FootStats Results Updater")
    parser.add_argument("--dry",  action="store_true", help="Tylko pokaż co by zaktualizował")
    parser.add_argument("--dni",  type=int, default=2,  help="Ile dni wstecz sprawdzać (domyślnie 2)")
    args = parser.parse_args()

    update_pending(days_back=args.dni, dry_run=args.dry, verbose=True)
