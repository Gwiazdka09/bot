import logging

logger = logging.getLogger(__name__)

"""
form_scraper.py – Dual form scraper: SofaScore (primary) + FlashScore (fallback)

SofaScore blokuje bezpośrednie requests (403), więc używamy Playwright
(przeglądarka z prawdziwymi cookies i fingerprint).

Pobiera dla drużyny:
- Ostatnie 5 wyników (forma W/D/L)
- Gole strzelone/stracone
- Kontuzje

Użycie:
    python -m footstats.scrapers.form_scraper "Stoke City" "Birmingham City"
    python -m footstats.scrapers.form_scraper "PSG"
"""

import json
import sys
import time
from pathlib import Path
from datetime import datetime
from typing import Optional
from urllib.parse import quote

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    PLAYWRIGHT_OK = True
except ImportError:
    PLAYWRIGHT_OK = False
    logger.info("[FormScraper] UWAGA: playwright niedostępny, zainstaluj: pip install playwright && playwright install chromium")

SOFA_BASE = "https://api.sofascore.com/api/v1"
CACHE_DIR = Path("cache/form")
CACHE_TTL_HOURS = 6

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


# ── Cache ─────────────────────────────────────────────────────────────────────
def _cache_path(key: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in key.lower())
    return CACHE_DIR / f"{safe}_{datetime.now().strftime('%Y%m%d')}.json"


def _load_cache(key: str) -> Optional[dict]:
    p = _cache_path(key)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        saved = datetime.fromisoformat(data.get("_cached_at", "2000-01-01T00:00:00"))
        if (datetime.now() - saved).total_seconds() / 3600 < CACHE_TTL_HOURS:
            return data
    except Exception:
        pass
    return None


def _save_cache(key: str, data: dict):
    data["_cached_at"] = datetime.now().isoformat()
    _cache_path(key).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── Playwright-based SofaScore API ────────────────────────────────────────────
def _sofa_fetch(page, path: str) -> Optional[dict]:
    """Pobiera JSON z SofaScore API przez nawigację przeglądarki (omija 403/CORS)."""
    url = f"{SOFA_BASE}{path}"
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=12000)
        if response is None or response.status >= 400:
            # 404 = brak danych (np. brak kontuzji) — nie logujemy jako błąd
            if response and response.status != 404:
                logger.info(f"[SofaScore] HTTP {response.status}: {path}")
            return None
        # JSON jest w <pre> lub bezpośrednio w body
        try:
            content = page.inner_text("pre")
        except Exception:
            content = page.evaluate("() => document.body.innerText")
        return json.loads(content)
    except Exception as e:
        logger.info(f"[SofaScore] Wyjątek {path}: {e}")
        return None


def _sofa_session():
    """Tworzy sesję Playwright do wywołań SofaScore API."""
    if not PLAYWRIGHT_OK:
        return None
    p = sync_playwright().start()
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(
        user_agent=_UA,
        extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.sofascore.com/",
        },
    )
    page = ctx.new_page()
    return p, browser, page


def find_team_id(team_name: str, page=None) -> Optional[int]:
    """Szuka ID drużyny piłkarskiej w SofaScore."""
    cache_key = f"sofa_id_{team_name}"
    cached = _load_cache(cache_key)
    if cached and "id" in cached:
        return cached["id"]

    own_session = page is None
    if own_session:
        if not PLAYWRIGHT_OK:
            return None
        sess = _sofa_session()
        if sess is None:
            return None
        p, browser, page = sess

    try:
        data = _sofa_fetch(page, f"/search/all?q={quote(team_name)}")
        if not data:
            return None

        # API zwraca {"results": [...]} lub {"groups": [...]}
        items = data.get("results") or []
        if not items:
            for group in data.get("groups", []):
                items.extend(group.get("hits", []))

        for item in items:
            entity = item.get("entity", item)  # czasem entity jest bezpośrednio
            sport = entity.get("sport", {})
            if sport.get("slug") == "football":
                tid = entity.get("id")
                name = entity.get("name", "")
                if tid:
                    logger.info(f"[SofaScore] ID: {name} = {tid}")
                    _save_cache(cache_key, {"id": tid, "name": name})
                    return tid
    finally:
        if own_session:
            browser.close()
            p.stop()

    logger.info(f"[SofaScore] Nie znaleziono: {team_name}")
    return None


