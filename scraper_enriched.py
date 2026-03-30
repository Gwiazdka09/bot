"""
scraper_enriched.py – Wzbogacanie danych przed analizą meczową
Rozszerzenie scraper_kursy.py o dane kontekstowe.

Użycie:
    from scraper_enriched import enrich_match_data
    dane = enrich_match_data("Arsenal", "Chelsea", "2026-03-30")

Źródła:
    1. Kontuzje/zawieszenia  – football-data.org API (FOOTBALL_API_KEY)
    2. Konferencje prasowe   – Google News RSS (feedparser)
    3. Forma xG              – Bzzoiro API (BZZOIRO_KEY)
    4. Sztuczna murawa       – słownik hardcoded
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

# ── Klucze API ─────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY", "").strip()
BZZOIRO_KEY      = os.getenv("BZZOIRO_KEY", "").strip()

# ── Konfiguracja ────────────────────────────────────────────────────────
TIMEOUT_S    = 8        # max sekund na jedno zapytanie HTTP
CACHE_TTL_H  = 2        # godziny ważności cache
CACHE_DIR    = Path("enriched_cache")
PRESS_CHARS  = 600      # ile znaków z artykułu prasowego

# ── Sztuczna murawa (hardcoded) ─────────────────────────────────────────
SZTUCZNA_MURAWA: dict[str, bool] = {
    "Bodo/Glimt":  True,
    "Molde":       True,
    "Vikingur":    True,
    "Astana":      True,
    "Ferencvaros": True,
}

# ── Cache plikowy ────────────────────────────────────────────────────────

def _cache_path(key: str) -> Path:
    CACHE_DIR.mkdir(exist_ok=True)
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


# ── 1. Kontuzje / zawieszenia – football-data.org ───────────────────────

def _fdb_get(endpoint: str) -> dict | None:
    """Wykonuje GET do football-data.org v4, zwraca JSON lub None."""
    if not FOOTBALL_API_KEY:
        return None
    url = f"https://api.football-data.org/v4{endpoint}"
    try:
        r = requests.get(
            url,
            headers={"X-Auth-Token": FOOTBALL_API_KEY},
            timeout=TIMEOUT_S,
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def _szukaj_team_id(nazwa: str) -> int | None:
    """Szuka team_id po nazwie drużyny w football-data.org."""
    cache_key = f"fdb_teamid_{nazwa}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached.get("id")

    data = _fdb_get(f"/teams/?name={requests.utils.quote(nazwa)}")
    if data and data.get("teams"):
        team = data["teams"][0]
        _cache_set(cache_key, {"id": team["id"], "name": team.get("name")})
        return team["id"]

    # Próba z pełnym przeszukaniem (lista TOP lig)
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
    Pobiera informacje o składzie i kontuzjach drużyny z football-data.org.

    Zwraca dict:
        {
          "team_id": int,
          "team_name": str,
          "squad_size": int,
          "injured": [{"name": str, "position": str}],
          "suspended": [{"name": str, "position": str}],
        }
    lub None jeśli błąd.
    """
    cache_key = f"kontuzje_{nazwa_druzyny}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    team_id = _szukaj_team_id(nazwa_druzyny)
    if not team_id:
        print(f"[Enriched] Nie znaleziono team_id dla: {nazwa_druzyny}")
        return None

    data = _fdb_get(f"/teams/{team_id}/")
    if not data:
        print(f"[Enriched] Brak odpowiedzi z football-data.org dla team_id={team_id}")
        return None

    squad = data.get("squad", [])
    injured   = []
    suspended = []

    for gracz in squad:
        status = (gracz.get("status") or "").lower()
        if "injur" in status or "kontuz" in status:
            injured.append({
                "name":     gracz.get("name", "?"),
                "position": gracz.get("position", "?"),
            })
        elif "suspend" in status or "zawiesz" in status or "ban" in status:
            suspended.append({
                "name":     gracz.get("name", "?"),
                "position": gracz.get("position", "?"),
            })

    wynik = {
        "team_id":   team_id,
        "team_name": data.get("name", nazwa_druzyny),
        "squad_size": len(squad),
        "injured":   injured,
        "suspended": suspended,
    }

    _cache_set(cache_key, wynik)
    return wynik


