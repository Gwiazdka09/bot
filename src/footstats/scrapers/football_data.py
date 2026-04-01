import time
import requests
import pandas as pd
from footstats.utils.cache import _cache_get, _cache_set
from footstats.scrapers.base import _http_get
from footstats.utils.console import console
from footstats.utils.helpers import _s
from footstats.config import ENV_FOOTBALL
from rich.table import Table
from rich.panel import Panel
from rich import box

# ================================================================
#  MODUL 4 - KLIENT API
# ================================================================

# Liczba druzyn per liga (do Importance Index)
_LIGI_N_DRUZYN: dict = {
    "PL": 20, "PD": 20, "BL1": 18, "SA": 20, "FL1": 18,
    "PPL": 18, "DED": 18, "ELC": 24, "CL": 36,
    "EC": 24, "WC": 32, "BSA": 20,
}

# Fallback jesli /competitions nie dziala
_LIGI_FALLBACK: list = [
    {"nazwa": "Bundesliga",                    "kod": "BL1", "kraj": "Niemcy",     "druzyny": 18},
    {"nazwa": "Campeonato Brasileiro Serie A", "kod": "BSA", "kraj": "Brazylia",   "druzyny": 20},
    {"nazwa": "Championship",                  "kod": "ELC", "kraj": "Anglia D2",  "druzyny": 24},
    {"nazwa": "Eredivisie",                    "kod": "DED", "kraj": "Holandia",   "druzyny": 18},
    {"nazwa": "FIFA World Cup",                "kod": "WC",  "kraj": "Swiat",      "druzyny": 32},
    {"nazwa": "Ligue 1",                       "kod": "FL1", "kraj": "Francja",    "druzyny": 18},
    {"nazwa": "Premier League",                "kod": "PL",  "kraj": "Anglia",     "druzyny": 20},
    {"nazwa": "Primera Division",              "kod": "PD",  "kraj": "Hiszpania",  "druzyny": 20},
    {"nazwa": "Primeira Liga",                 "kod": "PPL", "kraj": "Portugalia", "druzyny": 18},
    {"nazwa": "Serie A",                       "kod": "SA",  "kraj": "Wlochy",     "druzyny": 20},
    {"nazwa": "UEFA Champions League",         "kod": "CL",  "kraj": "Europa",     "druzyny": 36},
    {"nazwa": "UEFA European Championship",    "kod": "EC",  "kraj": "Europa",     "druzyny": 24},
]

class APIClient:
    """Klient API football-data.org z cache 30min i rate guard."""

    def __init__(self, api_key: str):
        self.headers = {"X-Auth-Token": api_key}

    def get(self, endpoint: str, params: dict = None) -> dict | None:
        params_str  = "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
        cache_klucz = f"{endpoint}?{params_str}"
        z_cache = _cache_get(cache_klucz)
        if z_cache is not None:
            return z_cache
        dane = _http_get(endpoint, params, self.headers)
        if dane is not None:
            _cache_set(cache_klucz, dane)
        return dane

    def pobierz_ligi_free(self) -> list:
        """
        Pobiera liste ligz /v4/competitions, filtruje plan=TIER_ONE.
        Zwraca posortowana liste slownikow.
        """
        dane = self.get("/competitions")
        if not dane:
            console.print("[yellow]Nie mozna pobrac listy lig z API. Uzywam listy statycznej.[/yellow]")
            return _LIGI_FALLBACK

        free = []
        for comp in dane.get("competitions", []):
            if comp.get("plan", "") != "TIER_ONE":
                continue
            kod   = _s(comp.get("code"), "?")
            nazwa = _s(comp.get("name"), kod)
            kraj  = _s(comp.get("area", {}).get("name"), "?")
            n_dr  = _LIGI_N_DRUZYN.get(kod, 20)
            free.append({"nazwa": nazwa, "kod": kod, "kraj": kraj, "druzyny": n_dr})

        free.sort(key=lambda x: x["nazwa"])
        return free if free else _LIGI_FALLBACK

    def tabela(self, kod: str) -> pd.DataFrame | None:
        dane = self.get(f"/competitions/{kod}/standings")
        if not dane or "standings" not in dane:
            return None
        wiersze = []
        for w in dane["standings"][0]["table"]:
            wiersze.append({
                "Poz.":    w["position"],
                "Druzyna": _s(w["team"].get("shortName") or w["team"].get("name")),
                "M":       w["playedGames"],
                "W":       w["won"],
                "R":       w["draw"],
                "P":       w["lost"],
                "BZ":      w["goalsFor"],
                "BS":      w["goalsAgainst"],
                "Bramki":  f"{w['goalsFor']}:{w['goalsAgainst']}",
                "+/-":     w["goalDifference"],
                "Pkt":     w["points"],
            })
        return pd.DataFrame(wiersze)

    def wyniki(self, kod: str, limit: int = 100) -> pd.DataFrame | None:
        dane = self.get(f"/competitions/{kod}/matches",
                        params={"status": "FINISHED", "limit": limit})
        if not dane:
            return None
        mecze = []
        for m in dane.get("matches", []):
            ft = m.get("score", {}).get("fullTime", {})
            gg, ga = ft.get("home"), ft.get("away")
            if gg is None or ga is None:
                continue
            gosp = _s(m["homeTeam"].get("shortName") or m["homeTeam"].get("name"))
            gosc = _s(m["awayTeam"].get("shortName") or m["awayTeam"].get("name"))
            if gosp == "-" or gosc == "-":
                continue
            mecze.append({
                "data":        m["utcDate"][:10],
                "data_full":   m["utcDate"],
                "gospodarz":   gosp,
                "goscie":      gosc,
                "gole_g":      int(gg),
                "gole_a":      int(ga),
                "kolejka":     m.get("matchday"),
                "stage":       m.get("stage", "REGULAR_SEASON"),
                "competition": _s(m.get("competition", {}).get("code"), "?"),
            })
        return pd.DataFrame(mecze) if mecze else None

    def nadchodzace(self, kod: str, limit: int = 40) -> pd.DataFrame | None:
        dane = self.get(f"/competitions/{kod}/matches",
                        params={"status": "SCHEDULED", "limit": limit})
        if not dane:
            return None
        mecze = []
        for m in dane.get("matches", []):
            gosp = _s(m["homeTeam"].get("shortName") or m["homeTeam"].get("name"))
            gosc = _s(m["awayTeam"].get("shortName") or m["awayTeam"].get("name"))
            if gosp == "-" or gosc == "-":
                continue
            agg = m.get("score", {}).get("aggregateScore") or {}
            mecze.append({
                "data":        m["utcDate"][:10],
                "data_full":   m["utcDate"],
                "godzina":     m["utcDate"][11:16] + " UTC",
                "gospodarz":   gosp,
                "goscie":      gosc,
                "kolejka":     _s(m.get("matchday"), "?"),
                "stage":       m.get("stage", "REGULAR_SEASON"),
                "first_leg_g": agg.get("homeScore"),
                "first_leg_a": agg.get("awayScore"),
            })
        return pd.DataFrame(mecze) if mecze else None