def get_form_sofascore(team_id: int, team_name: str, page=None) -> dict:
    """Pobiera ostatnie 5 wyników + kontuzje z SofaScore."""
    cache_key = f"sofa_form_{team_id}"
    cached = _load_cache(cache_key)
    if cached and cached.get("form"):
        return cached

    own_session = page is None
    if own_session:
        if not PLAYWRIGHT_OK:
            return _empty_form(team_name, "brak playwright")
        sess = _sofa_session()
        if sess is None:
            return _empty_form(team_name, "błąd sesji")
        p, browser, page = sess

    result = _empty_form(team_name, "sofascore")
    result["team_id"] = team_id

    try:
        # Ostatnie mecze
        events_data = _sofa_fetch(page, f"/team/{team_id}/events/last/0")
        if events_data:
            events = events_data.get("events", [])
            completed = [
                e for e in events
                if e.get("status", {}).get("type") == "finished"
            ]
            for ev in completed[-5:]:
                home_team = ev.get("homeTeam", {})
                away_team = ev.get("awayTeam", {})
                h_score = ev.get("homeScore", {}).get("current")
                a_score = ev.get("awayScore", {}).get("current")
                if h_score is None or a_score is None:
                    continue

                is_home = home_team.get("id") == team_id
                opp = away_team if is_home else home_team
                gf = h_score if is_home else a_score
                ga = a_score if is_home else h_score

                outcome = "W" if gf > ga else ("L" if gf < ga else "D")
                result["form"].append(outcome)
                result["goals_scored"] += gf
                result["goals_conceded"] += ga

                ts = ev.get("startTimestamp", 0)
                try:
                    date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
                except Exception:
                    date_str = "?"

                result["matches"].append({
                    "opponent": opp.get("name", "?"),
                    "opponent_id": opp.get("id"),
                    "score": f"{gf}:{ga}",
                    "home_away": "H" if is_home else "A",
                    "outcome": outcome,
                    "date": date_str,
                    "tournament": ev.get("tournament", {}).get("name", "?"),
                })

        # Kontuzje (endpoint może nie istnieć dla danej drużyny — 404 to OK)
        inj_data = _sofa_fetch(page, f"/team/{team_id}/injury")
        if inj_data and "_error" not in inj_data:
            for inj in inj_data.get("injuries", []):
                player = inj.get("player", {})
                result["injuries"].append({
                    "name": player.get("name", "?"),
                    "position": player.get("position", "?"),
                    "return": inj.get("returnToTeam", "?"),
                    "reason": inj.get("injuryDetails", ""),
                })

    finally:
        if own_session:
            browser.close()
            p.stop()

    _save_cache(cache_key, result)
    return result