# ── 2. Konferencje prasowe – Google News RSS ─────────────────────────────

def pobierz_konferencje(nazwa_druzyny: str) -> dict | None:
    """
    Pobiera najnowszy artykuł o konferencji prasowej przed meczem.

    Zwraca dict:
        {
          "title": str,
          "link": str,
          "published": str,
          "snippet": str,   # pierwsze 600 znaków
        }
    lub None jeśli brak wyników / błąd.
    """
    if feedparser is None:
        print("[Enriched] feedparser nie jest zainstalowany: pip install feedparser")
        return None

    cache_key = f"press_{nazwa_druzyny}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    query  = f"{nazwa_druzyny} press conference pre-match"
    url    = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=en&gl=US&ceid=US:en"

    try:
        feed = feedparser.parse(url)
        if feed.entries:
            wpis = feed.entries[0]
            tresc = wpis.get("summary", "") or ""
            # feedparser zwraca HTML – usuwamy tagi
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
    except Exception as e:
        print(f"[Enriched] RSS błąd ({nazwa_druzyny}): {e}")

    return None


# ── 3. Forma xG – Bzzoiro API ─────────────────────────────────────────────

def _bzz_get(path: str, params: dict = None) -> dict | None:
    """Wykonuje GET do sports.bzzoiro.com, zwraca JSON lub None."""
    if not BZZOIRO_KEY:
        return None
    try:
        r = requests.get(
            f"https://sports.bzzoiro.com/api{path}",
            headers={"Authorization": f"Token {BZZOIRO_KEY}"},
            params=params,
            timeout=TIMEOUT_S,
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def _bzz_szukaj_team_id(nazwa: str) -> int | None:
    """Szuka team_id w Bzzoiro po nazwie drużyny."""
    cache_key = f"bzz_teamid_{nazwa}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached.get("id")

    data = _bzz_get("/teams/", {"name": nazwa})
    if data:
        wyniki = data.get("results", [])
        if wyniki:
            t = wyniki[0]
            _cache_set(cache_key, {"id": t["id"], "name": t.get("name")})
            return t["id"]

    return None


def pobierz_forme_xg(nazwa_druzyny: str, ostatnie_n: int = 5) -> dict | None:
    """
    Pobiera formę xG (Expected Goals) z ostatnich N meczów przez Bzzoiro API.

    Zwraca dict:
        {
          "team":          str,
          "mecze":         int,
          "xg_scored_avg": float,   # średnie xG strzelone
          "xg_conc_avg":  float,    # średnie xG stracone
          "historia": [
              {"date": str, "opponent": str, "xg_for": float, "xg_against": float, "wynik": str}
          ]
        }
    lub None jeśli brak danych.
    """
    cache_key = f"xg_{nazwa_druzyny}_{ostatnie_n}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    team_id = _bzz_szukaj_team_id(nazwa_druzyny)
    if not team_id:
        print(f"[Enriched] Bzzoiro: nie znaleziono team_id dla {nazwa_druzyny}")
        return None

    data_do  = datetime.now().strftime("%Y-%m-%d")
    data_od  = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")

    data = _bzz_get("/events/", {
        "team":      team_id,
        "date_from": data_od,
        "date_to":   data_do,
        "status":    "finished",
    })

    if not data:
        return None

    zdarzenia = data.get("results", [])
    # Sortuj malejąco po dacie i weź ostatnie N
    zdarzenia_sort = sorted(
        zdarzenia,
        key=lambda e: e.get("event_date", ""),
        reverse=True,
    )[:ostatnie_n]

    if not zdarzenia_sort:
        return None

    historia  = []
    xg_scored = []
    xg_conc   = []

    for ev in zdarzenia_sort:
        home_id = ev.get("home_team", {}).get("id") if isinstance(ev.get("home_team"), dict) else None
        jest_gospodarzem = (home_id == team_id)

        stats = ev.get("stats") or {}

        # Bzzoiro może trzymać xG w różnych polach – próbujemy kilka wariantów
        if jest_gospodarzem:
            xgf = (stats.get("home_xg") or stats.get("xg_home") or
                   ev.get("home_xg") or ev.get("xg", {}).get("home"))
            xga = (stats.get("away_xg") or stats.get("xg_away") or
                   ev.get("away_xg") or ev.get("xg", {}).get("away"))
            przeciwnik = ev.get("away_team", {}).get("name", "?") if isinstance(ev.get("away_team"), dict) else "?"
        else:
            xgf = (stats.get("away_xg") or stats.get("xg_away") or
                   ev.get("away_xg") or ev.get("xg", {}).get("away"))
            xga = (stats.get("home_xg") or stats.get("xg_home") or
                   ev.get("home_xg") or ev.get("xg", {}).get("home"))
            przeciwnik = ev.get("home_team", {}).get("name", "?") if isinstance(ev.get("home_team"), dict) else "?"

        wpis = {
            "date":       str(ev.get("event_date", ""))[:10],
            "opponent":   przeciwnik,
            "xg_for":     float(xgf) if xgf is not None else None,
            "xg_against": float(xga) if xga is not None else None,
            "wynik":      ev.get("score", ev.get("result", "?")),
        }
        historia.append(wpis)

        if wpis["xg_for"] is not None:
            xg_scored.append(wpis["xg_for"])
        if wpis["xg_against"] is not None:
            xg_conc.append(wpis["xg_against"])

    wynik = {
        "team":          nazwa_druzyny,
        "mecze":         len(historia),
        "xg_scored_avg": round(sum(xg_scored) / len(xg_scored), 2) if xg_scored else None,
        "xg_conc_avg":   round(sum(xg_conc)   / len(xg_conc),   2) if xg_conc   else None,
        "historia":      historia,
    }

    _cache_set(cache_key, wynik)
    return wynik


# ── 4. Sztuczna murawa ───────────────────────────────────────────────────

def sprawdz_murawe(nazwa_druzyny: str) -> bool:
    """Zwraca True jeśli drużyna gra na sztucznej murawie."""
    return SZTUCZNA_MURAWA.get(nazwa_druzyny, False)


# ── Główna funkcja ───────────────────────────────────────────────────────

def enrich_match_data(
    team_home: str,
    team_away: str,
    match_date: str = None,
) -> dict:
    """
    Wzbogaca dane o meczu o kontekst przed analizą.

    Parametry:
        team_home   – nazwa drużyny gospodarzy (str)
        team_away   – nazwa drużyny gości (str)
        match_date  – data meczu YYYY-MM-DD (str, opcjonalne)

    Zwraca dict z kluczami:
        meta          – informacje o meczu i timestampie
        home_injuries – kontuzje/zawieszenia (dict lub None)
        away_injuries – kontuzje/zawieszenia (dict lub None)
        home_press    – konferencja prasowa (dict lub None)
        away_press    – konferencja prasowa (dict lub None)
        home_xg       – forma xG (dict lub None)
        away_xg       – forma xG (dict lub None)
        murawa        – {"home_artificial": bool, "away_artificial": bool}
    """
    print(f"[Enriched] Wzbogacam dane: {team_home} vs {team_away} ({match_date or 'brak daty'})")

    wynik: dict = {
        "meta": {
            "home":       team_home,
            "away":       team_away,
            "match_date": match_date,
            "fetched_at": datetime.now().isoformat(),
        },
        "home_injuries": None,
        "away_injuries": None,
        "home_press":    None,
        "away_press":    None,
        "home_xg":       None,
        "away_xg":       None,
        "murawa": {
            "home_artificial": sprawdz_murawe(team_home),
            "away_artificial": sprawdz_murawe(team_away),
        },
    }

    # 1. Kontuzje
    try:
        wynik["home_injuries"] = pobierz_kontuzje(team_home)
        print(f"[Enriched] Kontuzje {team_home}: OK")
    except Exception as e:
        print(f"[Enriched] Kontuzje {team_home}: błąd – {e}")

    try:
        wynik["away_injuries"] = pobierz_kontuzje(team_away)
        print(f"[Enriched] Kontuzje {team_away}: OK")
    except Exception as e:
        print(f"[Enriched] Kontuzje {team_away}: błąd – {e}")

    # 2. Konferencje prasowe
    try:
        wynik["home_press"] = pobierz_konferencje(team_home)
        print(f"[Enriched] Press {team_home}: {'OK' if wynik['home_press'] else 'brak'}")
    except Exception as e:
        print(f"[Enriched] Press {team_home}: błąd – {e}")

    try:
        wynik["away_press"] = pobierz_konferencje(team_away)
        print(f"[Enriched] Press {team_away}: {'OK' if wynik['away_press'] else 'brak'}")
    except Exception as e:
        print(f"[Enriched] Press {team_away}: błąd – {e}")

    # 3. Forma xG
    try:
        wynik["home_xg"] = pobierz_forme_xg(team_home)
        print(f"[Enriched] xG {team_home}: {'OK' if wynik['home_xg'] else 'brak'}")
    except Exception as e:
        print(f"[Enriched] xG {team_home}: błąd – {e}")

    try:
        wynik["away_xg"] = pobierz_forme_xg(team_away)
        print(f"[Enriched] xG {team_away}: {'OK' if wynik['away_xg'] else 'brak'}")
    except Exception as e:
        print(f"[Enriched] xG {team_away}: błąd – {e}")

    print(f"[Enriched] Gotowe.")
    return wynik


# ── Uruchomienie bezpośrednie ────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    home = sys.argv[1] if len(sys.argv) > 1 else "Arsenal"
    away = sys.argv[2] if len(sys.argv) > 2 else "Chelsea"
    date = sys.argv[3] if len(sys.argv) > 3 else None

    dane = enrich_match_data(home, away, date)

    print("\n" + "=" * 60)
    print(f"WZBOGACONE DANE: {home} vs {away}")
    print("=" * 60)

    inj_h = dane["home_injuries"]
    inj_a = dane["away_injuries"]
    if inj_h:
        print(f"\n[{home}] Skład: {inj_h['squad_size']} graczy | "
              f"Kontuzjowani: {len(inj_h['injured'])} | Zawieszeni: {len(inj_h['suspended'])}")
        for g in inj_h["injured"]:
            print(f"  - KONTUZJA: {g['name']} ({g['position']})")
        for g in inj_h["suspended"]:
            print(f"  - ZAWIESZ:  {g['name']} ({g['position']})")

    if inj_a:
        print(f"\n[{away}] Skład: {inj_a['squad_size']} graczy | "
              f"Kontuzjowani: {len(inj_a['injured'])} | Zawieszeni: {len(inj_a['suspended'])}")
        for g in inj_a["injured"]:
            print(f"  - KONTUZJA: {g['name']} ({g['position']})")
        for g in inj_a["suspended"]:
            print(f"  - ZAWIESZ:  {g['name']} ({g['position']})")

    press_h = dane["home_press"]
    if press_h:
        print(f"\n[Press {home}] {press_h['title']}")
        print(f"  Opublikowano: {press_h['published']}")
        print(f"  {press_h['snippet'][:200]}...")

    press_a = dane["away_press"]
    if press_a:
        print(f"\n[Press {away}] {press_a['title']}")
        print(f"  Opublikowano: {press_a['published']}")
        print(f"  {press_a['snippet'][:200]}...")

    xg_h = dane["home_xg"]
    xg_a = dane["away_xg"]
    if xg_h:
        print(f"\n[xG {home}] Ostatnie {xg_h['mecze']} meczów | "
              f"Strzelone avg: {xg_h['xg_scored_avg']} | Stracone avg: {xg_h['xg_conc_avg']}")
    if xg_a:
        print(f"[xG {away}] Ostatnie {xg_a['mecze']} meczów | "
              f"Strzelone avg: {xg_a['xg_scored_avg']} | Stracone avg: {xg_a['xg_conc_avg']}")

    murawa = dane["murawa"]
    if murawa["home_artificial"]:
        print(f"\n[Murawa] {home}: SZTUCZNA")
    if murawa["away_artificial"]:
        print(f"[Murawa] {away}: SZTUCZNA")
