import logging

logger = logging.getLogger(__name__)

"""
enriched.py – Wzbogacanie danych przed analizą meczową
=======================================================
Źródła:
    1. Kontuzje/zawieszenia  – football-data.org API
    2. Konferencje prasowe   – Google News RSS (feedparser)
    3. Forma xG              – Bzzoiro API
    4. Sztuczna murawa       – słownik hardcoded

Użycie:
    from footstats.scrapers.enriched import enrich_match_data
    dane = enrich_match_data("Arsenal", "Chelsea", "2026-03-30")

    python -m footstats.scrapers.enriched Arsenal Chelsea 2026-03-30
"""

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

try:
    import feedparser
except ImportError:
    feedparser = None

from dotenv import load_dotenv
load_dotenv()

FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY", "").strip()
BZZOIRO_KEY      = os.getenv("BZZOIRO_KEY", "").strip()

TIMEOUT_S   = 8
CACHE_TTL_H = 2
CACHE_DIR   = Path("cache/enriched")
PRESS_CHARS = 600

# Drużyny grające na sztucznej murawie
SZTUCZNA_MURAWA: dict[str, bool] = {
    "Bodo/Glimt":  True,
    "Molde":       True,
    "Vikingur":    True,
    "Astana":      True,
    "Ferencvaros": True,
}


# ── Cache plikowy ─────────────────────────────────────────────────────────

def _cache_path(key: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)
    return CACHE_DIR / f"{safe}.json"


def _cache_get(key: str) -> dict | None:
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        saved_at = datetime.fromisoformat(data.get("_ts", "2000-01-01"))
        if datetime.now() - saved_at < timedelta(hours=CACHE_TTL_H):
            return data.get("payload")
    except Exception:
        pass
    return None