# ── FlashScore fallback ───────────────────────────────────────────────────────
def get_form_flashscore(team_name: str, page=None) -> Optional[dict]:
    """Pobiera formę z FlashScore (zapasowo gdy SofaScore nie działa)."""
    if not PLAYWRIGHT_OK:
        return None

    own_session = page is None
    if own_session:
        sess = _sofa_session()
        if sess is None:
            return None
        p, browser, page = sess

    result = _empty_form(team_name, "flashscore")
    search_url = f"https://www.flashscore.pl/search/?q={quote(team_name)}"

    try:
        page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
        time.sleep(2)

        team_url = None
        links = page.query_selector_all("a[href*='/team/']")
        for link in links:
            text = link.inner_text().strip()
            href = link.get_attribute("href") or ""
            if team_name.lower()[:5] in text.lower() and "/team/" in href:
                team_url = "https://www.flashscore.pl" + href if href.startswith("/") else href
                break

        if not team_url:
            logger.info(f"[FlashScore] Nie znaleziono: {team_name}")
            return None

        results_url = team_url.rstrip("/") + "/wyniki/"
        page.goto(results_url, wait_until="domcontentloaded", timeout=20000)
        time.sleep(2)

        count = 0
        for row in page.query_selector_all("[class*='event__match']"):
            if count >= 5:
                break
            try:
                home_el = row.query_selector("[class*='homeParticipant']")
                away_el = row.query_selector("[class*='awayParticipant']")
                sh_el = row.query_selector("[class*='score--home']")
                sa_el = row.query_selector("[class*='score--away']")
                if not all([home_el, away_el, sh_el, sa_el]):
                    continue

                home_name = home_el.inner_text().strip()
                away_name = away_el.inner_text().strip()
                gh = int(sh_el.inner_text().strip())
                ga = int(sa_el.inner_text().strip())

                is_home = team_name.lower()[:5] in home_name.lower()
                gf = gh if is_home else ga
                gc = ga if is_home else gh
                opp = away_name if is_home else home_name
                outcome = "W" if gf > gc else ("L" if gf < gc else "D")

                result["form"].append(outcome)
                result["goals_scored"] += gf
                result["goals_conceded"] += gc
                result["matches"].append({
                    "opponent": opp,
                    "score": f"{gf}:{gc}",
                    "home_away": "H" if is_home else "A",
                    "outcome": outcome,
                    "date": "?",
                })
                count += 1
            except Exception:
                continue

    except Exception as e:
        logger.info(f"[FlashScore] Błąd: {e}")
        return None
    finally:
        if own_session:
            browser.close()
            p.stop()

    return result if result["form"] else None


# ── Główna logika ─────────────────────────────────────────────────────────────
def pobierz_forme(team_name: str) -> dict:
    """
    Pobiera formę drużyny: SofaScore (Playwright) → FlashScore (fallback).
    Zawsze zwraca słownik.
    """
    if not PLAYWRIGHT_OK:
        return _empty_form(team_name, "brak playwright")

    sess = _sofa_session()
    if sess is None:
        return _empty_form(team_name, "błąd sesji")
    p, browser, page = sess

    try:
        # SofaScore
        tid = find_team_id(team_name, page)
        if tid:
            data = get_form_sofascore(tid, team_name, page)
            if data.get("form"):
                return data
            logger.info(f"[Form] SofaScore: brak zakończonych meczów dla {team_name}")

        # FlashScore fallback (nowa sesja, stara już skompromitowana)
    finally:
        browser.close()
        p.stop()

    data_fs = get_form_flashscore(team_name)
    if data_fs and data_fs.get("form"):
        logger.info(f"[Form] {team_name}: {data_fs['form']} (FlashScore)")
        return data_fs

    logger.info(f"[Form] Brak danych dla: {team_name}")
    return _empty_form(team_name, "brak")


