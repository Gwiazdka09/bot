"""
flashscore_results.py – Fallback scraper wyników ze FlashScore dla starych meczów.
Ulepszona wersja: korzysta z Flashscore.mobi (lekka wersja HTML) i lepszej normalizacji nazw.
"""

import re
import logging
import requests
from datetime import datetime, timedelta
from pathlib import Path
from bs4 import BeautifulSoup
from footstats.utils.normalize import normalize_team_name, team_similarity

log = logging.getLogger(__name__)

# Konfiguracja
FLASHSCORE_MOBI_URL = "https://www.flashscore.mobi"
CACHE_DIR = Path(__file__).parent.parent.parent / "cache" / "flashscore"

_similar = team_similarity

def get_match_result(
    home_team: str,
    away_team: str,
    match_date: str,
    cache_enabled: bool = True,
) -> str | None:
    """
    Pobiera wynik meczu ze FlashScore (mobi).
    """
    try:
        date_obj = datetime.fromisoformat(match_date)
    except Exception:
        log.warning("Niepoprawny format daty: %s", match_date)
        return None

    # Cache check
    if cache_enabled:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file = CACHE_DIR / f"{match_date}.json"
        if cache_file.exists():
            try:
                import json
                with open(cache_file, "r", encoding="utf-8") as f:
                    cache = json.load(f)
                    key = f"{normalize_team_name(home_team)}_{normalize_team_name(away_team)}"
                    if key in cache:
                        log.debug("Cache hit: %s", key)
                        return cache[key]
            except Exception: pass

    # Oblicz offset dla Flashscore.mobi (?d=X)
    # d=0 (dzisiaj), d=-1 (wczoraj) itp.
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    diff = (date_obj - today).days
    
    # Flashscore.mobi obsługuje zwykle około 7 dni wstecz/przód
    if abs(diff) > 7:
        log.info("Data %s jest poza zasięgiem Flashscore.mobi (offset %d).", match_date, diff)
        # Tu można by dodać fallback na search, ale na razie logujemy błąd
        return None

    url = f"{FLASHSCORE_MOBI_URL}/?d={diff}&s=1"
    print(f"[FlashScore] Pobieram wyniki z: {url}")
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 13_5 like Mac OS X) AppleWebKit/605.1.15"
        }
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        
        # Log fragmentu treści (jak prosił użytkownik)
        snippet = r.text[:300].replace('\n', ' ')
        print(f"[FlashScore] Treść (fragment): {snippet}...")

        result = _parse_mobi_html(r.text, home_team, away_team)
        
        if result and cache_enabled:
            # Zapisz do cache
            try:
                import json
                cache_file = CACHE_DIR / f"{match_date}.json"
                data = {}
                if cache_file.exists():
                    with open(cache_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                key = f"{normalize_team_name(home_team)}_{normalize_team_name(away_team)}"
                data[key] = result
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
            except Exception as e:
                log.warning("Błąd zapisu cache: %s", e)

        return result

    except Exception as e:
        log.error("Błąd scrapowania FlashScore (%s vs %s): %s", home_team, away_team, e)
        return None

def _parse_mobi_html(html: str, home: str, away: str) -> str | None:
    """
    Parsuje HTML z wersji mobi w poszukiwaniu meczu.
    Struktura: <span>19:00</span>Home - Away <a ...>2:1</a><br />
    """
    # Używamy regex na liniach dla szybkości i prostoty
    # Najpierw normalizujemy wejściowe nazwy
    nh = normalize_team_name(home)
    na = normalize_team_name(away)
    
    # Szukamy wzorca: TEAM1 - TEAM2 <a ...>SCORE</a>
    # Wykorzystujemy fakt, że mobi ma bardzo powtarzalną strukturę
    lines = html.split("<br />")
    
    best_match = None
    best_score = 0.0
    
    for line in lines:
        if "match/" not in line:
            continue
            
        # Wyciągnij tekst przed linkiem (drużyny) i w linku (wynik)
        # Przykład: <span>19:00</span>Vasteras SK - Hacken <a href="..." class="fin">3:3</a>
        m = re.search(r"</span>(.*?)\s*<a[^>]*>(.*?)</a>", line)
        if m:
            teams_raw = m.group(1)
            score = m.group(2).strip()
            
            if " - " in teams_raw:
                t_home_raw, t_away_raw = teams_raw.split(" - ", 1)
                
                # Porównaj fuzzy
                s_h = SequenceMatcher(None, normalize_team_name(t_home_raw), nh).ratio()
                s_a = SequenceMatcher(None, normalize_team_name(t_away_raw), na).ratio()
                total_score = (s_h + s_a) / 2
                
                if total_score > 0.85:
                    print(f"  [FlashScore] Potencjalne dopasowanie: {t_home_raw} - {t_away_raw} ({score}) | sim={total_score:.2f}")
                
                if total_score > 0.85 and total_score > best_score:
                    if score != "-:-" and ":" in score:
                        best_match = score.replace(":", "-")
                        best_score = total_score
                        
    if best_match:
        log.info("Znaleziono wynik na FlashScore: %s vs %s -> %s (score=%.2f)", home, away, best_match, best_score)
        return best_match
        
    return None

if __name__ == "__main__":
    # Test lokalny
    import sys
    logging.basicConfig(level=logging.INFO)
    
    # Przykład z zgłoszenia: BK Häcken vs GAIS
    # (Załóżmy że grali wczoraj)
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    res = get_match_result("BK Häcken", "GAIS", yesterday)
    print(f"RESULT: {res}")
