import json
import time
from datetime import datetime
from pathlib import Path
import requests
from footstats.config import CACHE_TTL_MIN
from footstats.utils.console import console

# ================================================================
#  MODUL 3 - HTTP + CACHE + RATE GUARD  (v2.7.1)
# ================================================================
#
#  Strategia cache dla 3 zrodel:
#
#    football-data.org  →  pamiec RAM,  TTL = CACHE_TTL_MIN  (30 min)
#    api-sports.io      →  dysk JSON,   TTL = 24h (1 req = 1% budzetu!)
#    sports.bzzoiro.com →  pamiec RAM,  TTL = CACHE_TTL_MIN  (30 min)
#
#  api-sports.io: 100 req/dzien = OSZCZEDNOSC KRYTYCZNA:
#    - Zawsze najpierw sprawdzaj dysk, potem siec
#    - TTL 24h: dane z wczoraj wciaz wazne dla historii/tabeli
#    - Nadpisuj tylko gdy dane sie roznia (n meczow, pozycje tabeli)
#    - Licznik dzienny: zapisany na dysku, reset o polnocy
#    - Ostrzezenie gdy < 20 req pozostalo
#    - BLOKADA gdy < 5 req (rezerwowe na krytyczne zapytania)
# ================================================================

_RAM_CACHE: dict = {}   # football-data.org + bzzoiro (in-memory)

CACHE_DIR     = Path(".cache")
AF_CACHE_FILE = CACHE_DIR / "af_cache.json"      # dane API-Football
AF_BUDGET_FILE= CACHE_DIR / "af_budget.json"      # licznik dzienny

AF_CACHE_TTL_H   = 24    # Disk cache TTL dla API-Football (godziny)
AF_BUDGET_DAILY  = 100   # maks. req/dzien API-Football
AF_WARN_THRESHOLD= 20    # ostrzegaj gdy tyle req zostalo
AF_BLOCK_THRESHOLD= 5    # blokuj automatyczne zapytania gdy tyle zostalo

# ── Rate guard (football-data.org, 10 req/min) ──────────────────────

_req_count = 0
_req_window_start = datetime.now()

def _rate_guard():
    global _req_count, _req_window_start
    now   = datetime.now()
    delta = (now - _req_window_start).total_seconds()
    if delta >= 60:
        _req_count = 0
        _req_window_start = now
    _req_count += 1
    if _req_count >= 9 and delta < 60:
        czekaj = int(61 - delta)
        console.print(
            f"[bold yellow]Zbliżamy sie do limitu API (9/min). "
            f"Czekam {czekaj}s...[/bold yellow]"
        )
        time.sleep(czekaj + 1)
        _req_count = 1
        _req_window_start = datetime.now()

# ── RAM cache (FDB + Bzzoiro) ────────────────────────────────────────

def _cache_get(klucz: str):
    wpis = _RAM_CACHE.get(klucz)
    if wpis:
        delta = (datetime.now() - wpis["ts"]).total_seconds()
        if delta < CACHE_TTL_MIN * 60:
            console.print(f"[dim cyan]Cache HIT [{int(delta//60)}min]: {klucz[:55]}[/dim cyan]")
            return wpis["data"]
    return None

def _cache_set(klucz: str, dane):
    _RAM_CACHE[klucz] = {"ts": datetime.now(), "data": dane}

# ── Disk cache (API-Football, TTL 24h) ──────────────────────────────

def _af_ensure_dir():
    CACHE_DIR.mkdir(exist_ok=True)