def pobierz_forme_meczu(team_home: str, team_away: str) -> dict:
    """
    Pobiera formę obu drużyn w jednej sesji Playwright + H2H.
    Zwraca: {home: {...}, away: {...}, h2h: [...]}
    """
    if not PLAYWRIGHT_OK:
        return {
            "home": _empty_form(team_home, "brak playwright"),
            "away": _empty_form(team_away, "brak playwright"),
            "h2h": [],
        }

    sess = _sofa_session()
    if sess is None:
        return {
            "home": _empty_form(team_home, "błąd sesji"),
            "away": _empty_form(team_away, "błąd sesji"),
            "h2h": [],
        }
    p, browser, page = sess

    home_data = _empty_form(team_home, "brak")
    away_data = _empty_form(team_away, "brak")

    try:
        # Gospodarz
        tid_h = find_team_id(team_home, page)
        if tid_h:
            home_data = get_form_sofascore(tid_h, team_home, page)

        # Gość
        tid_a = find_team_id(team_away, page)
        if tid_a:
            away_data = get_form_sofascore(tid_a, team_away, page)

    finally:
        browser.close()
        p.stop()

    # FlashScore fallback jeśli potrzeba
    if not home_data.get("form"):
        fs = get_form_flashscore(team_home)
        if fs:
            home_data = fs
    if not away_data.get("form"):
        fs = get_form_flashscore(team_away)
        if fs:
            away_data = fs

    # H2H
    h2h = []
    away_id = away_data.get("team_id")
    away_low = team_away.lower()
    for m in home_data.get("matches", []):
        opp = m.get("opponent", "")
        opp_id = m.get("opponent_id")
        if (away_id and opp_id == away_id) or away_low[:6] in opp.lower():
            h2h.append({**m, "perspective": team_home})

    return {"home": home_data, "away": away_data, "h2h": h2h}


# ── Helpers ───────────────────────────────────────────────────────────────────
def _empty_form(team: str, source: str = "brak") -> dict:
    return {
        "team": team,
        "team_id": None,
        "form": [],
        "goals_scored": 0,
        "goals_conceded": 0,
        "matches": [],
        "injuries": [],
        "source": source,
    }


def formatuj_forme(data: dict) -> str:
    """Czytelny raport formy drużyny."""
    team = data.get("team", "?")
    form = data.get("form", [])
    gs = data.get("goals_scored", 0)
    gc = data.get("goals_conceded", 0)
    inj = data.get("injuries", [])
    matches = data.get("matches", [])
    src = data.get("source", "?")

    form_str = " ".join(form) if form else "brak"
    wins, draws, losses = form.count("W"), form.count("D"), form.count("L")

    inj_lines = [
        f"  - {i['name']} ({i.get('position','?')}) → {i.get('return','?')}"
        for i in inj[:5]
    ] or ["  brak kontuzji"]

    match_lines = [
        f"  [{m.get('outcome','?')}] {'vs' if m.get('home_away')=='H' else '@'} "
        f"{m.get('opponent','?')} {m.get('score','?')} ({m.get('date','?')})"
        for m in matches
    ] or ["  brak"]

    return (
        f"Drużyna: {team} [{src}]\n"
        f"Forma (ost. 5): {form_str}  ({wins}W {draws}D {losses}L)\n"
        f"Gole: +{gs} -{gc}\n"
        f"Ostatnie mecze:\n" + "\n".join(match_lines) + "\n"
        f"Kontuzje:\n" + "\n".join(inj_lines)
    )


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        logger.info("Użycie:")
        logger.info("  python -m footstats.scrapers.form_scraper 'Drużyna'")
        logger.info("  python -m footstats.scrapers.form_scraper 'Gospodarz' 'Gości'")
        sys.exit(0)

    if len(sys.argv) >= 3:
        home, away = sys.argv[1], sys.argv[2]
        logger.info(f"\n=== MECZ: {home} vs {away} ===\n")
        wynik = pobierz_forme_meczu(home, away)
        logger.info("── GOSPODARZ ──────────────────────────")
        print(formatuj_forme(wynik["home"]))
        logger.info("\n── GOŚĆ ────────────────────────────────")
        print(formatuj_forme(wynik["away"]))
        if wynik["h2h"]:
            logger.info("\n── H2H ──────────────────────────────────")
            for m in wynik["h2h"]:
                logger.info(f"  {m['date']} {m['perspective']} {m['score']} {m['opponent']}")
        else:
            logger.info("\n── H2H: brak wspólnych meczów w ost. 5 ──")
    else:
        team = sys.argv[1]
        logger.info(f"\n=== FORMA: {team} ===\n")
        print(formatuj_forme(pobierz_forme(team)))
