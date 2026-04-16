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
    if not league_str:
        return list(_LIGI_IDS.keys())

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
        return [best_id]
    # Nieznana liga — przeszukaj wszystkie
    log.debug("Nieznana liga '%s' (best=%.2f) — szukam we wszystkich", league_str, best_score)
    return list(_LIGI_IDS.keys())


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

        # Fuzzy-dopasowanie nazwy ligi do listy API-Football
        league_ids_to_try = _liga_ids_dla_nazwy(league_str)

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