def _cache_set(key: str, payload) -> None:
    try:
        path = _cache_path(key)
        path.write_text(
            json.dumps({"_ts": datetime.now().isoformat(), "payload": payload},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


# ── 1. Kontuzje / zawieszenia – football-data.org ────────────────────────

def _fdb_get(endpoint: str) -> dict | None:
    if not FOOTBALL_API_KEY:
        return None
    url = f"https://api.football-data.org/v4{endpoint}"
    try:
        r = requests.get(url, headers={"X-Auth-Token": FOOTBALL_API_KEY},
                         timeout=TIMEOUT_S)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def _szukaj_team_id(nazwa: str) -> int | None:
    cache_key = f"fdb_teamid_{nazwa}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached.get("id")

    data = _fdb_get(f"/teams/?name={requests.utils.quote(nazwa)}")
    if data and data.get("teams"):
        team = data["teams"][0]
        _cache_set(cache_key, {"id": team["id"], "name": team.get("name")})
        return team["id"]

    data2 = _fdb_get("/teams/")
    if data2 and data2.get("teams"):
        nazwa_low = nazwa.lower()
        for t in data2["teams"]:
            if nazwa_low in t.get("name", "").lower() or nazwa_low in t.get("shortName", "").lower():
                _cache_set(cache_key, {"id": t["id"], "name": t.get("name")})
                return t["id"]
    return None


def pobierz_kontuzje(nazwa_druzyny: str) -> dict | None:
    """
    Pobiera kontuzje i zawieszenia drużyny z football-data.org.
    Zwraca dict z kluczami: team_id, team_name, squad_size, injured, suspended.
    """
    cache_key = f"kontuzje_{nazwa_druzyny}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    team_id = _szukaj_team_id(nazwa_druzyny)
    if not team_id:
        return None

    data = _fdb_get(f"/teams/{team_id}/")
    if not data:
        return None

    squad     = data.get("squad", [])
    injured   = []
    suspended = []

    for gracz in squad:
        status = (gracz.get("status") or "").lower()
        if "injur" in status or "kontuz" in status:
            injured.append({"name": gracz.get("name", "?"), "position": gracz.get("position", "?")})
        elif "suspend" in status or "zawiesz" in status or "ban" in status:
            suspended.append({"name": gracz.get("name", "?"), "position": gracz.get("position", "?")})

    wynik = {
        "team_id":    team_id,
        "team_name":  data.get("name", nazwa_druzyny),
        "squad_size": len(squad),
        "injured":    injured,
        "suspended":  suspended,
    }
    _cache_set(cache_key, wynik)
    return wynik


# ── 2. Konferencje prasowe – Google News RSS ──────────────────────────────

def pobierz_konferencje(nazwa_druzyny: str) -> dict | None:
    """
    Pobiera najnowszy artykuł o konferencji prasowej z Google News RSS.
    Zwraca dict z kluczami: title, link, published, snippet.
    """
    if feedparser is None:
        return None

    cache_key = f"press_{nazwa_druzyny}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    query = f"{nazwa_druzyny} press conference pre-match"
    url   = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=en&gl=US&ceid=US:en"

    try:
        feed = feedparser.parse(url)
        if feed.entries:
            wpis = feed.entries[0]
            tresc = wpis.get("summary", "") or ""
            import re as _re
            tresc_czysta = _re.sub(r"<[^>]+>", "", tresc).strip()
            wynik = {
                "title":     wpis.get("title", ""),
                "link":      wpis.get("link", ""),
                "published": wpis.get("published", ""),
                "snippet":   tresc_czysta[:PRESS_CHARS],
            }
            _cache_set(cache_key, wynik)
            return wynik
    except Exception:
        pass
    return None


# ── 3. Forma xG – Bzzoiro API ─────────────────────────────────────────────

def _bzz_get(path: str, params: dict = None) -> dict | None:
    if not BZZOIRO_KEY:
        return None
    try:
        r = requests.get(
            f"https://sports.bzzoiro.com/api{path}",
            headers={"Authorization": f"Token {BZZOIRO_KEY}"},
            params=params, timeout=TIMEOUT_S,
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def pobierz_forme_xg(nazwa_druzyny: str, ostatnie_n: int = 5) -> dict | None:
    """
    Pobiera formę xG z ostatnich N meczów przez Bzzoiro API.
    Zwraca dict z: team, mecze, xg_scored_avg, xg_conc_avg, historia.
    """
    cache_key = f"xg_{nazwa_druzyny}_{ostatnie_n}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # Znajdź team_id w Bzzoiro
    data_teams = _bzz_get("/teams/", {"name": nazwa_druzyny})
    team_id = None
    if data_teams:
        wyniki = data_teams.get("results", [])
        if wyniki:
            team_id = wyniki[0].get("id")

    if not team_id:
        return None

    data_od = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    data_do = datetime.now().strftime("%Y-%m-%d")

    data = _bzz_get("/events/", {
        "team": team_id, "date_from": data_od, "date_to": data_do, "status": "finished",
    })
    if not data:
        return None

    zdarzenia = sorted(
        data.get("results", []),
        key=lambda e: e.get("event_date", ""),
        reverse=True,
    )[:ostatnie_n]

    if not zdarzenia:
        return None

    historia  = []
    xg_scored = []
    xg_conc   = []

    for ev in zdarzenia:
        home_id = ev.get("home_team", {}).get("id") if isinstance(ev.get("home_team"), dict) else None
        jest_g  = (home_id == team_id)
        stats   = ev.get("stats") or {}

        if jest_g:
            xgf = stats.get("home_xg") or stats.get("xg_home") or ev.get("home_xg")
            xga = stats.get("away_xg") or stats.get("xg_away") or ev.get("away_xg")
            prz = ev.get("away_team", {}).get("name", "?") if isinstance(ev.get("away_team"), dict) else "?"
        else:
            xgf = stats.get("away_xg") or stats.get("xg_away") or ev.get("away_xg")
            xga = stats.get("home_xg") or stats.get("xg_home") or ev.get("home_xg")
            prz = ev.get("home_team", {}).get("name", "?") if isinstance(ev.get("home_team"), dict) else "?"

        wpis = {
            "date":       str(ev.get("event_date", ""))[:10],
            "opponent":   prz,
            "xg_for":     float(xgf) if xgf is not None else None,
            "xg_against": float(xga) if xga is not None else None,
            "wynik":      ev.get("score", ev.get("result", "?")),
        }
        historia.append(wpis)
        if wpis["xg_for"]     is not None: xg_scored.append(wpis["xg_for"])
        if wpis["xg_against"] is not None: xg_conc.append(wpis["xg_against"])

    wynik = {
        "team":          nazwa_druzyny,
        "mecze":         len(historia),
        "xg_scored_avg": round(sum(xg_scored) / len(xg_scored), 2) if xg_scored else None,
        "xg_conc_avg":   round(sum(xg_conc)   / len(xg_conc),   2) if xg_conc   else None,
        "historia":      historia,
    }
    _cache_set(cache_key, wynik)
    return wynik


# ── 4. Sztuczna murawa ────────────────────────────────────────────────────

def sprawdz_murawe(nazwa_druzyny: str) -> bool:
    return SZTUCZNA_MURAWA.get(nazwa_druzyny, False)


# ── Główna funkcja ────────────────────────────────────────────────────────

def enrich_match_data(team_home: str, team_away: str, match_date: str = None) -> dict:
    """
    Wzbogaca dane o meczu: kontuzje, konferencje prasowe, xG, murawa.
    Zwraca dict z kluczami: meta, home_injuries, away_injuries,
    home_press, away_press, home_xg, away_xg, murawa.
    """
    logger.info(f"[Enriched] {team_home} vs {team_away} ({match_date or 'brak daty'})")

    wynik: dict = {
        "meta":          {"home": team_home, "away": team_away,
                          "match_date": match_date, "fetched_at": datetime.now().isoformat()},
        "home_injuries": None,
        "away_injuries": None,
        "home_press":    None,
        "away_press":    None,
        "home_xg":       None,
        "away_xg":       None,
        "murawa":        {"home_artificial": sprawdz_murawe(team_home),
                          "away_artificial": sprawdz_murawe(team_away)},
    }

    for key, fn, team in [
        ("home_injuries", pobierz_kontuzje,   team_home),
        ("away_injuries", pobierz_kontuzje,   team_away),
        ("home_press",    pobierz_konferencje, team_home),
        ("away_press",    pobierz_konferencje, team_away),
        ("home_xg",       pobierz_forme_xg,   team_home),
        ("away_xg",       pobierz_forme_xg,   team_away),
    ]:
        try:
            wynik[key] = fn(team)
            logger.info(f"[Enriched] {key}: {'OK' if wynik[key] else 'brak'}")
        except Exception as e:
            logger.info(f"[Enriched] {key}: błąd – {e}")

    logger.info("[Enriched] Gotowe.")
    return wynik


# ── Uruchomienie bezpośrednie ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    home = sys.argv[1] if len(sys.argv) > 1 else "Arsenal"
    away = sys.argv[2] if len(sys.argv) > 2 else "Chelsea"
    date = sys.argv[3] if len(sys.argv) > 3 else None

    dane = enrich_match_data(home, away, date)

    print("\n" + "=" * 60)
    logger.info(f"WZBOGACONE DANE: {home} vs {away}")
    print("=" * 60)

    inj_h = dane["home_injuries"]
    inj_a = dane["away_injuries"]
    for inj, name in [(inj_h, home), (inj_a, away)]:
        if inj:
            logger.info(f"\n[{name}] Skład: {inj['squad_size']} | Kontuzje: {len(inj['injured'])} | Zawieszenia: {len(inj['suspended'])}")
            for g in inj["injured"]:   logger.info(f"  - KONTUZJA: {g['name']} ({g['position']})")
            for g in inj["suspended"]: logger.info(f"  - ZAWIESZ:  {g['name']} ({g['position']})")

    for press, name in [(dane["home_press"], home), (dane["away_press"], away)]:
        if press:
            logger.info(f"\n[Press {name}] {press['title']}")
            logger.info(f"  {press['snippet'][:200]}...")

    for xg, name in [(dane["home_xg"], home), (dane["away_xg"], away)]:
        if xg:
            logger.info(f"\n[xG {name}] {xg['mecze']} meczów | strzelone avg: {xg['xg_scored_avg']} | stracone avg: {xg['xg_conc_avg']}")

    murawa = dane["murawa"]
    if murawa["home_artificial"]: logger.info(f"\n[Murawa] {home}: SZTUCZNA")
    if murawa["away_artificial"]: logger.info(f"[Murawa] {away}: SZTUCZNA")