def _af_load_disk_cache() -> dict:
    """Laduje caly plik cache z dysku."""
    _af_ensure_dir()
    if AF_CACHE_FILE.exists():
        try:
            return json.loads(AF_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def _af_save_disk_cache(cache: dict):
    """Zapisuje cache na dysk."""
    _af_ensure_dir()
    try:
        AF_CACHE_FILE.write_text(
            json.dumps(cache, ensure_ascii=False, indent=None, separators=(',',':')),
            encoding="utf-8"
        )
    except Exception:
        pass

def _af_cache_get(klucz: str) -> dict | None:
    """
    Sprawdza disk cache API-Football.
    Zwraca dane jesli istnieja i TTL < 24h. Inaczej None.
    """
    cache = _af_load_disk_cache()
    wpis  = cache.get(klucz)
    if not wpis:
        return None
    try:
        ts    = datetime.fromisoformat(wpis["ts"])
        delta = (datetime.now() - ts).total_seconds()
        if delta < AF_CACHE_TTL_H * 3600:
            wiek_h = int(delta // 3600)
            wiek_m = int((delta % 3600) // 60)
            console.print(
                f"[dim yellow]💾 AF Cache HIT "
                f"[{wiek_h}h {wiek_m}min]: {klucz[:55]}[/dim yellow]"
            )
            return wpis["data"]
    except Exception:
        pass
    return None

def _af_cache_set(klucz: str, dane: dict, stare_dane: dict | None = None):
    """
    Zapisuje dane do disk cache API-Football.
    Jesli stare_dane podane: porownuje czy warto nadpisac
    (nadpisuje tylko jesli dane sie roznia lub sa bogatsze).
    """
    cache = _af_load_disk_cache()

    # Sprawdz czy warto nadpisac
    if stare_dane is not None and klucz in cache:
        # Prosta heurystyka: porownaj liczbe elementow odpowiedzi
        n_nowe = len(dane.get("response", dane)) if isinstance(dane, dict) else len(dane)
        n_star = len(stare_dane.get("response", stare_dane)) if isinstance(stare_dane, dict) else len(stare_dane)
        if n_nowe <= n_star:
            console.print(
                f"[dim]AF Cache: nowe dane ({n_nowe}) nie bogatsze niz stare "
                f"({n_star}) – zatrzymuje stary cache.[/dim]"
            )
            return  # Nie nadpisuj – oszczednosc reqow w przyszlosci

    cache[klucz] = {
        "ts":   datetime.now().isoformat(),
        "data": dane,
    }
    _af_save_disk_cache(cache)
    console.print(f"[dim yellow]💾 AF Cache SAVE: {klucz[:55]}[/dim yellow]")

def af_cache_info() -> dict:
    """Zwraca info o disk cache: liczba wpisow, rozmiar, najstarszy/najnowszy."""
    cache = _af_load_disk_cache()
    if not cache:
        return {"wpisy": 0, "rozmiar_kb": 0, "najstarszy": None, "najnowszy": None}
    tsy = []
    for w in cache.values():
        try:
            tsy.append(datetime.fromisoformat(w["ts"]))
        except Exception:
            pass
    rozm = AF_CACHE_FILE.stat().st_size // 1024 if AF_CACHE_FILE.exists() else 0
    return {
        "wpisy":     len(cache),
        "rozmiar_kb": rozm,
        "najstarszy": min(tsy).strftime("%d.%m %H:%M") if tsy else None,
        "najnowszy":  max(tsy).strftime("%d.%m %H:%M") if tsy else None,
    }

def af_cache_clear():
    """Usuwa caly disk cache API-Football."""
    if AF_CACHE_FILE.exists():
        AF_CACHE_FILE.unlink()
        console.print("[yellow]Disk cache API-Football wyczyszczony.[/yellow]")

# ── Budzet dzienny API-Football ──────────────────────────────────────

def _af_budget_load() -> dict:
    """Laduje stan budzetu z dysku."""
    _af_ensure_dir()
    if AF_BUDGET_FILE.exists():
        try:
            d = json.loads(AF_BUDGET_FILE.read_text(encoding="utf-8"))
            # Reset o polnocy
            dzien = d.get("dzien", "")
            if dzien != datetime.now().strftime("%Y-%m-%d"):
                return {"dzien": datetime.now().strftime("%Y-%m-%d"), "uzyto": 0, "historia": []}
            return d
        except Exception:
            pass
    return {"dzien": datetime.now().strftime("%Y-%m-%d"), "uzyto": 0, "historia": []}

def _af_budget_save(budzet: dict):
    _af_ensure_dir()
    try:
        AF_BUDGET_FILE.write_text(
            json.dumps(budzet, ensure_ascii=False, separators=(',',':')),
            encoding="utf-8"
        )
    except Exception:
        pass

def af_budget_use(endpoint: str = "") -> int:
    """
    Rejestruje uzycie jednego requesta API-Football.
    Zwraca liczbe pozostalych reqow dziennie.
    Rzuca wyjatkiem jesli budzet wyczerpany (< AF_BLOCK_THRESHOLD).
    """
    b = _af_budget_load()
    b["uzyto"] = b.get("uzyto", 0) + 1
    hist = b.get("historia", [])
    hist.append({
        "ts":       datetime.now().strftime("%H:%M:%S"),
        "endpoint": endpoint[:60],
    })
    b["historia"] = hist[-50:]  # max 50 wpisow historii
    _af_budget_save(b)

    pozostalo = AF_BUDGET_DAILY - b["uzyto"]

    if pozostalo < AF_BLOCK_THRESHOLD:
        console.print(
            f"[bold red]⛔ API-Football: krytycznie mało req pozostalo "
            f"({pozostalo}/{AF_BUDGET_DAILY})! "
            f"Blokuje automatyczne zapytania – uzyj cache lub poczekaj do polnocy.[/bold red]"
        )
        raise RuntimeError(f"AF budget exhausted: {pozostalo} remaining")
    elif pozostalo < AF_WARN_THRESHOLD:
        console.print(
            f"[bold yellow]⚠️  API-Football: {pozostalo}/{AF_BUDGET_DAILY} req pozostalo "
            f"na dzis. Oszczedzam – korzystam z cache.[/bold yellow]"
        )
    return pozostalo

def af_budget_status() -> dict:
    """Zwraca aktualny status budzetu."""
    b = _af_budget_load()
    uzyto     = b.get("uzyto", 0)
    pozostalo = max(0, AF_BUDGET_DAILY - uzyto)
    return {
        "dzien":     b.get("dzien", "?"),
        "uzyto":     uzyto,
        "pozostalo": pozostalo,
        "limit":     AF_BUDGET_DAILY,
        "procent":   round(uzyto / AF_BUDGET_DAILY * 100, 1),
        "historia":  b.get("historia", [])[-5:],   # ostatnie 5
        "krytyczny": pozostalo < AF_BLOCK_THRESHOLD,
        "ostrzezenie": pozostalo < AF_WARN_THRESHOLD,
    }
