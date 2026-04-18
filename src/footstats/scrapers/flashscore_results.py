"""
flashscore_results.py – Fallback scraper wyników ze FlashScore dla starych meczów.

Gdy API-Football nie zwraca wyniku, ten scraper pobiera dane ze FlashScore
używając BeautifulSoup do parsowania wyników meczów.

Użycie:
    from flashscore_results import get_match_result
    wynik = get_match_result("Arsenal", "Chelsea", "2026-04-15")  # "2-1" lub None
"""

import re
import logging
from datetime import datetime, timedelta
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: pip install requests beautifulsoup4 lxml")
    raise

log = logging.getLogger(__name__)

FLASHSCORE_URL = "https://www.flashscore.com"
CACHE_DIR = Path(__file__).parent.parent.parent / "cache" / "flashscore"


def _norm_team_name(name: str) -> str:
    """Normalizuje nazwę zespołu do wyszukiwania."""
    name = re.sub(r"[^a-z0-9\s]", "", name.lower())
    name = re.sub(r"\s+", "-", name.strip())
    # Krótkie warianty
    return name.replace("manchester united", "man-united")\
               .replace("manchester city", "man-city")\
               .replace("newcastle united", "newcastle")\
               .replace("brighton hove albion", "brighton")


def get_match_result(
    home_team: str,
    away_team: str,
    match_date: str,  # YYYY-MM-DD
    cache_enabled: bool = True,
) -> str | None:
    """
    Pobiera wynik meczu ze FlashScore.

    Args:
        home_team: Nazwa drużyny gospodarza (np. "Arsenal")
        away_team: Nazwa drużyny gościa (np. "Chelsea")
        match_date: Data meczu w formacie YYYY-MM-DD
        cache_enabled: Czy używać cache (cache/flashscore/YYYY-MM-DD.json)

    Returns:
        Wynik w formacie "2-1" lub None jeśli nie znaleziono
    """
    try:
        from datetime import datetime as dt
        date_obj = dt.fromisoformat(match_date)
    except (ValueError, TypeError):
        log.warning("Invalid date format: %s", match_date)
        return None

    # Zmiana daty na format FlashScore (np. 15.04.2026)
    flash_date = date_obj.strftime("%d.%m.%Y")

    # Cache
    if cache_enabled:
        cache_file = CACHE_DIR / f"{match_date}.json"
        if cache_file.exists():
            try:
                import json
                with open(cache_file) as f:
                    cache = json.load(f)
                    key = f"{_norm_team_name(home_team)}_{_norm_team_name(away_team)}"
                    if key in cache:
                        log.debug("Cache hit: %s", key)
                        return cache[key]
            except Exception:
                pass

    # Wyszukiwanie na FlashScore
    try:
        result = _search_flashscore(home_team, away_team, flash_date)

        # Zapisz do cache
        if cache_enabled and result:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file = CACHE_DIR / f"{match_date}.json"
            try:
                import json
                cache = {}
                if cache_file.exists():
                    with open(cache_file) as f:
                        cache = json.load(f)
                key = f"{_norm_team_name(home_team)}_{_norm_team_name(away_team)}"
                cache[key] = result
                with open(cache_file, "w") as f:
                    json.dump(cache, f, indent=2)
            except Exception as e:
                log.warning("Cache write error: %s", e)

        return result
    except Exception as e:
        log.warning("FlashScore scrape error for %s vs %s: %s", home_team, away_team, e)
        return None


def _search_flashscore(home: str, away: str, date_str: str) -> str | None:
    """
    Wewnętrzna funkcja do wyszukiwania wyniku na FlashScore.
    Zwraca wynik "X-Y" lub None.
    """
    # Buduj URL wyszukiwania (przykład: /match/arsenal-chelsea-15042026/)
    home_slug = _norm_team_name(home)
    away_slug = _norm_team_name(away)
    date_slug = date_str.replace(".", "")  # 15.04.2026 → 15042026

    # Spróbuj bezpośrednią ścieżkę
    urls_to_try = [
        f"{FLASHSCORE_URL}/match/{home_slug}-{away_slug}-{date_slug}/",
        f"{FLASHSCORE_URL}/match/{away_slug}-{home_slug}-{date_slug}/",
        # Alternatywa: search page
        f"{FLASHSCORE_URL}/search/{home} {away} {date_str}/",
    ]

    for url in urls_to_try:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                result = _parse_flashscore_match(r.text, home, away)
                if result:
                    log.info("Found result on FlashScore: %s vs %s → %s", home, away, result)
                    return result
        except Exception as e:
            log.debug("FlashScore URL error %s: %s", url, e)
            continue

    return None


def _parse_flashscore_match(html: str, home: str, away: str) -> str | None:
    """
    Parsuje HTML ze strony meczu FlashScore.
    Szuka wyniku w formacie X-Y.
    """
    soup = BeautifulSoup(html, "lxml")

    # Szukaj wyniku w verschiednych miejscach
    patterns = [
        # Finalny wynik (główny obszar)
        r"(\d+)\s*[-–—]\s*(\d+)",
        # W nagłówku
        r"<h1[^>]*>.*?(\d+)\s*[-–—]\s*(\d+).*?</h1>",
    ]

    for pattern in patterns:
        matches = re.findall(pattern, html)
        if matches:
            # Zwróć ostatni znaleziony (zwykle finalny wynik)
            goals_home, goals_away = matches[-1]
            return f"{goals_home}-{goals_away}"

    # Spróbuj parsować strukturę JSON osadzoną w HTML (niektóre strony)
    try:
        import json
        json_match = re.search(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html)
        if json_match:
            data = json.loads(json_match.group(1))
            if isinstance(data, dict) and "homeTeam" in data and "awayTeam" in data:
                home_score = data.get("homeTeamScore", {})
                away_score = data.get("awayTeamScore", {})
                if isinstance(home_score, (int, str)) and isinstance(away_score, (int, str)):
                    return f"{home_score}-{away_score}"
    except Exception:
        pass

    return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Test
    result = get_match_result("Arsenal", "Chelsea", "2026-04-15")
    print(f"Arsenal vs Chelsea (2026-04-15): {result}")
