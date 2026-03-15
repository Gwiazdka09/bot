"""
████████╗ ██████╗  ██████╗ ████████╗███████╗████████╗ █████╗ ████████╗███████╗
██╔════╝██╔═══██╗██╔═══██╗╚══██╔══╝██╔════╝╚══██╔══╝██╔══██╗╚══██╔══╝██╔════╝
█████╗  ██║   ██║██║   ██║   ██║   ███████╗   ██║   ███████║   ██║   ███████╗
██╔══╝  ██║   ██║██║   ██║   ██║   ╚════██║   ██║   ██╔══██║   ██║   ╚════██║
██║     ╚██████╔╝╚██████╔╝   ██║   ███████║   ██║   ██║  ██║   ██║   ███████║
╚═╝      ╚═════╝  ╚═════╝    ╚═╝   ╚══════╝   ╚═╝   ╚═╝  ╚═╝   ╚═╝   ╚══════╝

  FootStats v2.7 MultiSource & Intelligence
  3 darmowe API | Walidacja kluczy | Pewniaczki tygodnia
  Analiza Dom/Wyjazd | Cross-walidacja ML | 1200+ lig

INSTALACJA:
  pip install requests pandas scipy rich reportlab python-dotenv

CZCIONKA PDF (polskie znaki):
  Pobierz DejaVuSans.ttf z https://dejavu-fonts.github.io/
  i umies w tym samym folderze co footstats.py

ZRODLA DANYCH (wszystkie DARMOWE, bez karty kredytowej):
  1. football-data.org  – FOOTBALL_API_KEY    (10 req/min, 12 lig TOP)
  2. api-sports.io      – APISPORTS_KEY        (100 req/dzien, 1200+ lig!)
  3. sports.bzzoiro.com – BZZOIRO_KEY          (bez limitu! ML pred + kursy)
  Rejestracja: https://dashboard.api-football.com  |  https://sports.bzzoiro.com/register/

ZMIANY v2.7 (MultiSource & Intelligence):
  1. SourceManager – 3 API, walidacja kluczy na starcie, status kolorowy
  2. APIFootball – 1200+ lig (Ekstraklasa, MLS, Saudi Pro, Liga MX...)
  3. BzzoiroClient – ML CatBoost predictions + kursy + cross-walidacja Poisson
  4. Opcja 8: Pewniaczki Tygodnia – mecze 7 dni, tylko typy >75% pewnosci
  5. Opcja 9: Analiza Dom/Wyjazd – dom vs wyjazd statystyki osobno,
     flaga 'Podroznik' dla druzyn lepszych na wyjezdzie
  6. Cross-walidacja: Poisson vs ML Bzzoiro, alert gdy duza roznica
"""

import os
import sys
import time
import math
from datetime import datetime, timedelta
from pathlib import Path

import requests
import pandas as pd
import numpy as np
from scipy.stats import poisson

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.prompt import Prompt, Confirm
from rich.text import Text
from rich import box
from rich.columns import Columns
from rich.align import Align

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer,
    Table as RLTable, TableStyle, HRFlowable, PageBreak, KeepTogether
)
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from dotenv import load_dotenv, set_key

console = Console()

# ================================================================
#  STALE
# ================================================================
VERSION         = "v2.7 MultiSource & Intelligence"
MAX_GOLE        = 8
OSTATNIE_N      = 15
BONUS_DOMOWY    = 1.15
SLEEP_KOLEJKA   = 6.0
SLEEP_LOOP      = 6.0
CACHE_TTL_MIN   = 30

ROTACJA_DNI     = 4
ROTACJA_KARA    = 0.80
ZMECZ_GODZ      = 72
ZMECZ_KARA_OBR  = 0.85
ZEMSTA_MIN_GOLE = 3
ZEMSTA_BONUS    = 1.15

H2H_OKNO_DNI       = 730
H2H_MIN_MECZE      = 2
PATENT_BONUS       = 1.10
FORTRESS_MECZE     = 5
FORTRESS_BONUS_OBR = 1.10
IMP2_PROG_FINAL    = 5
IMP2_BONUS_FINAL   = 1.20
IMP2_WAKACJE       = 0.90
CONFIDENCE_H2H_MAX = 5

REWANZ_OKNO_DNI    = 14
REWANZ_VABANK      = 1.30
REWANZ_PARKING_BUS = 0.75
REWANZ_FORT_OBR    = 1.20
FINAL_REMIS_BOOST  = 1.25

_FINAL_STAGES = {"FINAL", "THIRD_PLACE", "GROUP_STAGE", "PRELIMINARY_ROUND"}
_SINGLE_MATCH_COMPS = {"EC", "WC"}

# ── v2.7 NOWE STALE – MultiSource & Intelligence ───────────────────
PEWNIACZEK_PROG    = 75.0  # min. prawdopodobienstwto (%) dla Pewniaczka
PEWNIACZEK_DNI     = 7     # ile dni do przodu szukamy (tydzien)
DOMWYJAZD_MIN_M    = 5     # min. mecze dom/wyjazd do analizy
DOMWYJAZD_PODROZNIK= 0.20  # min. roznica wyjazd-dom w pkt/mecz -> "Podroznik"
BZZOIRO_MAX_ROZN   = 20.0  # max. roznica (%) Poisson vs Bzzoiro ML bez alarmu

# Klucze .env – nazwy zmiennych srodowiskowych
ENV_FOOTBALL   = "FOOTBALL_API_KEY"   # football-data.org
ENV_APISPORTS  = "APISPORTS_KEY"      # api-sports.io (API-Football)
ENV_BZZOIRO    = "BZZOIRO_KEY"        # sports.bzzoiro.com

# ================================================================
#  MODUL 0 - BEZPIECZENSTWO + MULTI-KEY MANAGER (v2.7)
# ================================================================

ENV_FILE       = Path(".env")
GITIGNORE_FILE = Path(".gitignore")

_GITIGNORE = """\
.env
.env.*
FootStats_*.pdf
__pycache__/
*.py[cod]
venv/
.venv/
.vscode/
.idea/
"""

def _stworz_gitignore():
    if not GITIGNORE_FILE.exists():
        GITIGNORE_FILE.write_text(_GITIGNORE, encoding="utf-8")
        console.print("[dim green]Utworzono .gitignore[/dim green]")

def _wczytaj_lub_stworz_env() -> str:
    """Wczytuje klucz football-data.org (obowiazkowy). Pyta o pozostale."""
    _stworz_gitignore()
    load_dotenv(ENV_FILE)

    klucz = os.getenv(ENV_FOOTBALL, "").strip().strip('"').strip("'")
    if not klucz:
        console.print(Panel(
            "[bold yellow]Nie znaleziono klucza football-data.org![/bold yellow]\n\n"
            "FootStats v2.7 obsluguje [bold]3 darmowe zrodla danych[/bold]:\n\n"
            "  [cyan]1. football-data.org[/cyan]    [dim](obowiazkowy) 10 req/min, 12 lig TOP[/dim]\n"
            "     Rejestracja: [bold]https://www.football-data.org/client/register[/bold]\n\n"
            "  [yellow]2. api-sports.io[/yellow]       [dim](opcjonalny) 100 req/dzien, 1200+ lig![/dim]\n"
            "     Rejestracja: [bold]https://dashboard.api-football.com/register[/bold]\n\n"
            "  [green]3. sports.bzzoiro.com[/green]  [dim](opcjonalny) BEZ LIMITU! ML + kursy[/dim]\n"
            "     Rejestracja: [bold]https://sports.bzzoiro.com/register/[/bold]",
            border_style="yellow", title="[bold yellow]FootStats v2.7 – Pierwsze uruchomienie[/bold yellow]",
            padding=(1, 3)
        ))
        klucz = Prompt.ask("[bold cyan]Klucz football-data.org (obowiazkowy)[/bold cyan]").strip()
        if not ENV_FILE.exists():
            ENV_FILE.write_text("", encoding="utf-8")
        set_key(str(ENV_FILE), ENV_FOOTBALL, klucz)

        # Opcjonalny API-Football
        if Confirm.ask("[yellow]Dodac klucz api-sports.io? (1200+ lig, Ekstraklasa!)[/yellow]",
                       default=False):
            k2 = Prompt.ask("[bold yellow]Klucz api-sports.io[/bold yellow]").strip()
            if k2:
                set_key(str(ENV_FILE), ENV_APISPORTS, k2)

        # Opcjonalny Bzzoiro
        if Confirm.ask("[green]Dodac klucz Bzzoiro? (ML predictions, kursy, BEZ LIMITU)[/green]",
                       default=False):
            k3 = Prompt.ask("[bold green]Klucz sports.bzzoiro.com[/bold green]").strip()
            if k3:
                set_key(str(ENV_FILE), ENV_BZZOIRO, k3)

        load_dotenv(ENV_FILE, override=True)
        klucz = os.getenv(ENV_FOOTBALL, "").strip().strip('"').strip("'")
        console.print(f"[green]Klucze zapisane: {ENV_FILE.resolve()}[/green]\n")

    return klucz

def _czytaj_wszystkie_klucze() -> dict:
    """Czyta wszystkie klucze z .env. Zwraca dict {ENV_*: klucz|None}."""
    load_dotenv(ENV_FILE, override=True)
    return {
        ENV_FOOTBALL:  (os.getenv(ENV_FOOTBALL,  "") or "").strip().strip('"').strip("'") or None,
        ENV_APISPORTS: (os.getenv(ENV_APISPORTS, "") or "").strip().strip('"').strip("'") or None,
        ENV_BZZOIRO:   (os.getenv(ENV_BZZOIRO,   "") or "").strip().strip('"').strip("'") or None,
    }

# ================================================================
#  MODUL 1 - CZCIONKA PDF
# ================================================================

_FONT_PATHS = [
    Path(__file__).parent / "DejaVuSans.ttf",
    Path(r"C:\Windows\Fonts\DejaVuSans.ttf"),
    Path(r"C:\Windows\Fonts\dejavusans.ttf"),
    Path.home() / "DejaVuSans.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
]
PDF_FONT      = "Helvetica"
PDF_FONT_BOLD = "Helvetica-Bold"
FONT_OK       = False

def _zarejestruj_font():
    global PDF_FONT, PDF_FONT_BOLD, FONT_OK
    for p in _FONT_PATHS:
        if p.is_file():
            try:
                pdfmetrics.registerFont(TTFont("DejaVu", str(p)))
                PDF_FONT = PDF_FONT_BOLD = "DejaVu"
                FONT_OK = True
                return True
            except Exception:
                pass
    return False

def _pdf(tekst: str) -> str:
    if FONT_OK:
        return str(tekst)
    return str(tekst).translate(str.maketrans(
        "acelnoszz ACELNOSZZ",
        "acelnoszz ACELNOSZZ"
    )).translate(str.maketrans(
        "\u0105\u0107\u0119\u0142\u0144\u00f3\u015b\u017a\u017c\u0104\u0106\u0118\u0141\u0143\u00d3\u015a\u0179\u017b",
        "acelnoszzACELNOSZZ"
    ))

# ================================================================
#  MODUL 2 - HELPERY
# ================================================================

def _s(v, domyslna: str = "-") -> str:
    if v is None:
        return domyslna
    try:
        if isinstance(v, float) and math.isnan(v):
            return domyslna
    except TypeError:
        pass
    s = str(v).strip()
    return domyslna if s.lower() in ("nan", "none", "null", "") else s

def _parse_date(data_str) -> datetime | None:
    if not data_str or str(data_str) in ("-", "nan", "none"):
        return None
    s = str(data_str).strip()
    # UWAGA: nie uzywaj len(fmt) jako dlugosci stringa daty –
    # format string ma inną długość niż reprezentowany przez niego ciąg.
    # Np. "%Y-%m-%d" ma 8 znaków, ale data "2024-03-15" ma 10.
    _FORMATY = [
        ("%Y-%m-%dT%H:%M:%SZ", 20),   # "2024-03-15T20:30:00Z"
        ("%Y-%m-%dT%H:%M:%S",  19),   # "2024-03-15T20:30:00"
        ("%Y-%m-%d",           10),   # "2024-03-15"
    ]
    for fmt, dl in _FORMATY:
        try:
            return datetime.strptime(s[:dl], fmt)
        except ValueError:
            continue
    return None

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

import json

_RAM_CACHE: dict = {}   # football-data.org + bzzoiro (in-memory)

CACHE_DIR     = Path(".cache")
AF_CACHE_FILE = CACHE_DIR / "af_cache.json"      # dane API-Football
AF_BUDGET_FILE= CACHE_DIR / "af_budget.json"      # licznik dzienny

CACHE_TTL_MIN    = 30    # RAM cache TTL (FDB / Bzzoiro)
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

# ── HTTP GET (football-data.org) ─────────────────────────────────────

def _http_get(endpoint: str, params: dict = None, headers: dict = None) -> dict | None:
    url = f"https://api.football-data.org/v4{endpoint}"
    _rate_guard()
    try:
        r = requests.get(url, headers=headers, params=params, timeout=15)
        if r.status_code == 200:
            return r.json()
        elif r.status_code == 429:
            console.print(Panel(
                "[bold red]Limit API wyczerpany (429 Too Many Requests)![/bold red]\n\n"
                "Plan FREE: [bold]10 zapytan na minute[/bold].\n"
                "FootStats wznowi pobieranie za [bold]62 sekundy[/bold]...",
                border_style="red", title="Rate Limit Exceeded", padding=(1, 2)
            ))
            time.sleep(62)
            return _http_get(endpoint, params, headers)
        elif r.status_code == 403:
            console.print("[red]403 Forbidden - nieprawidlowy klucz API lub plan.[/red]")
            return None
        elif r.status_code == 404:
            console.print(f"[yellow]404 Not Found: {endpoint}[/yellow]")
            return None
        else:
            console.print(f"[red]HTTP {r.status_code}: {endpoint}[/red]")
            return None
    except requests.ConnectionError:
        console.print("[red]Brak polaczenia z internetem.[/red]")
        return None
    except requests.Timeout:
        console.print("[red]Timeout - serwer nie odpowiada.[/red]")
        return None

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


# ================================================================
#  MODUL 4b – API-FOOTBALL (api-sports.io) v2.7
#  Darmowy plan: 100 req/dzien, 1200+ lig (Ekstraklasa, MLS, Saudi...)
# ================================================================

# Mapowanie nazw lig API-Football na wewnetrzne kody i id
_APISPORTS_LIGI = {
    # id : {kod_wewn, nazwa, kraj, druzyny}
    39:  {"kod": "PL",  "nazwa": "Premier League",        "kraj": "England",     "druzyny": 20},
    140: {"kod": "PD",  "nazwa": "Primera Division",       "kraj": "Spain",       "druzyny": 20},
    135: {"kod": "SA",  "nazwa": "Serie A",                "kraj": "Italy",       "druzyny": 20},
    78:  {"kod": "BL1", "nazwa": "Bundesliga",             "kraj": "Germany",     "druzyny": 18},
    61:  {"kod": "FL1", "nazwa": "Ligue 1",                "kraj": "France",      "druzyny": 18},
    94:  {"kod": "PPL", "nazwa": "Primeira Liga",          "kraj": "Portugal",    "druzyny": 18},
    88:  {"kod": "DED", "nazwa": "Eredivisie",             "kraj": "Netherlands", "druzyny": 18},
    40:  {"kod": "ELC", "nazwa": "Championship",           "kraj": "England",     "druzyny": 24},
    2:   {"kod": "CL",  "nazwa": "UEFA Champions League",  "kraj": "Europe",      "druzyny": 36},
    71:  {"kod": "BSA", "nazwa": "Brasileirao Serie A",    "kraj": "Brazil",      "druzyny": 20},
    106: {"kod": "EKS", "nazwa": "PKO BP Ekstraklasa",     "kraj": "Poland",      "druzyny": 18},
    253: {"kod": "MLS", "nazwa": "MLS",                    "kraj": "USA",         "druzyny": 29},
    307: {"kod": "SPL", "nazwa": "Saudi Pro League",       "kraj": "Saudi Arabia","druzyny": 18},
    262: {"kod": "LMX", "nazwa": "Liga MX",                "kraj": "Mexico",      "druzyny": 18},
    144: {"kod": "PRO", "nazwa": "Pro League",             "kraj": "Belgium",     "druzyny": 18},
    179: {"kod": "SPO", "nazwa": "Scottish Premiership",   "kraj": "Scotland",    "druzyny": 12},
}

class APIFootball:
    """
    Klient api-sports.io (API-Football).
    Darmowy: 100 req/dzien, wszystkie endpointy, 1200+ lig.
    Header: x-apisports-key: KEY
    """
    BASE = "https://v3.football.api-sports.io"

    def __init__(self, api_key: str):
        self.headers = {"x-apisports-key": api_key}
        self._valid: bool | None = None
        self._req_today: int = 0

    def waliduj(self) -> tuple[bool, str]:
        """
        Sprawdza klucz przez /status endpoint (1 req).
        Pobiera tez aktualny licznik reqow z serwera (nadrzedny vs nasz lokalny).
        """
        try:
            r = requests.get(f"{self.BASE}/status",
                             headers=self.headers, timeout=10)
            if r.status_code == 200:
                d    = r.json().get("response", {})
                used = d.get("requests", {}).get("current", 0)
                lim  = d.get("requests", {}).get("limit_day", 100)
                self._req_today = used
                self._valid = True

                # Zsynchronizuj lokalny licznik z serwerowym (serwer jest prawda)
                bud = _af_budget_load()
                if used > bud.get("uzyto", 0):
                    bud["uzyto"] = used
                    _af_budget_save(bud)

                pozostalo = lim - used
                kol = "green" if pozostalo > AF_WARN_THRESHOLD else (
                      "yellow" if pozostalo > AF_BLOCK_THRESHOLD else "red")
                return True, (f"[{kol}]OK – {used}/{lim} req/dzien | "
                              f"pozostalo: {pozostalo}[/{kol}]")

            elif r.status_code == 401:
                self._valid = False
                return False, "Nieprawidlowy klucz API-Football (401)"
            else:
                self._valid = False
                return False, f"HTTP {r.status_code}"
        except Exception as e:
            self._valid = False
            return False, str(e)

    def info_cache_i_budzet(self) -> str:
        """Krotki opis cache i budzetu do wyswietlenia w menu."""
        bud  = af_budget_status()
        info = af_cache_info()
        kol  = "green" if not bud["ostrzezenie"] else ("yellow" if not bud["krytyczny"] else "red")
        return (
            f"[{kol}]{bud['pozostalo']}/{bud['limit']} req pozostalo[/{kol}] | "
            f"Cache: {info['wpisy']} wpisow ({info['rozmiar_kb']}KB)"
        )

    def _get(self, endpoint: str, params: dict = None,
             force_network: bool = False) -> dict | None:
        """
        Pobiera dane z API-Football z pelna strategia oszczedzania:
          1. Sprawdz disk cache (TTL 24h) – bez zadnego requesta
          2. Jesli cache wazny: uzyj bez pytania sieci
          3. Jesli cache wygasl / brak:
             a. Sprawdz budzet (< AF_BLOCK_THRESHOLD = blokada)
             b. Wyslij request, zrejestruj w budzecie
             c. Zapisz na dysk (porownaj z starym przed nadpisaniem)
        force_network=True: pomija cache i pobiera swiezo (uzywa requesta).
        """
        cache_key = f"af:{endpoint}:{params}"

        # 1. Disk cache – zawsze proba
        if not force_network:
            cached = _af_cache_get(cache_key)
            if cached is not None:
                return cached

        # 2. Sprawdz budzet zanim wykonamy request
        bud = af_budget_status()
        if bud["krytyczny"]:
            # Krytyczny budzet: zwroc co mamy (nawet wygasle), albo None
            stare = _af_load_disk_cache().get(cache_key, {}).get("data")
            if stare:
                console.print(
                    "[yellow]⚠️  Krytyczny budzet AF – uzywam wygaslych danych z cache.[/yellow]"
                )
                return stare
            console.print("[bold red]⛔ Brak cache i budzet krytyczny – pominięto.[/bold red]")
            return None

        # 3. Wyslij request
        try:
            pozostalo = af_budget_use(endpoint)
        except RuntimeError:
            # Budzet zablokowany – sprobuj wygasle dane
            stare = _af_load_disk_cache().get(cache_key, {}).get("data")
            return stare

        try:
            r = requests.get(
                f"{self.BASE}{endpoint}",
                headers=self.headers, params=params, timeout=15
            )
            self._req_today += 1

            if r.status_code == 200:
                data = r.json()
                # Sprawdz stare dane przed zapisem
                stare = _af_load_disk_cache().get(cache_key, {}).get("data")
                _af_cache_set(cache_key, data, stare)
                console.print(
                    f"[dim]AF req uzyto: {bud['uzyto']+1}/{AF_BUDGET_DAILY} "
                    f"| pozostalo ~{pozostalo-1}[/dim]"
                )
                return data

            elif r.status_code == 429:
                console.print(
                    "[bold red]API-Football HTTP 429 – limit dzienny wyczerpany na serwerze![/bold red]\n"
                    "[dim]Dane beda dostepne jutro. Uzywam cache jesli dostepny.[/dim]"
                )
                stare = _af_load_disk_cache().get(cache_key, {}).get("data")
                return stare

            elif r.status_code in (401, 403):
                self._valid = False
                console.print(f"[red]API-Football: blad autoryzacji ({r.status_code})[/red]")
                return None

            return None

        except requests.exceptions.Timeout:
            console.print("[yellow]API-Football: timeout – uzywam cache.[/yellow]")
            stare = _af_load_disk_cache().get(cache_key, {}).get("data")
            return stare
        except Exception as e:
            console.print(f"[yellow]API-Football blad sieci: {e}[/yellow]")
            return None

    def ligi_dodatkowe(self) -> list:
        """Zwraca liste lig dostepnych przez API-Football (z predefiniowanej mapy)."""
        wynik = []
        for api_id, info in _APISPORTS_LIGI.items():
            wynik.append({
                "nazwa":   info["nazwa"],
                "kod":     info["kod"],
                "kraj":    info["kraj"],
                "druzyny": info["druzyny"],
                "api_id":  api_id,
                "zrodlo":  "api-sports.io",
            })
        return sorted(wynik, key=lambda x: x["nazwa"])

    def wyniki_liga(self, api_id: int, sezon: int = None) -> pd.DataFrame | None:
        """Pobiera wyniki dla ligi po api_id."""
        if sezon is None:
            sezon = datetime.now().year if datetime.now().month > 6 else datetime.now().year - 1
        dane = self._get("/fixtures", params={
            "league": api_id, "season": sezon, "status": "FT", "last": 100
        })
        if not dane:
            return None
        mecze = []
        for m in dane.get("response", []):
            goals = m.get("goals", {})
            gg, ga = goals.get("home"), goals.get("away")
            if gg is None or ga is None:
                continue
            teams = m.get("teams", {})
            gosp = _s(teams.get("home", {}).get("name"))
            gosc = _s(teams.get("away", {}).get("name"))
            date_str = m.get("fixture", {}).get("date", "")[:10]
            mecze.append({
                "data":        date_str,
                "data_full":   m.get("fixture", {}).get("date", date_str),
                "gospodarz":   gosp,
                "goscie":      gosc,
                "gole_g":      int(gg),
                "gole_a":      int(ga),
                "kolejka":     m.get("league", {}).get("round"),
                "stage":       "REGULAR_SEASON",
                "competition": _APISPORTS_LIGI.get(api_id, {}).get("kod", str(api_id)),
            })
        return pd.DataFrame(mecze) if mecze else None

    def nadchodzace_liga(self, api_id: int, sezon: int = None) -> pd.DataFrame | None:
        """Pobiera nadchodzace mecze dla ligi."""
        if sezon is None:
            sezon = datetime.now().year if datetime.now().month > 6 else datetime.now().year - 1
        dane = self._get("/fixtures", params={
            "league": api_id, "season": sezon, "status": "NS", "next": 40
        })
        if not dane:
            return None
        mecze = []
        for m in dane.get("response", []):
            teams   = m.get("teams", {})
            gosp    = _s(teams.get("home", {}).get("name"))
            gosc    = _s(teams.get("away", {}).get("name"))
            date_str= m.get("fixture", {}).get("date", "")[:10]
            mecze.append({
                "data":        date_str,
                "data_full":   m.get("fixture", {}).get("date", date_str),
                "godzina":     m.get("fixture", {}).get("date", "")[:16] + " UTC",
                "gospodarz":   gosp,
                "goscie":      gosc,
                "kolejka":     m.get("league", {}).get("round"),
                "stage":       "REGULAR_SEASON",
                "first_leg_g": None,
                "first_leg_a": None,
            })
        return pd.DataFrame(mecze) if mecze else None

    def tabela_liga(self, api_id: int, sezon: int = None) -> pd.DataFrame | None:
        """Pobiera tabele dla ligi."""
        if sezon is None:
            sezon = datetime.now().year if datetime.now().month > 6 else datetime.now().year - 1
        dane = self._get("/standings", params={"league": api_id, "season": sezon})
        if not dane:
            return None
        try:
            tabela = dane["response"][0]["league"]["standings"][0]
        except (IndexError, KeyError):
            return None
        wiersze = []
        for w in tabela:
            wiersze.append({
                "Poz.":    w["rank"],
                "Druzyna": _s(w["team"].get("name")),
                "M":       w["all"]["played"],
                "W":       w["all"]["win"],
                "R":       w["all"]["draw"],
                "P":       w["all"]["lose"],
                "BZ":      w["all"]["goals"]["for"],
                "BS":      w["all"]["goals"]["against"],
                "Bramki":  f"{w['all']['goals']['for']}:{w['all']['goals']['against']}",
                "+/-":     w["goalsDiff"],
                "Pkt":     w["points"],
            })
        return pd.DataFrame(wiersze) if wiersze else None


# ================================================================
#  MODUL 4c – BZZOIRO (sports.bzzoiro.com) v2.7
#  DARMOWY bez limitu: ML predictions CatBoost + kursy bukmacherskie
# ================================================================

class BzzoiroClient:
    """
    Klient sports.bzzoiro.com.
    BEZ LIMITU zapytan. ML CatBoost predictions + odsy bukmacherskie.
    Uzywa do cross-walidacji i wzbogacenia predykcji FootStats.
    Header: Authorization: Token KEY
    """
    BASE = "https://sports.bzzoiro.com/api"

    # Mapowanie kodow lig Bzzoiro do ID
    _LIGA_IDS = {
        "PL":  1,  "PPL": 2,   "PD":  3,   "SA":  4,   "BL1": 5,
        "FL1": 6,  "CL":  7,   "ELC": 12,  "DED": 10,  "BSA": 9,
        "EKS": None,  # nie ma Ekstraklasy w Bzzoiro
    }

    def __init__(self, api_key: str):
        self.headers = {"Authorization": f"Token {api_key}"}
        self._valid: bool | None = None

    def waliduj(self) -> tuple[bool, str]:
        """Sprawdza poprawnosc klucza."""
        try:
            r = requests.get(f"{self.BASE}/leagues/",
                             headers=self.headers, timeout=10)
            if r.status_code == 200:
                self._valid = True
                n = len(r.json().get("results", []))
                return True, f"OK – {n} lig dostepnych"
            elif r.status_code == 401:
                self._valid = False
                return False, "Nieprawidlowy klucz Bzzoiro (401)"
            else:
                self._valid = False
                return False, f"HTTP {r.status_code}"
        except Exception as e:
            self._valid = False
            return False, str(e)

    def _get(self, path: str, params: dict = None) -> dict | None:
        cache_key = f"bz:{path}:{params}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
        try:
            r = requests.get(f"{self.BASE}{path}",
                             headers=self.headers, params=params, timeout=15)
            if r.status_code == 200:
                data = r.json()
                _cache_set(cache_key, data)
                return data
        except Exception:
            pass
        return None

    def nadchodzace_tygodnia(self, liga_kod: str = None) -> list:
        """
        Pobiera nadchodzace mecze z nastepnych 7 dni.
        Opcjonalnie filtruje po lidze (kod wewnetrzny).
        Zwraca liste eventow z predykcjami ML.
        """
        data_od  = datetime.now().strftime("%Y-%m-%d")
        data_do  = (datetime.now() + timedelta(days=PEWNIACZEK_DNI)).strftime("%Y-%m-%d")
        params   = {"date_from": data_od, "date_to": data_do, "upcoming": "true"}

        liga_id = None
        if liga_kod:
            liga_id = self._LIGA_IDS.get(liga_kod)
        if liga_id:
            params["league"] = liga_id

        dane = self._get("/events/", params=params)
        return dane.get("results", []) if dane else []

    def predykcja_meczu(self, event_id: int) -> dict | None:
        """Pobiera predykcje ML dla konkretnego meczu."""
        dane = self._get(f"/predictions/", params={"event": event_id})
        if not dane:
            return None
        wyniki = dane.get("results", [])
        return wyniki[0] if wyniki else None

    def predykcje_tygodnia(self, liga_kod: str = None) -> list:
        """
        Pobiera predykcje na caly tydzien.
        Zwraca liste slownikow z kompletna analiza.
        """
        wydarzenia = self.nadchodzace_tygodnia(liga_kod)
        wynik = []
        for ev in wydarzenia:
            pred_ml = None
            if ev.get("predictions"):
                # predictions sa juz w evencie
                pred_ml = ev["predictions"]
            wynik.append({
                "id":         ev.get("id"),
                "gosp":       ev.get("home_team"),
                "gosc":       ev.get("away_team"),
                "liga":       ev.get("league", {}).get("name", "?") if isinstance(ev.get("league"), dict) else str(ev.get("league", "?")),
                "data":       str(ev.get("event_date", ""))[:10],
                "godzina":    str(ev.get("event_date", ""))[11:16],
                "status":     ev.get("status", "notstarted"),
                "pred_ml":    pred_ml,  # moze byc None jesli brak
                "odds":       ev.get("odds"),
            })
        return wynik

    @staticmethod
    def porownaj_z_poisson(pw_pois: float, px_pois: float, pp_pois: float,
                            pred_ml: dict | None) -> dict:
        """
        Porownuje predykcje Poissona z ML Bzzoiro.
        Zwraca slownik z informacja o zgodnosci.
        """
        if not pred_ml:
            return {"zgodnosc": None, "opis": "Bzzoiro: brak danych ML"}

        try:
            wyp_ml = _bzz_parse_prob(pred_ml)
            if wyp_ml is None:
                return {"zgodnosc": None, "opis": "Bzzoiro: nieznany format danych ML"}
            ml_1, ml_x, ml_2 = wyp_ml[0], wyp_ml[1], wyp_ml[2]

            # Faworyt wg obu modeli
            faw_pois = "1" if pw_pois > max(px_pois, pp_pois) else (
                        "X" if px_pois > pp_pois else "2")
            faw_ml   = "1" if ml_1 > max(ml_x, ml_2) else (
                        "X" if ml_x > ml_2 else "2")

            zgodnosc = (faw_pois == faw_ml)

            # Roznica procentowa na faworycie
            if faw_pois == "1": r = abs(pw_pois - ml_1)
            elif faw_pois == "X": r = abs(px_pois - ml_x)
            else: r = abs(pp_pois - ml_2)

            alert = r > BZZOIRO_MAX_ROZN

            return {
                "zgodnosc":    zgodnosc,
                "alert":       alert,
                "ml_1":        round(ml_1,1),
                "ml_x":        round(ml_x,1),
                "ml_2":        round(ml_2,1),
                "roznica_max": round(r, 1),
                "faw_pois":    faw_pois,
                "faw_ml":      faw_ml,
                "opis": (
                    f"Poisson: 1={pw_pois:.0f}% X={px_pois:.0f}% 2={pp_pois:.0f}% | "
                    f"ML Bzzoiro: 1={ml_1:.0f}% X={ml_x:.0f}% 2={ml_2:.0f}%"
                    + (f" [ALERT: roznica {r:.0f}%!]" if alert else "")
                ),
            }
        except Exception:
            return {"zgodnosc": None, "opis": "Bzzoiro: blad parsowania ML"}


# ================================================================
#  MODUL 4d – SOURCE MANAGER + WALIDACJA KLUCZY (v2.7)
# ================================================================

class SourceManager:
    """
    Zarzadza dostepnoscia 3 zrodel danych.
    Waliduje klucze na starcie i wyswietla status w konsoli.
    Udostepnia unified interface dla pozostalych modulow.
    """

    def __init__(self, klucze: dict):
        self.fdb    = APIClient(klucze[ENV_FOOTBALL]) if klucze.get(ENV_FOOTBALL)  else None
        self.af     = APIFootball(klucze[ENV_APISPORTS]) if klucze.get(ENV_APISPORTS) else None
        self.bzz    = BzzoiroClient(klucze[ENV_BZZOIRO])   if klucze.get(ENV_BZZOIRO)   else None
        self._status: dict = {}

    def waliduj_i_wyswietl(self):
        """Waliduje wszystkie dostepne zrodla i wyswietla tabele statusu."""
        t = Table(
            title=f"[bold blue]Zrodla Danych – FootStats {VERSION}[/bold blue]",
            box=box.ROUNDED, border_style="blue", show_lines=True
        )
        t.add_column("Zrodlo",    style="bold white", width=24)
        t.add_column("Status",    style="bold",       width=16)
        t.add_column("Ligi",      style="cyan",       width=8)
        t.add_column("Cache",     style="dim yellow", width=18)
        t.add_column("Info",      style="dim",        width=32)

        # football-data.org
        if self.fdb:
            ok, msg = self._test_fdb()
            st = "[bold green]✓ AKTYWNY[/bold green]" if ok else "[bold red]✗ BLAD[/bold red]"
            t.add_row("football-data.org", st, "12 TOP",
                      f"RAM {CACHE_TTL_MIN}min", msg)
            self._status["fdb"] = ok
        else:
            t.add_row("football-data.org", "[red]✗ BRAK[/red]", "–",
                      "–", "Brak klucza FOOTBALL_API_KEY w .env")
            self._status["fdb"] = False

        # api-sports.io
        if self.af:
            ok, msg = self.af.waliduj()
            st = "[bold green]✓ AKTYWNY[/bold green]" if ok else "[bold red]✗ BLAD[/bold red]"
            ci = af_cache_info()
            cache_str = f"Dysk 24h | {ci['wpisy']} wpisow"
            t.add_row("api-sports.io", st, "1200+", cache_str, msg)
            self._status["af"] = ok
        else:
            bud = af_budget_status()   # pokaz status nawet bez klucza
            ci  = af_cache_info()
            cache_str = f"Dysk 24h | {ci['wpisy']} wpisow"
            st_bud = ""
            if ci["wpisy"] > 0:
                st_bud = f" | Cache z: {ci['najnowszy']}"
            t.add_row("api-sports.io", "[yellow]⚬ OPCJONALNE[/yellow]", "1200+",
                      cache_str,
                      f"Brak klucza APISPORTS_KEY{st_bud}")
            self._status["af"] = False

        # sports.bzzoiro.com
        if self.bzz:
            ok, msg = self.bzz.waliduj()
            st = "[bold green]✓ AKTYWNY[/bold green]" if ok else "[bold red]✗ BLAD[/bold red]"
            t.add_row("sports.bzzoiro.com", st, "22+ML",
                      f"RAM {CACHE_TTL_MIN}min", msg)
            self._status["bzz"] = ok
        else:
            t.add_row("sports.bzzoiro.com", "[yellow]⚬ OPCJONALNE[/yellow]", "22+ML",
                      f"RAM {CACHE_TTL_MIN}min", "Brak klucza BZZOIRO_KEY | ML + kursy")
            self._status["bzz"] = False

        console.print(t)

        # Budżet API-Football – osobny panel jesli klucz aktywny
        if self._status.get("af"):
            bud = af_budget_status()
            kol = "green" if not bud["ostrzezenie"] else ("yellow" if not bud["krytyczny"] else "red")
            pasek_uzyte  = "█" * int(bud["procent"] / 5)
            pasek_wolne  = "░" * (20 - int(bud["procent"] / 5))
            console.print(
                f"  [dim]API-Football budzet [{datetime.now().strftime('%d.%m')}]:[/dim] "
                f"[{kol}]{pasek_uzyte}[/{kol}][dim]{pasek_wolne}[/dim] "
                f"[{kol}]{bud['uzyto']}/{bud['limit']} req[/{kol}] "
                f"| pozostalo: [{kol}]{bud['pozostalo']}[/{kol}]"
            )

        if not self._status.get("fdb"):
            console.print("[bold red]BLAD: football-data.org jest obowiazkowy![/bold red]")
        console.print()

    def _test_fdb(self) -> tuple[bool, str]:
        """Testuje polaczenie z football-data.org."""
        try:
            r = requests.get(
                "https://api.football-data.org/v4/competitions",
                headers={"X-Auth-Token": self.fdb.headers["X-Auth-Token"]},
                timeout=10
            )
            if r.status_code == 200:
                n = len(r.json().get("competitions", []))
                return True, f"{n} rozgrywek dostepnych"
            elif r.status_code == 403:
                return False, "Nieprawidlowy klucz (403)"
            else:
                return False, f"HTTP {r.status_code}"
        except Exception as e:
            return False, str(e)[:40]

    def dodaj_klucz_interaktywnie(self, env_name: str):
        """Pyta uzytkownika o brakujacy klucz i zapisuje do .env."""
        opisy = {
            ENV_APISPORTS: ("api-sports.io", "https://dashboard.api-football.com/register"),
            ENV_BZZOIRO:   ("sports.bzzoiro.com", "https://sports.bzzoiro.com/register/"),
        }
        nazwa, url = opisy.get(env_name, (env_name, ""))
        console.print(f"\n[yellow]Rejestracja {nazwa}: [bold]{url}[/bold][/yellow]")
        k = Prompt.ask(f"[bold cyan]Klucz {nazwa}[/bold cyan]").strip()
        if k:
            set_key(str(ENV_FILE), env_name, k)
            load_dotenv(ENV_FILE, override=True)
            return k
        return None

    @property
    def bzzoiro_ok(self) -> bool:
        return self._status.get("bzz", False)

    @property
    def apisports_ok(self) -> bool:
        return self._status.get("af", False)

class ImportanceIndex:
    """
    Importance Index 2.0 – dwustopniowa motywacja konca sezonu:

    TRYB NORMALNY (pozostalo > IMP2_PROG_FINAL kolejek):
      * High Stakes Top (poz. 1-4, < 10 kolejek): atak +20%
      * Baraze/Spadek (ostanie 5, < 10 kolejek):  atak +10-20%
      * Comfort (srodek tabeli, duzo kolejek):     atak -10%

    TRYB FINALNY (pozostalo <= IMP2_PROG_FINAL = 5 kolejek):
      * Miejsca 1-3:             atak +20% (walka o tytul / CL)
      * Ostatnie 3 miejsca:      atak +20% (desperacja, utrzymanie)
      * Reszta ('bezpieczni'):   atak -10% (efekt wakacji)
    """

    def __init__(self, df_tabela: pd.DataFrame, n_druzyn: int = 20):
        self.df = df_tabela
        self.n  = n_druzyn if n_druzyn else (len(df_tabela) if df_tabela is not None else 20)

    def _pozostale(self, rozegrane: int) -> int:
        sezon_dl = 34 if self.n <= 18 else 38
        return max(0, sezon_dl - rozegrane)

    def analiza(self, druzyna: str) -> dict:
        if self.df is None or self.df.empty:
            return self._normal()
        wiersz = self.df[self.df["Druzyna"] == druzyna]
        if wiersz.empty:
            return self._normal()
        poz       = int(wiersz["Poz."].iloc[0])
        rozegr    = int(wiersz["M"].iloc[0])
        pozostalo = self._pozostale(rozegr)

        # ── TRYB FINALNY: <= 5 kolejek do konca ─────────────────────
        if pozostalo <= IMP2_PROG_FINAL:
            # Miejsca 1-3: walka o tytul / UEFA
            if poz <= 3:
                ikona = "👑" if poz == 1 else "🏆"
                return {
                    "status":      "FINAL_TOP",
                    "label":       f"[bold gold1]{ikona} FINAL-TOP{poz}[/bold gold1]",
                    "label_plain": f"FINAL-TOP{poz}",
                    "bonus_atak":  IMP2_BONUS_FINAL,
                    "komentarz":   (
                        f"TRYB FINALNY: {druzyna} na {poz}. miejscu, "
                        f"zostalo {pozostalo} kolejek – atak +20% (walka o tytul/CL)."
                    ),
                }
            # Ostatnie 3 miejsca: bezposredni spadek
            if poz >= self.n - 2:
                return {
                    "status":      "FINAL_RELEGATION",
                    "label":       "[bold red]🆘 FINAL-SPADEK[/bold red]",
                    "label_plain": "FINAL-SPADEK",
                    "bonus_atak":  IMP2_BONUS_FINAL,
                    "komentarz":   (
                        f"TRYB FINALNY: {druzyna} zagrozony spadkiem (poz. {poz}/{self.n}), "
                        f"{pozostalo} kolejek – desperacja, atak +20%."
                    ),
                }
            # Reszta: efekt wakacji
            return {
                "status":      "VACATION",
                "label":       "[dim]🏖️  Wakacje-MID[/dim]",
                "label_plain": "Wakacje-MID",
                "bonus_atak":  IMP2_WAKACJE,
                "komentarz":   (
                    f"TRYB FINALNY: {druzyna} bezpieczna pozycja (poz. {poz}), "
                    f"{pozostalo} kolejek – efekt wakacji, wydajnosc -10%."
                ),
            }

        # ── TRYB NORMALNY: wiecej niz 5 kolejek ─────────────────────
        # Wysokie stawki: Top 4 (< 10 kolejek)
        if poz <= 4 and pozostalo < 10:
            ikona = "👑" if poz == 1 else "🏆"
            return {
                "status":      "HIGH_STAKES_TOP",
                "label":       f"[bold green]{ikona} Wysoka-TOP{poz}[/bold green]",
                "label_plain": f"Wysoka-TOP{poz}",
                "bonus_atak":  1.20,
                "komentarz":   f"{druzyna} walczy o Top {poz} (poz. {poz}/{self.n}), ~{pozostalo} kolejek – atak +20%.",
            }
        # Strefa spadkowa (< 10 kolejek)
        if poz >= self.n - 2 and pozostalo < 10:
            return {
                "status":      "HIGH_STAKES_BOTTOM",
                "label":       "[bold red]🆘 Wysoka-SPADEK[/bold red]",
                "label_plain": "Wysoka-SPADEK",
                "bonus_atak":  1.20,
                "komentarz":   f"{druzyna} zagrozony spadkiem (poz. {poz}/{self.n}), {pozostalo} kolejek – atak +20%.",
            }
        # Baraze (< 10 kolejek)
        if poz >= self.n - 5 and pozostalo < 10:
            return {
                "status":      "HIGH_STAKES_BOTTOM",
                "label":       "[bold orange_red1]⚠️  Wysoka-BARAZE[/bold orange_red1]",
                "label_plain": "Wysoka-BARAZE",
                "bonus_atak":  1.10,
                "komentarz":   f"{druzyna} strefa barazy (poz. {poz}), ~{pozostalo} kolejek – ofensywa +10%.",
            }
        # Komfort (duzo kolejek, srodek tabeli)
        mid_lo, mid_hi = 5, max(6, self.n - 6)
        if mid_lo <= poz <= mid_hi and pozostalo >= 10:
            return {
                "status":      "COMFORT",
                "label":       "[dim]😐 Neutralna-MID[/dim]",
                "label_plain": "Neutralna-MID",
                "bonus_atak":  0.90,
                "komentarz":   f"{druzyna} srodek tabeli (poz. {poz}), {pozostalo} kolejek – motywacja -10%.",
            }
        return self._normal(poz)

    def _normal(self, poz: int = 0) -> dict:
        return {
            "status":      "NORMAL",
            "label":       "[cyan]🔵 Normalna[/cyan]",
            "label_plain": "Normalna",
            "bonus_atak":  1.0,
            "komentarz":   f"Druzyna (poz. {poz}) – brak specjalnych czynnikow.",
        }


# ================================================================
#  MODUL 6 - HEURYSTYKA ZMECZENIA I ROTACJI (NOWE v2.4)
# ================================================================

class HeurystaZmeczeniaRotacji:
    """
    Wykrywa dwa czynniki obnizajace jakosc gry:

    🔄 ROTACJA: mecz CL w ciagu ROTACJA_DNI dni -> trener rotuje sklad
       Efekt: lambda ataku * ROTACJA_KARA = -20%

    😫 ZMECZENIE: poprzedni mecz < ZMECZ_GODZ godzin temu
       Efekt: lambda obrony * ZMECZ_KARA_OBR = -15%
       (co matematycznie zwieksza expected goals przeciwnika)
    """

    def __init__(self, df_mecze: pd.DataFrame):
        self.df = df_mecze.copy() if df_mecze is not None else pd.DataFrame()
        if not self.df.empty and "data_full" in self.df.columns:
            self.df["_dt"] = self.df["data_full"].apply(_parse_date)

    def _mecze_druzyny(self, druzyna: str) -> pd.DataFrame:
        if self.df.empty:
            return pd.DataFrame()
        maska = (self.df["gospodarz"] == druzyna) | (self.df["goscie"] == druzyna)
        return self.df[maska].copy()

    def analiza(self, druzyna: str, data_meczu_str: str) -> dict:
        """
        Zwraca slownik z mnoznikami i opisem.
        Klucze: rotacja, zmeczenie, mnoznik_atak, mnoznik_obr, ikony, opis
        """
        wynik = {
            "rotacja":      False,
            "zmeczenie":    False,
            "mnoznik_atak": 1.0,
            "mnoznik_obr":  1.0,
            "ikony":        "",
            "opis":         "",
        }
        data_meczu = _parse_date(data_meczu_str)
        if data_meczu is None or self.df.empty:
            return wynik

        mecze_d = self._mecze_druzyny(druzyna)
        if mecze_d.empty or "_dt" not in mecze_d.columns:
            return wynik
        mecze_d = mecze_d.dropna(subset=["_dt"])

        # 🔄 ROTACJA: mecz CL w oknie +/- ROTACJA_DNI
        okno_s = data_meczu - timedelta(days=ROTACJA_DNI)
        okno_e = data_meczu + timedelta(days=ROTACJA_DNI)
        mecze_cl = mecze_d[
            (mecze_d["_dt"] >= okno_s) &
            (mecze_d["_dt"] <= okno_e) &
            (mecze_d.get("competition", pd.Series(["?"]*len(mecze_d))) == "CL")
        ]
        if not mecze_cl.empty:
            wynik["rotacja"]      = True
            wynik["mnoznik_atak"] *= ROTACJA_KARA
            wynik["ikony"]        += "🔄"
            wynik["opis"]         += (
                f"🔄 Rotacja: {druzyna} gra CL w ciagu {ROTACJA_DNI} dni "
                f"(atak -{int((1-ROTACJA_KARA)*100)}%). "
            )

        # 😫 ZMECZENIE: ostatni mecz < ZMECZ_GODZ h
        prev = mecze_d[mecze_d["_dt"] < data_meczu].sort_values("_dt")
        if not prev.empty:
            diff_h = (data_meczu - prev.iloc[-1]["_dt"]).total_seconds() / 3600
            if diff_h < ZMECZ_GODZ:
                wynik["zmeczenie"]   = True
                wynik["mnoznik_obr"] *= ZMECZ_KARA_OBR
                wynik["ikony"]       += "😫"
                wynik["opis"]        += (
                    f"😫 Zmeczenie: {druzyna} grala {int(diff_h)}h temu "
                    f"(obrona -{int((1-ZMECZ_KARA_OBR)*100)}%). "
                )

        return wynik


# ================================================================
#  MODUL 7 - ANALIZA H2H (v2.5) + SYSTEM ZEMSTY + PATENT
# ================================================================

class AnalizaH2H:
    """
    Inteligentna analiza bezposrednich meczu (Head-to-Head) z filtrem 24 miesiecy.

    FILTR CZASOWY: brane sa wylacznie mecze z ostatnich H2H_OKNO_DNI = 730 dni.
    Starsze wyniki sa automatycznie odrzucane jako historycznie nieistotne.

    Wykrywane wzorce:

    🏅 PATENT (dominacja):
       Jesli jedna druzyna wygrywa WSZYSTKIE mecze H2H w ciagu 2 lat (min. H2H_MIN_MECZE=2),
       jej szanse przesunieto o PATENT_BONUS=+10%. Psychologicznie: "patent na rywala".

    ⚔️ ZEMSTA:
       Jesli ostatni mecz H2H zakonczyl sie roznica ZEMSTA_MIN_GOLE=3+ goli,
       druzyna przegrana dostaje ZEMSTA_BONUS=+15% do lambda_atak.

    📊 CONFIDENCE METER:
       Pewnosc typu (0-100%) na podstawie liczby swiezych meczow H2H:
         0 meczow = 20%  (minimalna pewnosc bazowa)
         1 mecz   = 40%
         2 mecze  = 60%
         3 mecze  = 75%
         4 mecze  = 87%
         5+ mecze = 100%
    """

    def __init__(self, df_mecze: pd.DataFrame):
        self.df = df_mecze.copy() if df_mecze is not None else pd.DataFrame()
        # Parsuj daty raz przy inicjalizacji
        if not self.df.empty and "data" in self.df.columns:
            self.df["_dt"] = pd.to_datetime(self.df["data"], errors="coerce")

    def _filtruj_h2h(self, druzyna1: str, druzyna2: str) -> pd.DataFrame:
        """
        Pobiera mecze H2H z ostatnich 24 miesiecy miedzy dwoma druzyna.
        Odrzuca wszystkie mecze starsze niz H2H_OKNO_DNI dni.
        """
        if self.df.empty:
            return pd.DataFrame()

        prog_cut = datetime.now() - timedelta(days=H2H_OKNO_DNI)

        maska = (
            (
                (self.df["gospodarz"] == druzyna1) & (self.df["goscie"] == druzyna2)
            ) | (
                (self.df["gospodarz"] == druzyna2) & (self.df["goscie"] == druzyna1)
            )
        )
        h2h = self.df[maska].copy()

        # Filtr czasowy: tylko 24 miesiace wstecz
        if "_dt" in h2h.columns:
            h2h = h2h[h2h["_dt"] >= pd.Timestamp(prog_cut)]

        return h2h.sort_values("data")

    def analiza(self, druzyna: str, przeciwnik: str) -> dict:
        """
        Zwraca kompletny wynik analizy H2H dla pary druzyn.

        Klucze slownika:
          patent        : bool  – dominacja w H2H (wszystkie wygrane)
          zemsta        : bool  – motywacja po wysokiej porazce
          mnoznik_atak  : float – laczny mnoznik lambda ataku
          mnoznik_szans : float – korekta szans (Patent +10%)
          ikona         : str   – ikony aktywnych czynnikow
          opis          : str   – opis do komentarza analityka
          pewnosc       : int   – Confidence Meter 0-100%
          n_h2h         : int   – liczba swiezych meczow H2H (<=24 mies.)
          h2h_df        : DataFrame – surowe dane H2H do wyswietlenia
        """
        wynik = {
            "patent":        False,
            "zemsta":        False,
            "mnoznik_atak":  1.0,
            "mnoznik_szans": 1.0,
            "ikona":         "",
            "opis":          "",
            "pewnosc":       20,   # minimalna pewnosc bazowa
            "n_h2h":         0,
            "h2h_df":        pd.DataFrame(),
        }

        h2h = self._filtruj_h2h(druzyna, przeciwnik)
        wynik["h2h_df"] = h2h
        wynik["n_h2h"]  = len(h2h)

        # ── Confidence Meter ──────────────────────────────────────────
        # Skala: 0→20%, 1→40%, 2→60%, 3→75%, 4→87%, 5+→100%
        skala = {0: 20, 1: 40, 2: 60, 3: 75, 4: 87}
        n = len(h2h)
        wynik["pewnosc"] = skala.get(n, 100) if n < CONFIDENCE_H2H_MAX else 100

        if h2h.empty:
            wynik["opis"] = f"Brak danych H2H z ostatnich 24 mies. (pewnosc: {wynik['pewnosc']}%)"
            return wynik

        # ── ZEMSTA: ostatni mecz H2H, roznica 3+ goli ────────────────
        ostatni  = h2h.iloc[-1]
        gg, ga   = int(ostatni["gole_g"]), int(ostatni["gole_a"])
        roznica  = abs(gg - ga)

        if roznica >= ZEMSTA_MIN_GOLE:
            # Ustal czy druzyna przegrala ten mecz
            if druzyna == ostatni["gospodarz"]:
                przegral = gg < ga
            else:
                przegral = ga < gg

            if przegral:
                wynik["zemsta"]       = True
                wynik["mnoznik_atak"] *= ZEMSTA_BONUS
                wynik["ikona"]        += "⚔️"
                wynik["opis"]         += (
                    f"⚔️ Zemsta: {druzyna} przegrala ostatni H2H z {przeciwnik} "
                    f"az {roznica} golami ({gg}:{ga}) "
                    f"→ motywacja rewanzowa, atak +{int((ZEMSTA_BONUS-1)*100)}%. "
                )

        # ── PATENT: wszystkie mecze H2H wygrane (min. 2) ─────────────
        if n >= H2H_MIN_MECZE:
            wygrane = 0
            for _, r in h2h.iterrows():
                gg_r, ga_r = int(r["gole_g"]), int(r["gole_a"])
                if druzyna == r["gospodarz"]:
                    if gg_r > ga_r: wygrane += 1
                else:
                    if ga_r > gg_r: wygrane += 1

            if wygrane == n:
                wynik["patent"]        = True
                wynik["mnoznik_szans"] = PATENT_BONUS
                wynik["ikona"]        += "🏅"
                wynik["opis"]         += (
                    f"🏅 Patent: {druzyna} wygrywa WSZYSTKIE {n} mecze H2H "
                    f"z ostatnich 24 mies. z {przeciwnik} "
                    f"→ przesuniecie szans +{int((PATENT_BONUS-1)*100)}%. "
                )

        if not wynik["opis"]:
            wynik["opis"] = (
                f"H2H {n} mecze (24 mies.): brak dominacji ani zemsta. "
                f"Pewnosc modelu: {wynik['pewnosc']}%."
            )

        return wynik

    @staticmethod
    def oblicz_pewnosc_laczna(n_h2h: int, n_meczow_ogolnie: int) -> int:
        """
        Oblicza laczna pewnosc typu lacząc dane H2H i ogolna liczbe meczow.
        Uzywana w Confidence Meter w tabeli kolejki.
        """
        # Baza z H2H (waga 60%)
        skala_h2h = {0: 20, 1: 40, 2: 60, 3: 75, 4: 87}
        baza_h2h  = skala_h2h.get(min(n_h2h, 4), 100) if n_h2h < CONFIDENCE_H2H_MAX else 100

        # Korekta z liczby ogolnych meczow (waga 40%)
        baza_og = min(100, int(n_meczow_ogolnie / OSTATNIE_N * 100))

        pewnosc = int(baza_h2h * 0.6 + baza_og * 0.4)
        return max(20, min(100, pewnosc))


# ================================================================
#  MODUL 7b - HOME FORTRESS (v2.5)
# ================================================================

class HomeFortress:
    """
    🏰 HOME FORTRESS: Twierdza domowa

    Jesli gospodarz nie przegral u siebie od FORTRESS_MECZE=5 meczow,
    model zaklada psychologiczna przewage na wlasnym stadionie.
    Efekt: lambda obrony gospodarza * FORTRESS_BONUS_OBR = +10%
    (czyli przyjmie mniej goli niz wskazywaloby to na statystyki).

    Wazne: bonus DODAJE sie do standardowego BONUS_DOMOWY,
    wiec lacznie gospodarz moze miec znaczaca przewage obronno-atakajna.
    """

    def __init__(self, df_mecze: pd.DataFrame):
        self.df = df_mecze.copy() if df_mecze is not None else pd.DataFrame()

    def analiza(self, gospodarz: str) -> dict:
        """
        Sprawdza serie bez porazki u siebie.
        Zwraca: {fortress, bonus_obrona, seria, ikona, opis}
        """
        wynik = {
            "fortress":     False,
            "bonus_obrona": 1.0,
            "seria":        0,
            "ikona":        "",
            "opis":         "",
        }

        if self.df is None or self.df.empty:
            return wynik

        dom = self.df[self.df["gospodarz"] == gospodarz].sort_values("data")
        if dom.empty:
            return wynik

        # Policz nieprzerwana serie bez porazki u siebie (od najnowszego)
        seria = 0
        for _, r in dom.iloc[::-1].iterrows():
            gg, ga = int(r["gole_g"]), int(r["gole_a"])
            if gg > ga or gg == ga:   # wygrana lub remis
                seria += 1
            else:                      # przegrana – stop
                break

        wynik["seria"] = seria

        if seria >= FORTRESS_MECZE:
            wynik["fortress"]     = True
            wynik["bonus_obrona"] = FORTRESS_BONUS_OBR
            wynik["ikona"]        = "🏰"
            wynik["opis"]         = (
                f"🏰 Twierdza domowa: {gospodarz} nie przegral u siebie od {seria} meczow "
                f"→ obrona +{int((FORTRESS_BONUS_OBR-1)*100)}% na wlasnym stadionie."
            )

        return wynik


# ================================================================
#  MODUL 8 - WAZONA FORMA
# ================================================================

def _wagi_mecze(df_mecze: pd.DataFrame) -> pd.Series:
    """
    Wagi czasowe: od najnowszego meczu:
      pozycja 0-2  (3 najnowsze): 1.5x
      pozycja 3-6               : 1.0x
      pozycja 7+                : 0.5x
    """
    n    = len(df_mecze)
    wagi = []
    for i in range(n):
        rev_i = n - 1 - i
        if rev_i < 3:
            wagi.append(1.5)
        elif rev_i < 7:
            wagi.append(1.0)
        else:
            wagi.append(0.5)
    return pd.Series(wagi, index=df_mecze.index)

def _oblicz_sile_wazona(df_mecze: pd.DataFrame) -> tuple:
    sr_g    = df_mecze["gole_g"].mean()
    sr_a    = df_mecze["gole_a"].mean()
    srednia = (sr_g + sr_a) / 2 or 1.0
    sily    = {}

    for d in set(df_mecze["gospodarz"]) | set(df_mecze["goscie"]):
        dom = df_mecze[df_mecze["gospodarz"] == d].copy()
        wyj = df_mecze[df_mecze["goscie"]    == d].copy()

        if not dom.empty:
            w_d   = _wagi_mecze(dom)
            str_d = (dom["gole_g"] * w_d).sum() / w_d.sum()
            st_d  = (dom["gole_a"] * w_d).sum() / w_d.sum()
        else:
            str_d = st_d = srednia

        if not wyj.empty:
            w_w   = _wagi_mecze(wyj)
            str_w = (wyj["gole_a"] * w_w).sum() / w_w.sum()
            st_w  = (wyj["gole_g"] * w_w).sum() / w_w.sum()
        else:
            str_w = st_w = srednia

        nd, nw = len(dom), len(wyj)
        nt     = nd + nw or 1
        strzal = (str_d * nd + str_w * nw) / nt
        strata = (st_d  * nd + st_w  * nw) / nt

        df_all = pd.concat([
            dom.assign(wynik_d=dom.apply(
                lambda r: "W" if r.gole_g>r.gole_a else("R" if r.gole_g==r.gole_a else "P"), axis=1)),
            wyj.assign(wynik_d=wyj.apply(
                lambda r: "W" if r.gole_a>r.gole_g else("R" if r.gole_a==r.gole_g else "P"), axis=1)),
        ]).sort_values("data").tail(OSTATNIE_N)

        forma_pkt = 0.0
        if not df_all.empty:
            w_all = _wagi_mecze(df_all)
            mapa  = {"W": 3, "R": 1, "P": 0}
            forma_pkt = sum(
                mapa.get(row.get("wynik_d", "P"), 0) * w_all[idx]
                for idx, row in df_all.iterrows()
            ) / (w_all.sum() or 1)

        sily[d] = {
            "atak":      strzal  / srednia,
            "obrona":    strata  / srednia,
            "mecze":     nt,
            "gole_sr":   round(strzal,  2),
            "strac_sr":  round(strata,  2),
            "forma_pkt": round(forma_pkt, 2),
        }

    return sily, srednia


# ================================================================
#  MODUL 9 - LOGIKA DWUMECZOW
# ================================================================

def _czy_knockout(stage: str) -> bool:
    return str(stage).upper() in {
        "FINAL", "THIRD_PLACE", "SEMI_FINALS", "QUARTER_FINALS",
        "LAST_16", "LAST_32", "LAST_64",
        "ROUND_4", "ROUND_3", "ROUND_2", "ROUND_1",
        "KNOCKOUT_PHASE_PLAYOFF",
        "PLAYOFF_ROUND_1", "PLAYOFF_ROUND_2", "PLAYOFFS",
        "ROUND_OF_16",
    }


# ================================================================
#  MODUL 9b – KLASYFIKATOR MECZU v2.6
# ================================================================

class KlasyfikatorMeczu:
    """
    Rozpoznaje typ meczu i generuje etykiete UI:
      [LIGA]          – REGULAR_SEASON
      [PUCHAR 1/2]    – faza pucharowa, pierwsza noga (lub brak historii)
      [REWANZ (X:Y)]  – wykryta druga noga (1. mecz w ostatnich 14 dniach)
      [FINAL]         – mecze finalne / turnieje bez rewanzu (EC, WC)

    Wykrywanie rewanzu: sprawdza czy w df_wyk istnieje mecz tych samych druzyn
    w tej samej fazie z ostatnich REWANZ_OKNO_DNI=14 dni.
    """

    def __init__(self, df_wyk: pd.DataFrame, kod_ligi: str = ""):
        self.df      = df_wyk.copy() if df_wyk is not None else pd.DataFrame()
        self.kod     = kod_ligi.upper()

    def klasyfikuj(self, g: str, a: str, stage: str, data_meczu_str: str,
                   first_leg_g=None, first_leg_a=None) -> dict:
        """
        Zwraca slownik:
          typ         : "LIGA" | "PUCHAR_1" | "REWANZ" | "FINAL"
          etykieta    : str  (do wyswietlenia w tabeli)
          etykieta_pdf: str  (bez Rich markup)
          rewanz      : bool
          single      : bool – mecz bez rewanzu (Final/EC/WC)
          agg_g       : int | None  – gole gosp. z 1. nogi
          agg_a       : int | None  – gole gosci z 1. nogi
          opis        : str
        """
        stage_up = str(stage).upper()

        # ── LIGA ────────────────────────────────────────────────────
        if stage_up == "REGULAR_SEASON":
            return {
                "typ":          "LIGA",
                "etykieta":     "[dim][LIGA][/dim]",
                "etykieta_pdf": "[LIGA]",
                "rewanz":       False,
                "single":       False,
                "agg_g":        None,
                "agg_a":        None,
                "opis":         "",
            }

        # ── FINAL / TURNIEJE BEZ REWANZU ────────────────────────────
        is_final_stage = stage_up in _FINAL_STAGES
        is_single_comp = self.kod in _SINGLE_MATCH_COMPS
        if is_final_stage or is_single_comp:
            label = "FINAL" if is_final_stage else "TURNIEJ"
            return {
                "typ":          "FINAL",
                "etykieta":     f"[bold magenta][{label}][/bold magenta]",
                "etykieta_pdf": f"[{label}]",
                "rewanz":       False,
                "single":       True,
                "agg_g":        None,
                "agg_a":        None,
                "opis":         f"Mecz {label} – bez rewanzu. Mozliwa dogrywka/karne.",
            }

        # ── FAZA PUCHAROWA – sprawdz czy to rewanz ──────────────────
        # Jesli API zwrocilo aggregateScore, uzyj go bezposrednio
        if first_leg_g is not None and first_leg_a is not None:
            try:
                ag, aa = int(first_leg_g), int(first_leg_a)
                roznica_agg = ag - aa
                return {
                    "typ":          "REWANZ",
                    "etykieta":     f"[bold cyan][REWANZ ({ag}:{aa})][/bold cyan]",
                    "etykieta_pdf": f"[REWANZ ({ag}:{aa})]",
                    "rewanz":       True,
                    "single":       False,
                    "agg_g":        ag,
                    "agg_a":        aa,
                    "opis":         f"Rewanz: wynik 1. meczu {ag}:{aa} (roznica {abs(roznica_agg)}).",
                }
            except (TypeError, ValueError):
                pass

        # Szukaj 1. nogi w historii (ostatnie REWANZ_OKNO_DNI dni)
        data_meczu = _parse_date(data_meczu_str)
        if data_meczu is not None and not self.df.empty:
            prog_cut = data_meczu - timedelta(days=REWANZ_OKNO_DNI)
            hist = self.df[
                (
                    ((self.df["gospodarz"] == g) & (self.df["goscie"] == a)) |
                    ((self.df["gospodarz"] == a) & (self.df["goscie"] == g))
                ) &
                (self.df["stage"] == stage)
            ].copy()
            if "data_full" in hist.columns:
                hist["_dt"] = hist["data_full"].apply(_parse_date)
            elif "data" in hist.columns:
                hist["_dt"] = hist["data"].apply(_parse_date)
            hist = hist.dropna(subset=["_dt"])
            hist = hist[hist["_dt"] >= prog_cut]

            if not hist.empty:
                pierwsza = hist.sort_values("_dt").iloc[-1]
                fg = int(pierwsza["gole_g"])
                fa = int(pierwsza["gole_a"])
                # Jesli w 1. meczu gospodarz byl goscia (teraz graja rewanz u siebie)
                # agg_g = gole aktualnego gospodarza
                if pierwsza["gospodarz"] == g:
                    agg_g, agg_a = fg, fa
                else:
                    agg_g, agg_a = fa, fg
                roznica = agg_g - agg_a
                return {
                    "typ":          "REWANZ",
                    "etykieta":     f"[bold cyan][REWANZ ({agg_g}:{agg_a})][/bold cyan]",
                    "etykieta_pdf": f"[REWANZ ({agg_g}:{agg_a})]",
                    "rewanz":       True,
                    "single":       False,
                    "agg_g":        agg_g,
                    "agg_a":        agg_a,
                    "opis":         f"Rewanz (wykryty z historii): wynik 1. meczu {fg}:{fa}.",
                }

        # Pierwsza noga (brak historii rewanzu)
        return {
            "typ":          "PUCHAR_1",
            "etykieta":     "[bold yellow][PUCHAR 1/2][/bold yellow]",
            "etykieta_pdf": "[PUCHAR 1/2]",
            "rewanz":       False,
            "single":       False,
            "agg_g":        None,
            "agg_a":        None,
            "opis":         f"Pierwsza noga: {stage_up}. Rewanz bedzie za ~7 dni.",
        }


def _korekta_rewanz_v26(lg: float, la: float,
                        agg_g: int, agg_a: int) -> tuple:
    """
    Korekta lambd dla rewanzu v2.6 (rozszerzona logika):

    Gospodarz (aktualny) = druzyna, ktora w 1. meczu byla goscia.
    agg_g = gole aktualnego gospodarza z 1. meczu (jako gosc)
    agg_a = gole aktualnych gosci z 1. meczu (jako gospodarz)

    Roznica = agg_g - agg_a (>0 = gospodarz prowadzi w dwumeczu)

    Progi:
      roznica >= +2: gospodarz prowadzi komfortowo → gra na czas
        atak  *REWANZ_PARKING_BUS (-25%)
        obrona *REWANZ_FORT_OBR (+20%)
      roznica <= -2: gospodarz przegrywa → vabank
        atak  *REWANZ_VABANK (+30%)
      roznica == -1 lub +1: minimalna roznica → oba atakuja
        atak  *1.10 dla obu
      remis (0:0 lub wyrownosc): neutralnie + lekki wzrost
    """
    roznica = agg_g - agg_a
    opis = f"[REWANZ] Wynik 1. meczu: {agg_g}:{agg_a} (roznica {'+' if roznica>=0 else ''}{roznica}). "

    if roznica >= 2:
        # Gospodarz prowadzi 2+ – gra na czas, goscie vabank
        opis += (f"Gospodarz PROWADZI (+{roznica}) → defensywa/gra na czas "
                 f"(atak -{int((1-REWANZ_PARKING_BUS)*100)}%, obrona +{int((REWANZ_FORT_OBR-1)*100)}%). "
                 f"Goscie gra VA-BANK (atak +{int((REWANZ_VABANK-1)*100)}%).")
        return (
            round(lg * REWANZ_PARKING_BUS, 3),
            round(la * REWANZ_VABANK / REWANZ_FORT_OBR, 3),
            opis,
        )
    elif roznica <= -2:
        # Gospodarz przegrywa 2+ – vabank, goscie defensywa
        opis += (f"Gospodarz PRZEGRYWA ({roznica}) → VA-BANK "
                 f"(atak +{int((REWANZ_VABANK-1)*100)}%). "
                 f"Goscie gra na czas (atak -{int((1-REWANZ_PARKING_BUS)*100)}%, "
                 f"obrona +{int((REWANZ_FORT_OBR-1)*100)}%).")
        return (
            round(lg * REWANZ_VABANK, 3),
            round(la * REWANZ_PARKING_BUS / REWANZ_FORT_OBR, 3),
            opis,
        )
    elif roznica == 0 and agg_g == agg_a:
        # Remis 0:0 lub rowny wynik → oba musza atakowac
        opis += "Remis – oba zespoly musza atakowac (+10% lambda obu)."
        return round(lg * 1.10, 3), round(la * 1.10, 3), opis
    else:
        # Roznica 1 lub -1 → wyrownana rywalizacja
        opis += f"Minimalna roznica (1 gol) → wyrownana walka, lekkie wzmocnienie ataku obu (+5%)."
        return round(lg * 1.05, 3), round(la * 1.05, 3), opis


def _korekta_dwumecz(lg, la, first_leg_g, first_leg_a, jest_gospodarzem_1: bool):
    """Kompatybilnosc wsteczna – uzywana gdy brak agg z API."""
    try:
        fg, fa = int(first_leg_g), int(first_leg_a)
    except (TypeError, ValueError):
        return lg, la, "Brak wyniku 1. meczu - standardowa analiza."
    roznica = fg - fa
    if not jest_gospodarzem_1:
        roznica = -roznica
    if abs(roznica) >= 3:
        if roznica > 0:
            return round(lg*0.60,3), round(la*1.50,3), (
                f"REWANZ: Gospodarz prowadzi {fg}:{fa} (+{roznica}). "
                "Parking Bus (atak -40%) vs All-In gosci (atak +50%).")
        else:
            return round(lg*1.50,3), round(la*0.60,3), (
                f"REWANZ: Goscie prowadza {fa}:{fg}. "
                "Gospodarz All-In (+50%), goscie Parking Bus (-40%).")
    elif roznica == 0 and fg == fa:
        return round(lg*1.10,3), round(la*1.10,3), (
            f"REWANZ: Remis 1. meczu ({fg}:{fa}) - oba zespoly musza atakowac.")
    return lg, la, f"REWANZ: Wynik 1. meczu {fg}:{fa} - standardowe lambdy."


# ================================================================
#  MODUL 10 - PREDYKCJA POISSONA
# ================================================================

def predict_match(
    g: str, a: str,
    df_mecze: pd.DataFrame,
    importance_g: dict = None,
    importance_a: dict = None,
    heurystyka_g: dict = None,
    heurystyka_a: dict = None,
    h2h_g: dict = None,
    h2h_a: dict = None,
    fortress_g: dict = None,
    first_leg_g=None, first_leg_a=None,
    stage: str = "REGULAR_SEASON",
    klasyfikacja: dict = None,
) -> dict | None:
    """
    Kompletna predykcja v2.6 z:
      1. Wazona forma historyczna
      2. Stage Recognition: LIGA vs PUCHAR vs REWANZ vs FINAL
      3. Fallback turniejowy: gdy brak statystyk pary, uzyj sredniej turniejowej
      4. Importance Index 2.0
      5. Heurystyka zmeczenia/rotacji
      6. AnalizaH2H: Patent +10%, Zemsta +15%
      7. HomeFortress: +10% obrona
      8. Rewanz Vabank v2.6 (+30% / Parking Bus)
      9. Single-Match Finals: boost remisu + uwaga 'dogr./karne'
    Zwraca dict lub None jesli za malo danych.
    """
    importance_g = importance_g or {"bonus_atak": 1.0, "komentarz": "", "status": "NORMAL"}
    importance_a = importance_a or {"bonus_atak": 1.0, "komentarz": "", "status": "NORMAL"}
    heurystyka_g = heurystyka_g or {"mnoznik_atak": 1.0, "mnoznik_obr": 1.0, "opis": ""}
    heurystyka_a = heurystyka_a or {"mnoznik_atak": 1.0, "mnoznik_obr": 1.0, "opis": ""}
    h2h_g        = h2h_g or {"mnoznik_atak": 1.0, "mnoznik_szans": 1.0, "opis": "", "pewnosc": 20, "n_h2h": 0}
    h2h_a        = h2h_a or {"mnoznik_atak": 1.0, "mnoznik_szans": 1.0, "opis": "", "pewnosc": 20, "n_h2h": 0}
    fortress_g   = fortress_g or {"bonus_obrona": 1.0, "fortress": False, "opis": ""}
    klasyfikacja = klasyfikacja or {"typ": "LIGA", "rewanz": False, "single": False,
                                    "agg_g": None, "agg_a": None, "opis": ""}

    stage_up     = str(stage).upper()
    is_liga      = (stage_up == "REGULAR_SEASON")
    jest_rewanz  = klasyfikacja.get("rewanz", False)
    jest_single  = klasyfikacja.get("single", False)

    # ── Zbierz mecze do analizy ──────────────────────────────────────
    maska = (
        (df_mecze["gospodarz"] == g) | (df_mecze["goscie"] == g) |
        (df_mecze["gospodarz"] == a) | (df_mecze["goscie"] == a)
    )
    df_f = df_mecze[maska].tail(OSTATNIE_N)

    # ── v2.6 STABILNOSC: fallback turniejowy ─────────────────────────
    # Jesli brak danych pary w fazie pucharowej, nie zwracamy None —
    # uzyj ogolnej sredniej z df_mecze (min 4 mecze dowolnych).
    if len(df_f) < 4:
        if is_liga:
            return None  # Liga: normalna sciezka, brak danych = brak predykcji
        # Tryb turniejowy: probuj z calym df
        df_f_all = df_mecze.tail(OSTATNIE_N * 2)
        if len(df_f_all) < 4:
            return None
        # Policz srednia turniejowa i syntetyczne sily dla pary
        sily_all, srednia_all = _oblicz_sile_wazona(df_f_all)
        if not sily_all:
            return None
        # Szacuj sily jako srednia turniejowa (fallback)
        avg_atak  = float(np.mean([v["atak"]   for v in sily_all.values()]))
        avg_obr   = float(np.mean([v["obrona"] for v in sily_all.values()]))
        avg_gsr   = float(np.mean([v["gole_sr"] for v in sily_all.values()]))
        avg_strac = float(np.mean([v["strac_sr"] for v in sily_all.values()]))
        avg_forma = float(np.mean([v["forma_pkt"] for v in sily_all.values()]))
        syntetyczna = {
            "atak": avg_atak, "obrona": avg_obr,
            "gole_sr": avg_gsr, "strac_sr": avg_strac, "forma_pkt": avg_forma
        }
        sg = sily_all.get(g, syntetyczna)
        sa = sily_all.get(a, syntetyczna)
        srednia = srednia_all
        df_f    = df_f_all   # do confidence
    else:
        sily, srednia = _oblicz_sile_wazona(df_f)
        if g not in sily or a not in sily:
            return None
        sg, sa = sily[g], sily[a]

    # ── Lambda bazowa ────────────────────────────────────────────────
    lambda_g = max(0.05,
        sg["atak"]
        * sa["obrona"]
        * srednia
        * BONUS_DOMOWY
        * importance_g["bonus_atak"]
        * heurystyka_g["mnoznik_atak"]
        * h2h_g["mnoznik_atak"]
        / heurystyka_a["mnoznik_obr"]
    )
    lambda_a = max(0.05,
        sa["atak"]
        * sg["obrona"]
        * srednia
        * importance_a["bonus_atak"]
        * heurystyka_a["mnoznik_atak"]
        * h2h_a["mnoznik_atak"]
        / heurystyka_g["mnoznik_obr"]
        / fortress_g["bonus_obrona"]
    )

    # Patent H2H
    lambda_g *= h2h_g.get("mnoznik_szans", 1.0)
    lambda_a *= h2h_a.get("mnoznik_szans", 1.0)
    lambda_g = max(0.05, lambda_g)
    lambda_a = max(0.05, lambda_a)

    # ── v2.6 Korekta rewanzowa ───────────────────────────────────────
    korekta_opis = ""
    jest_knockout = _czy_knockout(stage)

    if jest_rewanz:
        agg_g = klasyfikacja.get("agg_g")
        agg_a = klasyfikacja.get("agg_a")
        if agg_g is not None and agg_a is not None:
            lambda_g, lambda_a, korekta_opis = _korekta_rewanz_v26(
                lambda_g, lambda_a, int(agg_g), int(agg_a))
        elif first_leg_g is not None:
            lambda_g, lambda_a, korekta_opis = _korekta_dwumecz(
                lambda_g, lambda_a, first_leg_g, first_leg_a, jest_gospodarzem_1=False)
    elif jest_knockout and first_leg_g is not None:
        lambda_g, lambda_a, korekta_opis = _korekta_dwumecz(
            lambda_g, lambda_a, first_leg_g, first_leg_a, jest_gospodarzem_1=False)

    lambda_g = max(0.05, lambda_g)
    lambda_a = max(0.05, lambda_a)

    # ── Macierz Poissona ─────────────────────────────────────────────
    N = MAX_GOLE + 1
    M = np.zeros((N, N))
    for i in range(N):
        for j in range(N):
            M[i][j] = poisson.pmf(i, lambda_g) * poisson.pmf(j, lambda_a)

    pw  = float(np.sum(np.tril(M, -1)))
    pr  = float(np.sum(np.diag(M)))
    pp  = float(np.sum(np.triu(M,  1)))

    # ── v2.6 Final boost: wiekszy remis w meczach bez rewanzu ────────
    if jest_single:
        pr *= FINAL_REMIS_BOOST   # szansa remisu rosnie (dogrywka/karne realna)

    suma = pw + pr + pp or 1.0
    pw /= suma; pr /= suma; pp /= suma

    btts   = (1 - poisson.pmf(0, lambda_g)) * (1 - poisson.pmf(0, lambda_a))
    over25 = 1.0 - sum(M[i][j] for i in range(N) for j in range(N) if i+j <= 2)
    over25 = min(over25 / suma, 1.0)

    idx  = np.unravel_index(np.argmax(M), M.shape)
    flat = sorted([(M[i][j], i, j) for i in range(N) for j in range(N)], reverse=True)
    top5 = [(f"{i}:{j}", round(p*100, 1)) for p, i, j in flat[:5]]

    n_h2h_srednia = (h2h_g.get("n_h2h", 0) + h2h_a.get("n_h2h", 0)) // 2
    pewnosc = AnalizaH2H.oblicz_pewnosc_laczna(n_h2h_srednia, len(df_f))

    return {
        "gospodarz":    g,
        "gosc":         a,
        "lambda_g":     round(lambda_g, 2),
        "lambda_a":     round(lambda_a, 2),
        "p_wygrana":    round(pw  * 100, 1),
        "p_remis":      round(pr  * 100, 1),
        "p_przegrana":  round(pp  * 100, 1),
        "btts":         round(btts  * 100, 1),
        "over25":       round(over25 * 100, 1),
        "under25":      round((1 - over25) * 100, 1),
        "wynik_g":      int(idx[0]),
        "wynik_a":      int(idx[1]),
        "top5":         top5,
        "sila_at_g":    round(sg["atak"],   2),
        "sila_ob_g":    round(sg["obrona"], 2),
        "sila_at_a":    round(sa["atak"],   2),
        "sila_ob_a":    round(sa["obrona"], 2),
        "forma_g":      sg["forma_pkt"],
        "forma_a":      sa["forma_pkt"],
        "imp_g":        importance_g,
        "imp_a":        importance_a,
        "heur_g":       heurystyka_g,
        "heur_a":       heurystyka_a,
        "h2h_g":        h2h_g,
        "h2h_a":        h2h_a,
        "fortress_g":   fortress_g,
        "knockout":     jest_knockout,
        "rewanz":       jest_rewanz,
        "single":       jest_single,
        "korekta_opis": korekta_opis,
        "klasyfikacja": klasyfikacja,
        "pewnosc":      pewnosc,
    }


# ================================================================
#  MODUL 11 - TYPY BUKMACHERSKIE
# ================================================================

def typy_zaklady(w: dict) -> list:
    pw, pr, pp  = w["p_wygrana"], w["p_remis"], w["p_przegrana"]
    bt, o25, u25 = w["btts"], w["over25"], w["under25"]
    wyniki = []
    def dodaj(typ, val, pewny=70, dobry=55):
        if val >= pewny:   wyniki.append((typ, f"{val:.1f}%", "PEWNY"))
        elif val >= dobry: wyniki.append((typ, f"{val:.1f}%", "DOBRY"))
    dodaj("1  (Gospodarz wygrywa)", pw)
    if pr >= 32: wyniki.append(("X  (Remis)", f"{pr:.1f}%", "DOBRY"))
    dodaj("2  (Gosc wygrywa)", pp)
    dodaj("1X (Gosp. lub remis)",  pw + pr, 80, 72)
    dodaj("X2 (Remis lub gosc)",   pr + pp, 80, 72)
    dodaj("12 (Ktos wygrywa)",     pw + pp, 85, 75)
    dodaj("BTTS TAK", bt, 65, 55)
    if bt < 45: wyniki.append(("BTTS NIE", f"{100-bt:.1f}%", "DOBRY" if 100-bt>=60 else "SLABY"))
    dodaj("Over 2.5", o25, 70, 58)
    dodaj("Under 2.5", u25, 68, 58)
    return wyniki


# ================================================================
#  MODUL 12 - KOMENTARZ ANALITYKA
# ================================================================

def komentarz_analityka(w: dict) -> str:
    g, a       = w["gospodarz"], w["gosc"]
    pw, pr, pp = w["p_wygrana"], w["p_remis"], w["p_przegrana"]
    linie      = []

    # ── v2.6 Kontekst meczu ──────────────────────────────────────────
    klas = w.get("klasyfikacja", {})
    typ  = klas.get("typ", "LIGA")
    if typ == "REWANZ":
        agg_g = klas.get("agg_g", "?")
        agg_a = klas.get("agg_a", "?")
        linie.append(f"[REWANZ] Wynik 1. meczu: {agg_g}:{agg_a}. {klas.get('opis','')}")
    elif typ == "FINAL":
        linie.append(
            f"[FINAL/TURNIEJ] Mecz bez rewanzu. "
            f"Uwaga: mozliwa dogrywka/karne (remis po 90 min = {pr:.0f}%, "
            f"prawdopodobienstwo wzroslo o +{int((FINAL_REMIS_BOOST-1)*100)}% vs standard)."
        )
    elif typ == "PUCHAR_1":
        linie.append(f"[PUCHAR 1/2] Pierwsza noga – wynik bedzie ksztaltowal rewanz.")

    if pw >= 65:       linie.append(f"Model faworyzuje {g} ({pw:.0f}% szans na wygrana).")
    elif pp >= 65:     linie.append(f"Model faworyzuje {a} ({pp:.0f}% szans na wygrana).")
    elif pr >= 28:     linie.append(f"Mecz wyrownany – wysoka szansa na remis ({pr:.0f}%).")
    else:              linie.append("Mecz wyrownany – roznice minimalne.")

    # Importance Index 2.0 – nowe statusy v2.5
    for d, imp in [(g, w.get("imp_g",{})), (a, w.get("imp_a",{}))]:
        st = imp.get("status", "NORMAL")
        if st == "FINAL_TOP":
            linie.append(f"{d}: TRYB FINALNY – walka o podium, atak +20% (zostalo maks. 5 kolejek).")
        elif st == "FINAL_RELEGATION":
            linie.append(f"{d}: TRYB FINALNY – desperacja o utrzymanie, atak +20%.")
        elif st == "VACATION":
            linie.append(f"{d}: Efekt wakacji – bezpieczna pozycja, motywacja -10%.")
        elif st == "HIGH_STAKES_TOP":
            linie.append(f"{d} walczy o TOP/tytul – agresja ofensywna +20%.")
        elif st == "HIGH_STAKES_BOTTOM":
            linie.append(f"{d} zagrozony spadkiem – gra pod presja.")
        elif st == "COMFORT":
            linie.append(f"{d} w strefie komfortu – motywacja obnizona -10%.")

    # Heurystyka v2.4
    for d, heur in [(g, w.get("heur_g",{})), (a, w.get("heur_a",{}))]:
        if heur.get("opis"): linie.append(heur["opis"].strip())

    # H2H v2.5 – Patent i Zemsta
    for d, h2h in [(g, w.get("h2h_g",{})), (a, w.get("h2h_a",{}))]:
        opis = h2h.get("opis", "")
        if opis and (h2h.get("patent") or h2h.get("zemsta")):
            linie.append(opis.strip())

    # Home Fortress v2.5
    fort = w.get("fortress_g", {})
    if fort.get("fortress") and fort.get("opis"):
        linie.append(fort["opis"].strip())

    # Forma
    fg, fa = w.get("forma_g", 0), w.get("forma_a", 0)
    if fg > fa + 0.5:   linie.append(f"Forma {g} ({fg:.1f} pkt/mecz) lepsza niz {a} ({fa:.1f}).")
    elif fa > fg + 0.5: linie.append(f"Forma {a} ({fa:.1f} pkt/mecz) lepsza niz {g} ({fg:.1f}).")

    if w["btts"] >= 65:  linie.append(f"Obie druzyny prawdopodobnie strzela ({w['btts']:.0f}% BTTS).")
    if w["over25"] >= 70: linie.append(f"Mecz bramkostrzelny – Over 2.5 ({w['over25']:.0f}%).")
    elif w["under25"] >= 65: linie.append(f"Mecz defensywny – Under 2.5 ({w['under25']:.0f}%).")
    if w.get("knockout") and w.get("korekta_opis"):
        linie.append(w["korekta_opis"])

    # Confidence Meter
    pewnosc = w.get("pewnosc", 20)
    linie.append(f"Pewnosc modelu: {pewnosc}% (baza danych H2H 24 mies. + historia ogolna).")

    return " ".join(linie)


# ================================================================
#  MODUL 13 - ANALIZA FORMY
# ================================================================

def pobierz_forme(druzyna: str, df_mecze: pd.DataFrame, n: int = 8) -> pd.DataFrame:
    dom = df_mecze[df_mecze["gospodarz"] == druzyna].copy()
    wyj = df_mecze[df_mecze["goscie"]    == druzyna].copy()
    dom["wynik"]     = dom.apply(lambda r: "W" if r.gole_g>r.gole_a else("R" if r.gole_g==r.gole_a else "P"), axis=1)
    dom["strzelone"] = dom["gole_g"]; dom["stracone"] = dom["gole_a"]; dom["miejsce"] = "Dom"
    wyj["wynik"]     = wyj.apply(lambda r: "W" if r.gole_a>r.gole_g else("R" if r.gole_a==r.gole_g else "P"), axis=1)
    wyj["strzelone"] = wyj["gole_a"]; wyj["stracone"] = wyj["gole_g"]; wyj["miejsce"] = "Wyjazd"
    kols = ["data","gospodarz","goscie","gole_g","gole_a","wynik","strzelone","stracone","miejsce"]
    return pd.concat([dom[kols], wyj[kols]]).sort_values("data").tail(n)

def wyswietl_forme(druzyna: str, df_mecze: pd.DataFrame, n: int = 8):
    df = pobierz_forme(druzyna, df_mecze, n)
    if df.empty:
        console.print(f"[red]Brak danych dla: {druzyna}[/red]"); return
    t = Table(title=f"[bold cyan]Forma: {druzyna}[/bold cyan]",
              box=box.MINIMAL_DOUBLE_HEAD, border_style="cyan", header_style="bold cyan")
    t.add_column("Data",   style="dim",        justify="center", width=11)
    t.add_column("Gosp.",  style="bold white",  justify="right",  width=14)
    t.add_column("Wynik",  style="bold yellow", justify="center", width=7)
    t.add_column("Goscie", style="bold white",  justify="left",   width=14)
    t.add_column("Gdzie",  style="dim",         justify="center", width=8)
    t.add_column("W/R/P",  style="bold",        justify="center", width=5)
    for _, r in df.iloc[::-1].iterrows():
        k = "bold green" if r["wynik"]=="W" else("bold yellow" if r["wynik"]=="R" else "bold red")
        t.add_row(_s(r["data"]), _s(r["gospodarz"]), f"{r['gole_g']}-{r['gole_a']}",
                  _s(r["goscie"]), _s(r["miejsce"]), f"[{k}]{r['wynik']}[/{k}]")
    console.print(t)
    pasek = Text()
    for w in df["wynik"]:
        if w=="W":   pasek.append(" W ", style="bold white on green")
        elif w=="R": pasek.append(" R ", style="bold black on yellow")
        else:        pasek.append(" P ", style="bold white on red")
        pasek.append(" ")
    console.print(Align.center(pasek))
    console.print(Align.center(Text(
        f"  Sr. strzelon: {df['strzelone'].mean():.2f}  |  Sr. stracon: {df['stracone'].mean():.2f}  ",
        style="dim")))
    console.print()

def porownaj_forme(g: str, a: str, df_mecze: pd.DataFrame, n: int = 8):
    console.rule(f"[bold cyan]{g}  vs  {a}[/bold cyan]")
    wyswietl_forme(g, df_mecze, n)
    wyswietl_forme(a, df_mecze, n)
    maska = ((df_mecze["gospodarz"]==g)|(df_mecze["goscie"]==g)|
             (df_mecze["gospodarz"]==a)|(df_mecze["goscie"]==a))
    df_f  = df_mecze[maska].tail(OSTATNIE_N)
    if len(df_f) < 4: return
    sily, _ = _oblicz_sile_wazona(df_f)
    if g not in sily or a not in sily: return
    sg, sa = sily[g], sily[a]

    def lepsza(v1, v2, wyzej=True):
        s1 = "bold green" if (v1>=v2 if wyzej else v1<=v2) else "dim"
        s2 = "bold green" if (v2>v1  if wyzej else v2<v1)  else "dim"
        return f"[{s1}]{v1}[/{s1}]", f"[{s2}]{v2}[/{s2}]"

    tc = Table(title="[bold magenta]Porownanie Wskaznikow[/bold magenta]",
               box=box.ROUNDED, border_style="magenta", header_style="bold magenta")
    tc.add_column("Wskaznik", style="dim",       justify="right",  width=28)
    tc.add_column(g[:16],     style="bold green", justify="center", width=10)
    tc.add_column(a[:16],     style="bold red",   justify="center", width=10)
    for label, v1, v2, w2 in [
        ("Wspolczynnik ataku (wazony)",  sg["atak"],     sa["atak"],     True),
        ("Wspolczynnik obrony (wazony)", sg["obrona"],   sa["obrona"],   False),
        ("Sr. goli strzelonych",         sg["gole_sr"],  sa["gole_sr"],  True),
        ("Sr. goli straconych",          sg["strac_sr"], sa["strac_sr"], False),
        ("Forma pkt/mecz (wazony)",      sg["forma_pkt"],sa["forma_pkt"],True),
    ]:
        r1, r2 = lepsza(round(v1,2), round(v2,2), w2)
        tc.add_row(label, r1, r2)
    console.print(tc)

    h2h = df_mecze[
        ((df_mecze["gospodarz"]==g)&(df_mecze["goscie"]==a)) |
        ((df_mecze["gospodarz"]==a)&(df_mecze["goscie"]==g))
    ].tail(5)
    if not h2h.empty:
        th = Table(title=f"[bold yellow]H2H: {g} vs {a}[/bold yellow]",
                   box=box.MINIMAL, border_style="yellow", header_style="bold yellow")
        th.add_column("Data",  style="dim",        justify="center")
        th.add_column("Gosp.", style="bold white",  justify="right")
        th.add_column("Wynik", style="bold yellow", justify="center")
        th.add_column("Gosc",  style="bold white",  justify="left")
        for _, r in h2h.iloc[::-1].iterrows():
            gg, ga = r["gole_g"], r["gole_a"]
            kg = "bold green" if gg>ga else("yellow" if gg==ga else "dim red")
            ka = "bold red"   if gg>ga else("yellow" if gg==ga else "bold green")
            th.add_row(_s(r["data"]), f"[{kg}]{r['gospodarz']}[/{kg}]",
                       f"{gg}-{ga}", f"[{ka}]{r['goscie']}[/{ka}]")
        console.print(th)



# ================================================================
#  MODUL 13b - ANALIZA DOM/WYJAZD (v2.7)
# ================================================================

class AnalizaDomWyjazd:
    """
    Osobne statystyki domowe i wyjazdowe druzyny.
    Wykrywa 'Podroznika' - druzyne lepsza na wyjezdzie niz u siebie.
    """

    def __init__(self, df_mecze):
        self.df = df_mecze.copy() if df_mecze is not None else __import__("pandas").DataFrame()

    def analiza(self, druzyna, n=10):
        wynik = {
            "druzyna": druzyna, "dom_pkt": 0.0, "wyjazd_pkt": 0.0,
            "dom_gole_str": 0.0, "dom_gole_strac": 0.0,
            "wyj_gole_str": 0.0, "wyj_gole_strac": 0.0,
            "dom_seria": "", "wyj_seria": "", "dom_m": 0, "wyj_m": 0,
            "podroznik": False, "bonus_wyjazd": 1.0, "opis": "", "ikona": "",
        }
        if self.df.empty:
            return wynik

        dom = self.df[self.df["gospodarz"] == druzyna].sort_values("data").tail(n)
        wyj = self.df[self.df["goscie"] == druzyna].sort_values("data").tail(n)

        def _stats(df_sub, is_dom):
            if df_sub.empty:
                return 0.0, 0.0, 0.0, ""
            pkt = 0; seria = []
            for _, r in df_sub.iterrows():
                gg, ga = int(r["gole_g"]), int(r["gole_a"])
                w = gg > ga if is_dom else ga > gg
                re = gg == ga
                if w:     pkt += 3; seria.append("W")
                elif re:  pkt += 1; seria.append("R")
                else:     seria.append("P")
            n_m = len(df_sub)
            avg_g = float(df_sub["gole_g"].mean() if is_dom else df_sub["gole_a"].mean())
            avg_s = float(df_sub["gole_a"].mean() if is_dom else df_sub["gole_g"].mean())
            return round(pkt/n_m, 2), round(avg_g, 2), round(avg_s, 2), " ".join(seria[-5:])

        d_pkt, d_str, d_strac, d_ser = _stats(dom, True)
        w_pkt, w_str, w_strac, w_ser = _stats(wyj, False)

        wynik.update({
            "dom_pkt": d_pkt, "wyjazd_pkt": w_pkt,
            "dom_gole_str": d_str, "dom_gole_strac": d_strac,
            "wyj_gole_str": w_str, "wyj_gole_strac": w_strac,
            "dom_seria": d_ser, "wyj_seria": w_ser,
            "dom_m": len(dom), "wyj_m": len(wyj),
        })

        roznica = w_pkt - d_pkt
        if len(wyj) >= DOMWYJAZD_MIN_M and roznica >= DOMWYJAZD_PODROZNIK:
            wynik.update({
                "podroznik": True, "bonus_wyjazd": 1.10, "ikona": "✈️",
                "opis": (f"✈️ Podroznik: {druzyna} lepszy na wyjezdzie "
                         f"({w_pkt:.2f} pkt/m) niz u siebie ({d_pkt:.2f} pkt/m). "
                         f"Lambda ataku goscia +10%.")
            })
        elif d_pkt > w_pkt + 0.3:
            wynik["opis"] = (f"🏠 Bastion: {druzyna} silniejszy u siebie "
                             f"({d_pkt:.2f} vs {w_pkt:.2f} pkt/mecz wyjazd).")
        else:
            wynik["opis"] = (f"~= Wyrownany: {druzyna} dom {d_pkt:.2f} / "
                             f"wyjazd {w_pkt:.2f} pkt/mecz.")
        return wynik

    def wyswietl(self, druzyna, n=10):
        w = self.analiza(druzyna, n)
        console.rule(f"[bold cyan]Analiza Dom/Wyjazd: {druzyna}[/bold cyan]")
        t = Table(box=box.ROUNDED, border_style="cyan", header_style="bold cyan")
        t.add_column("Metryka", style="dim", justify="right", width=24)
        t.add_column("🏠 DOM", style="bold green", justify="center", width=14)
        t.add_column("✈️ WYJAZD", style="bold yellow", justify="center", width=14)
        t.add_column("Delta", style="bold", justify="center", width=10)

        def delta(d, wy, im_wyzej=True):
            r = round(wy - d, 2)
            k = ("bold green" if (r>0) == im_wyzej else "bold red") if r != 0 else "dim"
            return f"[{k}]{'+' if r>0 else ''}{r}[/{k}]"

        t.add_row("Mecze (ostatnie)", str(w["dom_m"]), str(w["wyj_m"]), "")
        t.add_row("Pkt/mecz", f"[bold]{w['dom_pkt']}[/bold]",
                  f"[bold]{w['wyjazd_pkt']}[/bold]",
                  delta(w["dom_pkt"], w["wyjazd_pkt"]))
        t.add_row("Gole str./mecz", str(w["dom_gole_str"]), str(w["wyj_gole_str"]),
                  delta(w["dom_gole_str"], w["wyj_gole_str"]))
        t.add_row("Gole strac./mecz", str(w["dom_gole_strac"]), str(w["wyj_gole_strac"]),
                  delta(w["dom_gole_strac"], w["wyj_gole_strac"], False))
        t.add_row("Forma (5 ost.)", w["dom_seria"] or "–", w["wyj_seria"] or "–", "")
        console.print(t)
        styl = "green" if w["podroznik"] else "dim"
        console.print(Panel(w["opis"], border_style=styl, padding=(0, 2)))
        console.print()


# ================================================================
#  MODUL 13c – PEWNIACZKI TYGODNIA – MULTI-LIGA  (v2.7.1)
# ================================================================
#
#  Cele:
#    - Skanuje WSZYSTKIE dostepne ligi (FDB + Bzzoiro), nie tylko biezaca
#    - 3-warstwowa strategia: Poisson > ML Bzzoiro > brak
#    - Deduplikacja: ten sam mecz nie pojawi sie dwa razy
#    - Cross-walidacja Poisson vs ML (ostrzezenie gdy >20% roznica)
#    - Eksport wynikow do PDF (eksportuj_pdf_pewniaczki)
#
#  Strategia zbierania danych:
#    Warstwa 1 – Bzzoiro (0 req, wszystkie ligi, ML CatBoost)
#      Pobiera ~400+ meczow z 22 lig na raz – buduje indeks ML
#    Warstwa 2 – Biezaca liga (0 req, pelen Poisson z historia)
#      Nadpisuje ML dla tych samych meczow (Poisson dokladniejszy)
#    Warstwa 3 – Inne ligi FDB (opcja; ~N req, 10/min)
#      Pobiera tylko nadchodzace; predykcja z ML jesli dostepna
#
#  Budzet req:
#    FDB:    0 + ~N opcjonalnych (inne ligi)
#    AF:     0 (wylacznie disk cache, nie pyta sieci dla Pewniakow)
#    Bzzoiro: 1 req na pobranie wszystkich lig naraz
# ================================================================


# ── Pomocnicze: zbieranie typow bukmacherskich ─────────────────

def _typy_pewne(pw: float, pr: float, pp: float,
                bt: float, o25: float, u25: float,
                g: str, a: str, prog: float) -> list:
    """
    Sprawdza 8 typow bukmacherskich i zwraca liste (opis, szansa)
    dla typow z szansa >= prog%.

    Typy: 1, 2, 1X, X2, 12, BTTS, Over/Under 2.5
    """
    wynik = []
    for opis, wartosc in [
        (f"1 – Wygrana {g[:15]}",  pw),
        (f"2 – Wygrana {a[:15]}",  pp),
        ("1X – Gosp. lub Remis",   pw + pr),
        ("X2 – Remis lub Gosc",    pr + pp),
        ("12 – Ktos wygrywa",      pw + pp),
        ("BTTS TAK",               bt),
        ("Over 2.5",               o25),
        ("Under 2.5",              u25),
    ]:
        if wartosc >= prog:
            wynik.append((opis, round(wartosc, 1)))
    return wynik


# ── Pomocnicze: predykcja ML Bzzoiro → format standardowy ─────

def _bzz_parse_prob(pred_ml: dict) -> tuple:
    """
    Uniwersalny parser Bzzoiro – WSZYSTKIE znane formaty API sports.bzzoiro.com.

    Zbadane formaty:
      Format A: {percent: {home:"55%", draw:"25%", away:"20%"}}  <- GLOWNY
      Format B: {home_win_prob:0.55, draw_prob:0.25, away_win_prob:0.20}
      Format C: {home:55, draw:25, away:20}
      Format D: zagniezdzone {predictions:{...}} lub {prediction:{...}}

    Zwraca (pw, pr, pp, bt, o25) jako procenty 0-100 lub None.
    """
    if not pred_ml or not isinstance(pred_ml, dict):
        return None

    def p(v):
        if v is None:
            return 0.0
        try:
            f = float(str(v).strip().rstrip('%'))
            # UWAGA: granica 1.0 jest niejednoznaczna.
            # Uzywamy SCISLEGO < 1.0 zamiast <= 1.0:
            #   0.55 → ulamek → *100 = 55.0  ✓
            #   1.0  → procent → 1.0          ✓ (1% to rzadkie ale poprawne)
            #   55.0 → procent → 55.0         ✓
            return f * 100 if 0 < f < 1.0 else f
        except (ValueError, TypeError):
            return 0.0

    def norm(pw, pr, pp, bt=0.0, o25=0.0):
        s = pw + pr + pp or 100.0
        return (round(pw/s*100, 1), round(pr/s*100, 1),
                round(100 - pw/s*100 - pr/s*100, 1),
                round(min(max(bt, 0), 100), 1),
                round(min(max(o25, 0), 100), 1))

    # Format A: percent.home/draw/away (glowny format Bzzoiro)
    pct = pred_ml.get("percent") or pred_ml.get("percentages")
    if isinstance(pct, dict):
        pw, pr, pp = p(pct.get("home")), p(pct.get("draw")), p(pct.get("away"))
        if pw + pr + pp > 5:
            bt  = p(pct.get("btts") or pred_ml.get("btts", 0))
            o25 = p(pct.get("over_2_5") or pred_ml.get("over_2_5", 0))
            return norm(pw, pr, pp, bt, o25)

    # Format B: home_win_prob / draw_prob / away_win_prob
    if "home_win_prob" in pred_ml:
        pw = p(pred_ml.get("home_win_prob"))
        pr = p(pred_ml.get("draw_prob"))
        pp = p(pred_ml.get("away_win_prob"))
        if pw + pr + pp > 5:
            return norm(pw, pr, pp,
                        p(pred_ml.get("btts", 0)),
                        p(pred_ml.get("over_2_5", 0)))

    # Format C: home/draw/away bezposrednio
    if all(k in pred_ml for k in ("home", "draw", "away")):
        pw, pr, pp = p(pred_ml["home"]), p(pred_ml["draw"]), p(pred_ml["away"])
        if pw + pr + pp > 5:
            return norm(pw, pr, pp)

    # Format D: zagniezdzone predictions/prediction
    nested = pred_ml.get("predictions") or pred_ml.get("prediction")
    if isinstance(nested, dict):
        return _bzz_parse_prob(nested)

    return None


def _ml_do_predykcji(pred_ml: dict | None, odds: dict | None = None) -> dict | None:
    """
    Konwertuje predykcje ML z Bzzoiro do wspolnego formatu predykcji.
    Uzywa _bzz_parse_prob() – obsluguje wszystkie formaty API Bzzoiro.
    Zwraca None gdy brak danych lub niemozliwe parsowanie.
    """
    if not pred_ml:
        return None
    try:
        wyp = _bzz_parse_prob(pred_ml)
        if wyp is None:
            return None
        pw, pr, pp, bt, o25 = wyp
        ms = pred_ml.get("most_likely_score") or pred_ml.get("goals") or {}
        wg = int(ms.get("home", 1) or 1)
        wa = int(ms.get("away", 0) or 0)
        return {
            "metoda":    "ML",
            "p_wygrana": pw, "p_remis": pr, "p_przegrana": pp,
            "btts":      bt, "over25": o25, "under25": round(100-o25, 1),
            "wynik_g":   wg, "wynik_a": wa,
            "lambda_g":  "–", "lambda_a": "–",
            "pewnosc":   55,
            "odds":      odds,
        }
    except Exception:
        return None


# ── Glowna funkcja skanowania ──────────────────────────────────

def pewniaczki_tygodnia(
    api_fdb,
    df_wyk_biezaca,
    df_nad_biezaca,
    nazwa_biezacej: str,
    importance_idx,
    heurystyka_eng,
    h2h_sys,
    fortress_sys,
    dw_sys,
    klasyfikator,
    bzzoiro=None,
    skanuj_inne_ligi: bool = True,
    prog: float = PEWNIACZEK_PROG,
) -> list:
    """
    Skanuje nadchodzace mecze z WSZYSTKICH dostepnych lig
    i zwraca liste Pewniakow (typy z szansa >= prog%).

    Parametry:
        api_fdb           – klient football-data.org
        df_wyk_biezaca    – DataFrame wynikow biezacej ligi (do Poissona)
        df_nad_biezaca    – DataFrame nadchodzacych biezacej ligi
        nazwa_biezacej    – nazwa biezacej ligi (do etykiet)
        importance_idx    – system ImportanceIndex
        heurystyka_eng    – system HeurystaZmeczeniaRotacji
        h2h_sys           – system AnalizaH2H
        fortress_sys      – system HomeFortress
        dw_sys            – system AnalizaDomWyjazd
        klasyfikator      – KlasyfikatorMeczu
        bzzoiro           – klient BzzoiroClient (None = nieaktywny)
        skanuj_inne_ligi  – True = pobierz nadchodzace z innych lig FDB
        prog              – min. szansa typu (domyslnie PEWNIACZEK_PROG=75%)

    Zwraca liste slownikow posortowana:
        1. Poisson przed ML (wieksza wiarygodnosc)
        2. Malejaco wg maksymalnej szansy typu
    """
    dzisiaj = datetime.now().date()
    granica = dzisiaj + timedelta(days=PEWNIACZEK_DNI)

    # Slownik deduplikacji: klucz "gosp|gosc|data" → wpis Pewniaczka
    # Poisson nadpisuje ML dla tego samego meczu.
    wyniki: dict = {}

    # Cache Dom/Wyjazd wspolny dla wszystkich meczow – nie liczymy dwa razy
    dw_cache: dict = {}

    # ── WARSTWA 1: Bzzoiro ML – wszystkie ligi, 0 req ──────────
    # Bzzoiro zwraca ~400+ meczow z 22 lig w jednym zapytaniu.
    # Uzywamy go jako bazy danych ML dla cross-walidacji i lig bez historii.
    bzz_indeks: dict = {}   # klucz "gosp|gosc|data" → event Bzzoiro

    if bzzoiro and getattr(bzzoiro, "_valid", False):
        console.print("[dim]🌐 Bzzoiro: pobieranie zdarzen tygodnia (wszystkie ligi)...[/dim]")
        try:
            bzz_lista = bzzoiro.predykcje_tygodnia()  # 1 req, 22 ligi, caly tydzien
            n_w_oknie = 0
            for ev in bzz_lista:
                g_b = str(ev.get("gosp","") or "").strip()
                a_b = str(ev.get("gosc","") or "").strip()
                d_b = str(ev.get("data","") or "")[:10]
                if not g_b or not a_b or not d_b:
                    continue
                # Filtruj tylko do zakresu tygodnia
                try:
                    if not (dzisiaj <= datetime.strptime(d_b, "%Y-%m-%d").date() <= granica):
                        continue
                except ValueError:
                    continue
                n_w_oknie += 1
                klucz = f"{g_b}|{a_b}|{d_b}"
                bzz_indeks[klucz] = ev
                # Buduj wstepna predykcje ML – moze byc nadpisana przez Poisson
                pred_ml = _ml_do_predykcji(ev.get("pred_ml"), ev.get("odds"))
                if not pred_ml:
                    continue
                typy = _typy_pewne(
                    pred_ml["p_wygrana"], pred_ml["p_remis"], pred_ml["p_przegrana"],
                    pred_ml["btts"], pred_ml["over25"], pred_ml["under25"],
                    g_b, a_b, prog
                )
                if not typy:
                    continue
                wyniki[klucz] = {
                    "data": d_b, "godzina": str(ev.get("godzina","–")),
                    "gospodarz": g_b, "goscie": a_b,
                    "liga": str(ev.get("liga","Bzzoiro")),
                    "typy": typy, "metoda": "ML",
                    "pred": pred_ml, "bzz_info": None,
                    "ikony": "", "klas": {"typ": "LIGA", "etykieta_pdf": "[LIGA]"},
                }
            console.print(f"[dim]   Bzzoiro: {n_w_oknie} meczow w przedziale tygodnia[/dim]")
        except Exception as e:
            console.print(f"[yellow]Bzzoiro blad: {e}[/yellow]")

    # ── WARSTWA 2: Biezaca liga – Poisson (0 req) ───────────────
    # Pelna analiza: H2H, Fortress, Dom/Wyjazd, Importance, Heurystyki.
    # Poisson nadpisuje ML z Warstwy 1 dla tych samych meczow.
    console.print(f"[dim]🔢 Poisson: biezaca liga ({nazwa_biezacej})...[/dim]")

    if df_nad_biezaca is not None and not df_nad_biezaca.empty:
        for _, mecz in df_nad_biezaca.iterrows():
            g = _s(mecz.get("gospodarz"));  a = _s(mecz.get("goscie"))
            if g == "-" or a == "-":
                continue
            d = str(mecz.get("data",""))[:10]
            try:
                if not (dzisiaj <= datetime.strptime(d, "%Y-%m-%d").date() <= granica):
                    continue
            except ValueError:
                continue

            stage = _s(mecz.get("stage"), "REGULAR_SEASON")
            dfull = _s(mecz.get("data_full"), d)
            flg   = mecz.get("first_leg_g")
            fla   = mecz.get("first_leg_a")
            godz  = _s(mecz.get("godzina"), "–")
            klucz = f"{g}|{a}|{d}"

            # Systemy analityczne
            imp_g = importance_idx.analiza(g); imp_a = importance_idx.analiza(a)
            hg    = heurystyka_eng.analiza(g, dfull)
            ha    = heurystyka_eng.analiza(a, dfull)
            hh_g  = h2h_sys.analiza(g, a); hh_a = h2h_sys.analiza(a, g)
            ft_g  = fortress_sys.analiza(g)
            klas  = klasyfikator.klasyfikuj(g, a, stage, dfull, flg, fla)

            # Dom/Wyjazd – cache wspolny, unikamy powtarzania obliczen
            if a not in dw_cache:
                dw_cache[a] = dw_sys.analiza(a)
            dw_a = dw_cache[a]

            # Jesli goscie to Podroznik: +10% lambda ataku na wyjezdzie
            hh_a2 = dict(hh_a)
            if dw_a.get("podroznik"):
                hh_a2["mnoznik_atak"] = hh_a2.get("mnoznik_atak", 1.0) * dw_a["bonus_wyjazd"]

            w = predict_match(
                g, a, df_wyk_biezaca,
                imp_g, imp_a, hg, ha, hh_g, hh_a2, ft_g,
                flg, fla, stage, klas,
            )
            if not w:
                continue  # za malo historii – pominięto

            pw, pr, pp = w["p_wygrana"], w["p_remis"], w["p_przegrana"]
            typy = _typy_pewne(pw, pr, pp, w["btts"], w["over25"], w["under25"],
                               g, a, prog)
            if not typy:
                continue

            # Cross-walidacja z Bzzoiro jesli mamy ML dla tego meczu
            bzz_info = None
            bzz_ev = bzz_indeks.get(klucz)
            if bzz_ev:
                cross = BzzoiroClient.porownaj_z_poisson(
                    pw, pr, pp, bzz_ev.get("pred_ml"))
                bzz_info = {"cross": cross, "odds": bzz_ev.get("odds")}

            # Zbierz ikony aktywnych czynnikow
            ikony = (hg.get("ikony","") + ha.get("ikony","") +
                     hh_g.get("ikona","") + hh_a.get("ikona","") +
                     ft_g.get("ikona","") + dw_a.get("ikona",""))

            # Nadpisz ML (Poisson > ML)
            wyniki[klucz] = {
                "data": d, "godzina": godz,
                "gospodarz": g, "goscie": a,
                "liga": nazwa_biezacej,
                "typy": typy, "metoda": "POISSON",
                "pred": w, "bzz_info": bzz_info,
                "ikony": ikony.strip(), "klas": klas,
            }

    # ── WARSTWA 3: Inne ligi FDB (opcjonalnie, ~N req) ───────────
    # Dla kazdej pozostalej ligi: pobieramy TYLKO nadchodzace (1 req/liga).
    # NIE pobieramy wynikow historycznych – za duze koszty reqow.
    # Predykcja mozliwa tylko z ML Bzzoiro (jesli mamy event w indeksie).
    if skanuj_inne_ligi and api_fdb:
        ligi_fdb = api_fdb.pobierz_ligi_free()
        inne = [l for l in ligi_fdb if l["nazwa"] != nazwa_biezacej]
        if inne:
            console.print(
                f"[dim]📋 Skanowanie {len(inne)} innych lig FDB (~{len(inne)} req)...[/dim]"
            )
            for liga in inne:
                try:
                    df_nad_l = api_fdb.nadchodzace(liga["kod"], 30)
                    time.sleep(SLEEP_LOOP)  # rate limit FDB: 10 req/min
                except Exception:
                    continue
                if df_nad_l is None or df_nad_l.empty:
                    continue
                for _, mecz in df_nad_l.iterrows():
                    g = _s(mecz.get("gospodarz")); a = _s(mecz.get("goscie"))
                    if g == "-" or a == "-":
                        continue
                    d = str(mecz.get("data",""))[:10]
                    try:
                        if not (dzisiaj <= datetime.strptime(d, "%Y-%m-%d").date() <= granica):
                            continue
                    except ValueError:
                        continue
                    klucz = f"{g}|{a}|{d}"
                    if klucz in wyniki:
                        continue  # juz mamy (Poisson lub ML) – nie nadpisuj

                    # Bez historii wynikow: liczymy tylko z ML Bzzoiro
                    bzz_ev = bzz_indeks.get(klucz)
                    if not bzz_ev:
                        continue  # brak ML i historii – nie mamy czym liczyc
                    pred_ml = _ml_do_predykcji(bzz_ev.get("pred_ml"), bzz_ev.get("odds"))
                    if not pred_ml:
                        continue
                    typy = _typy_pewne(
                        pred_ml["p_wygrana"], pred_ml["p_remis"], pred_ml["p_przegrana"],
                        pred_ml["btts"], pred_ml["over25"], pred_ml["under25"],
                        g, a, prog
                    )
                    if not typy:
                        continue
                    wyniki[klucz] = {
                        "data": d,
                        "godzina": _s(mecz.get("godzina"), "–"),
                        "gospodarz": g, "goscie": a,
                        "liga": liga["nazwa"],
                        "typy": typy, "metoda": "ML",
                        "pred": pred_ml, "bzz_info": None,
                        "ikony": "", "klas": {"typ": "LIGA", "etykieta_pdf": "[LIGA]"},
                    }

    # ── Sortowanie ──────────────────────────────────────────────
    # Priorytet 1: Poisson (bardziej dokladny) przed ML
    # Priorytet 2: malejaco wg najwyzszej szansy wsrod typow meczu
    lista = list(wyniki.values())
    lista.sort(key=lambda x: (
        0 if x["metoda"] == "POISSON" else 1,   # Poisson na gore
        -(max(v for _, v in x["typy"]) if x["typy"] else 0),
    ))
    return lista


# ── Wyswietlanie w konsoli ─────────────────────────────────────

def wyswietl_pewniaczki(pewniaczki: list, prog: float = PEWNIACZEK_PROG):
    """
    Wyswietla raport Pewniakow Tygodnia w konsoli Rich.

    Dla kazdego meczu pokazuje:
      - Numer rankingowy + nazwy druzyn + liga
      - Data, godzina, ikony czynnikow
      - Typowany wynik + lambdy (tylko Poisson)
      - Tabele typow bukmacherskich z ocena
      - Cross-walidacja ML Bzzoiro + kursy (jesli dostepne)

    Legenda metod:
      [P] – Poisson (pelna analiza z historia)
      [M] – ML CatBoost Bzzoiro (brak historii, szacunek)
    """
    if not pewniaczki:
        console.print(Panel(
            f"[yellow]Brak pewniakow >= {prog:.0f}% na nastepne {PEWNIACZEK_DNI} dni.[/yellow]\n"
            "[dim]Sprobuj obnizyc prog lub dodaj klucz Bzzoiro dla wiekszego zasieg.[/dim]",
            border_style="yellow", title="Pewniaczki Tygodnia"
        ))
        return

    n_p = sum(1 for x in pewniaczki if x["metoda"] == "POISSON")
    n_m = len(pewniaczki) - n_p
    ligi = sorted(set(x["liga"] for x in pewniaczki))

    console.print(Panel(
        f"[bold green]★ PEWNIACZKI: {len(pewniaczki)} meczow >= {prog:.0f}% ★[/bold green]\n"
        f"[dim]{datetime.now().strftime('%d.%m')} – "
        f"{(datetime.now()+timedelta(days=PEWNIACZEK_DNI)).strftime('%d.%m.%Y')}  "
        f"| Ligi: {len(ligi)} | [bold][P][/bold] Poisson:{n_p} [dim][M][/dim] ML:{n_m}[/dim]",
        border_style="green",
        title=f"[bold green]★ PEWNIACZKI TYGODNIA – FootStats {VERSION} ★[/bold green]",
        padding=(0, 2),
    ))
    console.print()

    for i, p in enumerate(pewniaczki, 1):
        kolor   = "green" if i <= 3 else ("yellow" if i <= 7 else "white")
        met_str = "[bold green][P][/bold green]" if p["metoda"] == "POISSON" else "[dim][M][/dim]"

        console.rule(
            f"[bold {kolor}]#{i}  {p['gospodarz']} vs {p['goscie']}[/bold {kolor}]  "
            f"{met_str}  [dim]{p['liga']}[/dim]"
        )
        console.print(
            f"  [dim]{p['data']} {p['godzina']}  {p.get('ikony','').strip()}[/dim]"
        )

        # Lambdy i typowany wynik – tylko gdy Poisson
        pred = p.get("pred", {})
        lam  = ""
        if p["metoda"] == "POISSON" and pred.get("lambda_g") not in (None, "–"):
            lam = f"  λG={pred['lambda_g']} λA={pred['lambda_a']}"
        wynik_g = pred.get("wynik_g","–"); wynik_a = pred.get("wynik_a","–")
        pewn    = pred.get("pewnosc","–")
        console.print(
            f"  Typ. wynik: [bold yellow]{wynik_g}:{wynik_a}[/bold yellow]{lam}  "
            f"Pewnosc: [bold]{pewn}%[/bold]"
        )

        # Tabela typow
        tt = Table(box=box.SIMPLE, show_header=True, header_style="bold green", pad_edge=False)
        tt.add_column("Typ",    style="bold white",  width=30)
        tt.add_column("Szansa", style="bold yellow", width=8, justify="right")
        tt.add_column("Ocena",  style="bold green",  width=12, justify="center")
        for tn, tv in p["typy"]:
            ocena = "★★★ PEWNY" if tv >= 90 else ("★★  BARDZO" if tv >= 80 else "★   DOBRY")
            tt.add_row(tn, f"{tv:.1f}%", ocena)
        console.print(tt)

        # Bzzoiro cross-walidacja i kursy
        if p.get("bzz_info"):
            cross = p["bzz_info"].get("cross", {})
            if cross.get("zgodnosc") is not None:
                ikona = "✅" if cross["zgodnosc"] else "⚠️"
                k = "green" if cross["zgodnosc"] else ("red" if cross.get("alert") else "yellow")
                console.print(f"  [{k}]{ikona} ML: {cross.get('opis','')[:80]}[/{k}]")
            odds = p["bzz_info"].get("odds")
            if isinstance(odds, dict):
                console.print(
                    f"  [dim]Kursy: 1={odds.get('home','–')}  "
                    f"X={odds.get('draw','–')}  2={odds.get('away','–')}[/dim]"
                )
        elif p.get("pred", {}).get("odds"):
            odds = p["pred"]["odds"]
            if isinstance(odds, dict):
                console.print(
                    f"  [dim]Kursy: 1={odds.get('home','–')}  "
                    f"X={odds.get('draw','–')}  2={odds.get('away','–')}[/dim]"
                )
        console.print()

    console.print(
        "[dim]Legenda: ★★★=90%+ | ★★=80-89% | ★=75-79% | "
        "[bold][P][/bold]=Poisson | [dim][M][/dim]=ML Bzzoiro | ✅ zgodne | ⚠️ roznica >20%[/dim]\n"
    )


# ── Eksport Pewniakow do PDF ───────────────────────────────────

def eksportuj_pdf_pewniaczki(
    pewniaczki: list,
    prog: float = PEWNIACZEK_PROG,
    sciezka: str = None,
) -> str:
    """
    Tworzy dedykowany PDF z raportem Pewniakow Tygodnia.

    Struktura dokumentu:
      Strona 1 – naglowek + tabela zbiorcza wszystkich Pewniakow
      Strona 2+ – szczegoly: kazdy mecz z typami, ML info, kursami

    Parametry:
        pewniaczki – lista z funkcji pewniaczki_tygodnia()
        prog       – prog pewnosci (tylko do naglowka)
        sciezka    – sciezka pliku PDF (None = auto)

    Zwraca sciezke zapisanego pliku PDF.
    """
    if not sciezka:
        sciezka = f"Pewniaczki_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"

    doc = SimpleDocTemplate(
        sciezka, pagesize=A4,
        rightMargin=1.5*cm, leftMargin=1.5*cm,
        topMargin=2*cm,     bottomMargin=2*cm,
    )
    F, FB = PDF_FONT, PDF_FONT_BOLD

    def st(name, **kw):
        return ParagraphStyle(name, fontName=F, **kw)

    # Style typograficzne
    s_tit = st("t",  fontSize=17, textColor=colors.HexColor("#1a5276"),
               alignment=TA_CENTER, spaceAfter=4)
    s_sub = st("s",  fontSize=8,  textColor=colors.grey,
               alignment=TA_CENTER, spaceAfter=8)
    s_h1  = st("h1", fontSize=12, textColor=colors.HexColor("#1a5276"),
               spaceBefore=10, spaceAfter=4)
    s_h2  = st("h2", fontSize=9,  textColor=colors.HexColor("#2980b9"),
               spaceBefore=5,  spaceAfter=2)
    s_bod = st("b",  fontSize=8,  spaceAfter=2)
    s_ml  = st("ml", fontSize=7,  textColor=colors.HexColor("#7f8c8d"),
               leftIndent=4,   spaceAfter=2)
    s_ok  = st("ok", fontSize=7,  textColor=colors.HexColor("#27ae60"), spaceAfter=1)
    s_war = st("wa", fontSize=7,  textColor=colors.HexColor("#e67e22"), spaceAfter=1)
    s_ft  = st("ft", fontSize=6,  textColor=colors.grey, alignment=TA_CENTER)

    note  = "" if FONT_OK else " [Brak czcionki – ogonki ASCII]"
    story = []

    # ── Statystyki naglowka ──────────────────────────────────────
    n_p   = sum(1 for x in pewniaczki if x["metoda"] == "POISSON")
    n_m   = len(pewniaczki) - n_p
    ligi  = sorted(set(x["liga"] for x in pewniaczki))

    story.append(Paragraph(_pdf(f"FootStats {VERSION}  |  Pewniaczki Tygodnia"), s_tit))
    story.append(Paragraph(_pdf(
        f"Okres: {datetime.now().strftime('%d.%m.%Y')} – "
        f"{(datetime.now() + timedelta(days=PEWNIACZEK_DNI)).strftime('%d.%m.%Y')}  "
        f"|  Min. szansa: {prog:.0f}%  "
        f"|  Meczow: {len(pewniaczki)}  "
        f"|  Ligi: {len(ligi)}  "
        f"|  [P]={n_p} [M]={n_m}{note}"
    ), s_sub))
    story.append(HRFlowable(width="100%", thickness=2,
                            color=colors.HexColor("#1a5276"), spaceAfter=6))
    story.append(Paragraph(_pdf(
        "[P]=Poisson (historia meczow + H2H)  "
        "[M]=ML CatBoost Bzzoiro  "
        "★★★=90%+  ★★=80-89%  ★=75-79%"
    ), s_ml))
    story.append(Spacer(1, 0.3*cm))

    # ── Tabela zbiorcza ──────────────────────────────────────────
    story.append(Paragraph(_pdf("Przeglad Pewniakow"), s_h1))
    nagl = [_pdf(x) for x in ["Nr","Data/Godz","Mecz","Liga","Wyn.","Najlepszy typ","Szan.","M"]]
    rows = [nagl]
    for idx, p in enumerate(pewniaczki, 1):
        best_typ, best_val = max(p["typy"], key=lambda x: x[1]) if p["typy"] else ("–", 0)
        pred = p.get("pred", {})
        rows.append([
            _pdf(str(idx)),
            _pdf(f"{p['data']}\n{p['godzina'][:5]}"),
            _pdf(f"{p['gospodarz'][:12]}\nvs {p['goscie'][:12]}"),
            _pdf(p["liga"][:14]),
            _pdf(f"{pred.get('wynik_g','?')}:{pred.get('wynik_a','?')}"),
            _pdf(best_typ[:24]),
            _pdf(f"{best_val:.1f}%"),
            _pdf("P" if p["metoda"]=="POISSON" else "M"),
        ])

    ts = TableStyle([
        ("BACKGROUND",     (0,0),(-1,0),  colors.HexColor("#1a5276")),
        ("TEXTCOLOR",      (0,0),(-1,0),  colors.white),
        ("FONTNAME",       (0,0),(-1,-1), F), ("FONTNAME",(0,0),(-1,0), FB),
        ("FONTSIZE",       (0,0),(-1,-1), 7),
        ("ALIGN",          (0,0),(-1,-1), "CENTER"),
        ("ALIGN",          (2,1),(3,-1),  "LEFT"),
        ("ROWBACKGROUNDS", (0,1),(-1,-1), [colors.white, colors.HexColor("#eaf4fb")]),
        ("GRID",           (0,0),(-1,-1), 0.4, colors.grey),
        ("TOPPADDING",     (0,0),(-1,-1), 2), ("BOTTOMPADDING",(0,0),(-1,-1), 2),
        ("VALIGN",         (0,0),(-1,-1), "MIDDLE"),
    ])
    widths = [0.6*cm, 1.6*cm, 3.5*cm, 2.5*cm, 1.2*cm, 5.0*cm, 1.4*cm, 0.6*cm]
    story.append(RLTable(rows, colWidths=widths, repeatRows=1, style=ts))
    story.append(Spacer(1, 0.4*cm))

    # ── Szczegoly meczow ─────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph(_pdf("Szczegolowa Analiza Pewniakow"), s_h1))

    for i, p in enumerate(pewniaczki, 1):
        pred   = p.get("pred", {})
        g, a   = p["gospodarz"], p["goscie"]
        met    = "[P] Poisson" if p["metoda"] == "POISSON" else "[M] ML Bzzoiro"

        story.append(HRFlowable(width="100%", thickness=0.7,
                                color=colors.HexColor("#aed6f1"), spaceAfter=3))
        story.append(Paragraph(_pdf(
            f"#{i}  {g} vs {a}  |  {p['liga']}  |  {p['data']} {p['godzina']}  |  {met}"
        ), s_h2))

        # Typ. wynik i parametry
        lam = ""
        if p["metoda"] == "POISSON" and pred.get("lambda_g") not in (None,"–"):
            lam = f"  λG={pred['lambda_g']} λA={pred['lambda_a']}"
        story.append(Paragraph(_pdf(
            f"Typowany wynik: {pred.get('wynik_g','?')}:{pred.get('wynik_a','?')}{lam}  "
            f"|  Pewnosc modelu: {pred.get('pewnosc','–')}%"
        ), s_bod))

        # Tabela typow bukmacherskich
        tnagl = [[_pdf("Typ"), _pdf("Szansa"), _pdf("Ocena")]]
        for tn, tv in p["typy"]:
            ocena = "★★★" if tv >= 90 else ("★★" if tv >= 80 else "★")
            tnagl.append([_pdf(tn), _pdf(f"{tv:.1f}%"), _pdf(ocena)])
        tst = TableStyle([
            ("BACKGROUND",    (0,0),(-1,0),  colors.HexColor("#2980b9")),
            ("TEXTCOLOR",     (0,0),(-1,0),  colors.white),
            ("FONTNAME",      (0,0),(-1,-1), F), ("FONTNAME",(0,0),(-1,0), FB),
            ("FONTSIZE",      (0,0),(-1,-1), 7),
            ("ALIGN",         (0,0),(-1,-1), "CENTER"), ("ALIGN",(0,1),(0,-1),"LEFT"),
            ("ROWBACKGROUNDS",(0,1),(-1,-1), [colors.white, colors.HexColor("#d6eaf8")]),
            ("GRID",          (0,0),(-1,-1), 0.3, colors.grey),
            ("TOPPADDING",    (0,0),(-1,-1), 1), ("BOTTOMPADDING",(0,0),(-1,-1), 1),
        ])
        story.append(RLTable(tnagl, colWidths=[5.5*cm,2.0*cm,1.5*cm], style=tst))

        # Ikony czynnikow (tylko Poisson)
        if p.get("ikony"):
            story.append(Paragraph(_pdf(f"Czynniki: {p['ikony']}"), s_ml))

        # Cross-walidacja ML + kursy
        if p.get("bzz_info"):
            cross = p["bzz_info"].get("cross", {})
            if cross.get("opis"):
                sty = s_ok if cross.get("zgodnosc") else s_war
                pfx = "OK " if cross.get("zgodnosc") else "ROZN. "
                story.append(Paragraph(_pdf(pfx + cross["opis"][:100]), sty))
            odds = p["bzz_info"].get("odds")
            if isinstance(odds, dict):
                story.append(Paragraph(_pdf(
                    f"Kursy: 1={odds.get('home','–')}  "
                    f"X={odds.get('draw','–')}  2={odds.get('away','–')}"
                ), s_ml))
        elif isinstance(pred.get("odds"), dict):
            odds = pred["odds"]
            story.append(Paragraph(_pdf(
                f"Kursy: 1={odds.get('home','–')}  "
                f"X={odds.get('draw','–')}  2={odds.get('away','–')}"
            ), s_ml))

        story.append(Spacer(1, 0.25*cm))

    # Stopka
    story.append(Spacer(1, 0.4*cm))
    story.append(HRFlowable(width="100%", thickness=0.8, color=colors.grey))
    story.append(Paragraph(_pdf(
        f"FootStats {VERSION}  |  Wygenerowano: "
        f"{datetime.now().strftime('%d.%m.%Y %H:%M')}  |  "
        "TYLKO DO UZYTKU ANALITYCZNEGO – nie stanowi porady inwestycyjnej"
    ), s_ft))

    doc.build(story)
    return sciezka


# ================================================================
#  MODUL 14 - ANALIZA KOLEJKI
# ================================================================

def analiza_kolejki(
    df_nad: pd.DataFrame,
    df_wyk: pd.DataFrame,
    importance_idx: ImportanceIndex,
    heurystyka_eng: HeurystaZmeczeniaRotacji,
    h2h_sys: AnalizaH2H,
    fortress_sys: HomeFortress,
    klasyfikator: "KlasyfikatorMeczu" = None,
) -> list:
    """
    Analizuje wszystkie nadchodzace mecze z pelnym zestawem czynnikow v2.6:
      - Stage Recognition: [LIGA] / [PUCHAR 1/2] / [REWANZ (X:Y)] / [FINAL]
      - KlasyfikatorMeczu: wykrywanie rewanzu z historii 14 dni
      - Importance Index 2.0
      - Heurystyka zmeczenia/rotacji
      - AnalizaH2H (Patent + Zemsta, filtr 24 mies.)
      - HomeFortress
      - Confidence Meter
    Pauza SLEEP_KOLEJKA sekund miedzy meczami (plan FREE: 10 req/min).
    """
    if df_nad is None or df_nad.empty:
        console.print("[yellow]Brak meczow (TBD pominiete).[/yellow]")
        return []

    wyniki = []
    n      = len(df_nad)

    t = Table(
        title=f"[bold green]Analiza {n} Nadchodzacych Meczow – FootStats {VERSION}[/bold green]",
        box=box.SIMPLE_HEAVY, border_style="green", header_style="bold green",
        show_lines=True
    )
    t.add_column("Data",       style="dim",          justify="center", width=11)
    t.add_column("Gospodarz",  style="bold white",   justify="right",  width=14)
    t.add_column("Goscie",     style="bold white",   justify="left",   width=14)
    t.add_column("Typ.wyn.",   style="bold yellow",  justify="center", width=7)
    t.add_column("1",          style="green",        justify="center", width=5)
    t.add_column("X",          style="yellow",       justify="center", width=5)
    t.add_column("2",          style="red",          justify="center", width=5)
    t.add_column("BTTS",       style="cyan",         justify="center", width=8)
    t.add_column("Ov2.5",      style="magenta",      justify="center", width=6)
    t.add_column("Czynniki",   style="bold",         justify="left",   width=16)
    t.add_column("Informacje", style="bold",         justify="left",   width=16)
    t.add_column("Pewnosc",    style="bold cyan",    justify="center", width=8)

    with Progress(
        SpinnerColumn(style="green"), TextColumn("{task.description}"),
        BarColumn(bar_width=16, complete_style="green"),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(), console=console, transient=True
    ) as prog:
        task = prog.add_task("Start...", total=n)

        for i, (_, mecz) in enumerate(df_nad.iterrows()):
            data_str  = _s(mecz.get("data"))
            data_full = _s(mecz.get("data_full"), mecz.get("data", "-"))
            g         = _s(mecz.get("gospodarz"))
            a         = _s(mecz.get("goscie"))
            stage     = _s(mecz.get("stage"), "REGULAR_SEASON")
            flg       = mecz.get("first_leg_g")
            fla       = mecz.get("first_leg_a")

            prog.update(task, advance=1, description=f"[{i+1}/{n}] {g} vs {a}...")

            if g == "-" or a == "-":
                t.add_row(data_str, g, a, "[dim]TBD[/dim]",
                          "-","-","-","-","-","[dim]-[/dim]","[dim]-[/dim]","–")
                continue

            # ── v2.6 Klasyfikacja meczu ──────────────────────────────
            klas = (klasyfikator.klasyfikuj(g, a, stage, data_full, flg, fla)
                    if klasyfikator else
                    {"typ": "LIGA", "rewanz": False, "single": False,
                     "agg_g": None, "agg_a": None,
                     "etykieta": "[dim][LIGA][/dim]",
                     "etykieta_pdf": "[LIGA]", "opis": ""})

            # ── Systemy analityczne ──────────────────────────────────
            # LIGA: nie sprawdzamy dodatkowych danych H2H-stage (brak sensu)
            imp_g  = importance_idx.analiza(g)
            imp_a  = importance_idx.analiza(a)
            heur_g = heurystyka_eng.analiza(g, data_full)
            heur_a = heurystyka_eng.analiza(a, data_full)
            # H2H z sleep – ochrona limitu 10 req/min
            h2h_g  = h2h_sys.analiza(g, a)
            time.sleep(SLEEP_KOLEJKA)
            h2h_a  = h2h_sys.analiza(a, g)
            fort_g = fortress_sys.analiza(g)

            wynik = predict_match(
                g, a, df_wyk,
                imp_g, imp_a,
                heur_g, heur_a,
                h2h_g, h2h_a,
                fort_g,
                flg, fla, stage,
                klas,
            )

            # Kolumna ikon czynnikow (bez etykiety stage – to trafia do Informacje)
            ikony = (
                heur_g.get("ikony","") +
                heur_a.get("ikony","") +
                h2h_g.get("ikona","") +
                h2h_a.get("ikona","") +
                fort_g.get("ikona","")
            )
            czynniki    = (ikony + " " + imp_g["label_plain"][:9]).strip() or "–"
            # Etykieta v2.6 – typ meczu (z kolorem Rich)
            etykieta_ui = klas.get("etykieta", "[dim][LIGA][/dim]")

            if wynik:
                wyniki.append({"mecz": mecz, "predykcja": wynik, "klasyfikacja": klas})
                pw, pr, pp = wynik["p_wygrana"], wynik["p_remis"], wynik["p_przegrana"]
                bt, o25    = wynik["btts"], wynik["over25"]
                typ        = f"{wynik['wynik_g']}:{wynik['wynik_a']}"
                pewnosc    = wynik.get("pewnosc", 20)
                kf = "bold green" if pw>max(pr,pp) else("bold red" if pp>max(pw,pr) else "bold yellow")

                # Kolor kolumny Pewnosc
                if pewnosc >= 80:   kp = "bold green"
                elif pewnosc >= 55: kp = "bold yellow"
                else:               kp = "dim red"

                t.add_row(
                    data_str, g, a,
                    f"[{kf}]{typ}[/{kf}]",
                    f"{pw:.0f}%", f"{pr:.0f}%", f"{pp:.0f}%",
                    f"{'TAK' if bt>=50 else 'NIE'} {bt:.0f}%",
                    f"{'OV' if o25>=50 else 'UN'} {o25:.0f}%",
                    czynniki,
                    etykieta_ui,
                    f"[{kp}]{pewnosc}%[/{kp}]",
                )
            else:
                t.add_row(data_str, g, a, "[dim]brak danych[/dim]",
                          "-","-","-","-","-","[dim]-[/dim]", etykieta_ui, "–")

            # Sleep miedzy meczami
            if i < n - 1:
                time.sleep(SLEEP_KOLEJKA)

    console.print(t)
    console.print(
        "\n[dim]Etykiety: [LIGA] mecz ligowy | [PUCHAR 1/2] pierwsza noga | "
        "[REWANZ (X:Y)] rewanz z wynikiem 1. meczu | [FINAL] mecz finalny/bez rewanzu[/dim]\n"
        "[dim]Czynniki: 🔄 Rotacja/CL | 😫 Zmeczenie <72h | ⚔️ Zemsta H2H | 🏅 Patent H2H | "
        "🏰 Twierdza | 🏆👑 High Stakes | 🆘 Spadek | 🏖️ Wakacje[/dim]\n"
        "[dim]Pewnosc: zielony >=80% | zolty 55-79% | czerwony <55% (mniej danych H2H)[/dim]\n"
    )
    return wyniki


# ================================================================
#  MODUL 15 - EKSPORT PDF
# ================================================================

def eksportuj_pdf(wyniki_kolejki: list, nazwa_ligi: str,
                  df_tabela: pd.DataFrame = None, sciezka: str = None) -> str:
    if not sciezka:
        sciezka = f"FootStats_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"

    doc = SimpleDocTemplate(sciezka, pagesize=A4,
                             rightMargin=1.5*cm, leftMargin=1.5*cm,
                             topMargin=2*cm, bottomMargin=2*cm)
    F, FB = PDF_FONT, PDF_FONT_BOLD

    def st(name, **kw):
        return ParagraphStyle(name, fontName=F, **kw)

    s_tit = st("t",  fontSize=18, textColor=colors.HexColor("#1a5276"), alignment=TA_CENTER, spaceAfter=4)
    s_sub = st("s",  fontSize=8,  textColor=colors.grey, alignment=TA_CENTER, spaceAfter=8)
    s_h1  = st("h1", fontSize=13, textColor=colors.HexColor("#1a5276"), spaceBefore=10, spaceAfter=5)
    s_h2  = st("h2", fontSize=10, textColor=colors.HexColor("#2980b9"), spaceBefore=6,  spaceAfter=3)
    s_bod = st("b",  fontSize=8,  spaceAfter=2)
    s_kom = st("k",  fontSize=8,  textColor=colors.HexColor("#2c3e50"),
               backColor=colors.HexColor("#eaf4fb"), alignment=TA_JUSTIFY,
               leftIndent=6, rightIndent=6, spaceBefore=3, spaceAfter=4)
    s_ok  = st("ok", fontSize=8,  textColor=colors.HexColor("#27ae60"), spaceAfter=2)
    s_dob = st("d",  fontSize=8,  textColor=colors.HexColor("#e67e22"), spaceAfter=2)

    note = "" if FONT_OK else " [UWAGA: Brak DejaVuSans.ttf - ogonki zastapione ASCII.]"
    story = []

    story.append(Paragraph(_pdf(f"FootStats {VERSION}  |  Raport Predykcji"), s_tit))
    story.append(Paragraph(_pdf(
        f"Liga: {nazwa_ligi}  |  {datetime.now().strftime('%d.%m.%Y %H:%M')}  |  "
        f"Model: Poisson + Importance + Stage Recognition + Rewanz Vabank + H2H + Fortress{note}"
    ), s_sub))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#1a5276"), spaceAfter=8))

    # Tabela zbiorcza
    story.append(Paragraph(_pdf("Przeglad Kolejki"), s_h1))
    nagl  = [_pdf(x) for x in ["Data","Gospodarz","Goscie","Typ","1%","X%","2%","BTTS","Ov2.5","Czynniki","Inf."]]
    dane_t = [nagl]
    for wpis in wyniki_kolejki:
        m, w = wpis["mecz"], wpis["predykcja"]
        klas = wpis.get("klasyfikacja", {})
        ikony = (w.get("heur_g",{}).get("ikony","") + w.get("heur_a",{}).get("ikony","") +
                 w.get("zemsta_g",{}).get("ikona","") + w.get("zemsta_a",{}).get("ikona",""))
        cz  = _pdf((ikony + " " + w.get("imp_g",{}).get("label_plain",""))[:14].strip())
        inf = _pdf(klas.get("etykieta_pdf", "[LIGA]")[:12])
        dane_t.append([
            _pdf(m.get("data","-")),
            _pdf(str(m.get("gospodarz","-"))[:13]),
            _pdf(str(m.get("goscie","-"))[:13]),
            _pdf(f"{w['wynik_g']}:{w['wynik_a']}"),
            _pdf(f"{w['p_wygrana']:.0f}"),
            _pdf(f"{w['p_remis']:.0f}"),
            _pdf(f"{w['p_przegrana']:.0f}"),
            _pdf(f"{'T' if w['btts']>=50 else 'N'} {w['btts']:.0f}%"),
            _pdf(f"{'OV' if w['over25']>=50 else 'UN'} {w['over25']:.0f}%"),
            cz, inf,
        ])
    ts_styl = TableStyle([
        ("BACKGROUND",     (0,0),(-1,0),  colors.HexColor("#1a5276")),
        ("TEXTCOLOR",      (0,0),(-1,0),  colors.white),
        ("FONTNAME",       (0,0),(-1,-1), F), ("FONTNAME",(0,0),(-1,0), FB),
        ("FONTSIZE",       (0,0),(-1,-1), 7),
        ("ALIGN",          (0,0),(-1,-1), "CENTER"),
        ("ROWBACKGROUNDS", (0,1),(-1,-1), [colors.white, colors.HexColor("#eaf4fb")]),
        ("GRID",           (0,0),(-1,-1), 0.4, colors.grey),
        ("TOPPADDING",     (0,0),(-1,-1), 2), ("BOTTOMPADDING",(0,0),(-1,-1), 2),
    ])
    widths = [1.8*cm,2.2*cm,2.2*cm,1.2*cm,0.9*cm,0.9*cm,0.9*cm,1.6*cm,1.6*cm,1.8*cm,1.6*cm]
    story.append(RLTable(dane_t, colWidths=widths, repeatRows=1, style=ts_styl))
    story.append(Spacer(1, 0.4*cm))

    # Szczegoly
    story.append(PageBreak())
    story.append(Paragraph(_pdf("Szczegolowa Analiza Meczow"), s_h1))
    for i, wpis in enumerate(wyniki_kolejki):
        m, w = wpis["mecz"], wpis["predykcja"]
        g, a = w["gospodarz"], w["gosc"]
        blok = []
        blok.append(HRFlowable(width="100%", thickness=0.8,
                                color=colors.HexColor("#aed6f1"), spaceAfter=4))
        klas_pdf = wpis.get("klasyfikacja", {})
        etykieta_pdf = klas_pdf.get("etykieta_pdf", "")
        blok.append(Paragraph(_pdf(
            f"{_s(m.get('data','-'))}  |  {g}  vs  {a}"
            + (f"  {etykieta_pdf}" if etykieta_pdf else "")
        ), s_h2))
        # Uwaga o dogrywce dla meczow final/single
        if w.get("single"):
            blok.append(Paragraph(_pdf(
                "UWAGA: Mecz bez rewanzu – mozliwa dogrywka/karne "
                f"(szansa remisu po 90 min: {w['p_remis']:.0f}%, "
                f"wzmocniona +{int((FINAL_REMIS_BOOST-1)*100)}% vs standard)."
            ), ParagraphStyle("warn", fontName=PDF_FONT_BOLD, fontSize=8,
                              textColor=colors.HexColor("#8e44ad"), spaceAfter=3)))
        dm = [
            [_pdf("Typ"), _pdf("Szansa"), _pdf("Typ"), _pdf("Szansa")],
            [_pdf("1 Gosp."),  _pdf(f"{w['p_wygrana']}%"), _pdf("BTTS TAK"),  _pdf(f"{w['btts']}%")],
            [_pdf("X Remis"),  _pdf(f"{w['p_remis']}%"),   _pdf("BTTS NIE"),  _pdf(f"{100-w['btts']:.1f}%")],
            [_pdf("2 Gosc"),   _pdf(f"{w['p_przegrana']}%"),_pdf("Over 2.5"), _pdf(f"{w['over25']}%")],
            [_pdf("1X"),       _pdf(f"{w['p_wygrana']+w['p_remis']:.1f}%"),
             _pdf("Under 2.5"),_pdf(f"{w['under25']}%")],
        ]
        dm_st = TableStyle([
            ("BACKGROUND",(0,0),(-1,0), colors.HexColor("#2980b9")),
            ("TEXTCOLOR", (0,0),(-1,0), colors.white),
            ("FONTNAME",  (0,0),(-1,-1), F), ("FONTNAME",(0,0),(-1,0), FB),
            ("FONTSIZE",  (0,0),(-1,-1), 7.5),
            ("ALIGN",     (0,0),(-1,-1), "CENTER"),
            ("GRID",      (0,0),(-1,-1), 0.4, colors.lightgrey),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#eaf4fb")]),
        ])
        blok.append(RLTable(dm, colWidths=[2.8*cm,2*cm,2.8*cm,2*cm], style=dm_st))
        blok.append(Spacer(1,0.1*cm))
        blok.append(Paragraph(_pdf("  |  ".join(f"{r}({p}%)" for r,p in w["top5"])), s_bod))
        blok.append(Paragraph(_pdf(
            f"Lambda G={w['lambda_g']}  A={w['lambda_a']}  "
            f"Forma G={w['forma_g']:.1f}  A={w['forma_a']:.1f}"), s_bod))
        for naz,sz,pew in typy_zaklady(w):
            blok.append(Paragraph(_pdf(f"{'*' if pew=='PEWNY' else '-'} {naz}: {sz} [{pew}]"),
                                   s_ok if pew=="PEWNY" else(s_dob if pew=="DOBRY" else s_bod)))
        blok.append(Paragraph(_pdf("Komentarz Analityka:"), s_bod))
        blok.append(Paragraph(_pdf(komentarz_analityka(w)), s_kom))
        for d,heur in [(g,w.get("heur_g",{})), (a,w.get("heur_a",{}))]:
            if heur.get("opis"): blok.append(Paragraph(_pdf(heur["opis"]), s_bod))
        for d,zem  in [(g,w.get("zemsta_g",{})), (a,w.get("zemsta_a",{}))]:
            if zem.get("opis"):  blok.append(Paragraph(_pdf(zem["opis"]),  s_bod))
        blok.append(Spacer(1,0.3*cm))
        story.append(KeepTogether(blok))
        if (i+1) % 4 == 0 and i+1 < len(wyniki_kolejki):
            story.append(PageBreak())

    # Tabela ligowa
    if df_tabela is not None and not df_tabela.empty:
        story.append(PageBreak())
        story.append(Paragraph(_pdf(f"Tabela: {nazwa_ligi}"), s_h1))
        nagl_t = [_pdf(x) for x in ["Poz.","Druzyna","M","W","R","P","Bramki","+/-","Pkt"]]
        dane_tb = [nagl_t]
        for _,r in df_tabela.iterrows():
            dane_tb.append([_pdf(str(r[k])) for k in ["Poz.","Druzyna","M","W","R","P","Bramki","+/-","Pkt"]])
        tb_st = TableStyle([
            ("BACKGROUND",(0,0),(-1,0), colors.HexColor("#1a5276")),
            ("TEXTCOLOR", (0,0),(-1,0), colors.white),
            ("FONTNAME",  (0,0),(-1,-1), F), ("FONTNAME",(0,0),(-1,0), FB),
            ("FONTSIZE",  (0,0),(-1,-1), 7.5),
            ("ALIGN",     (0,0),(-1,-1),"CENTER"), ("ALIGN",(1,0),(1,-1),"LEFT"),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#eaf4fb")]),
            ("GRID",      (0,0),(-1,-1), 0.4, colors.grey),
        ])
        n_dr = len(df_tabela)
        for ri in range(1, n_dr+1):
            if ri <= 4:       tb_st.add("BACKGROUND",(0,ri),(0,ri),colors.HexColor("#27ae60"))
            elif ri >= n_dr-1:tb_st.add("BACKGROUND",(0,ri),(0,ri),colors.HexColor("#c0392b"))
        story.append(RLTable(dane_tb,
            colWidths=[1.2*cm,4*cm,1*cm,1*cm,1*cm,1*cm,1.8*cm,1.2*cm,1.2*cm],
            repeatRows=1, style=tb_st))

    story.append(Spacer(1, 0.4*cm))
    story.append(HRFlowable(width="100%", thickness=0.8, color=colors.grey))
    story.append(Paragraph(_pdf(
        f"FootStats {VERSION}  |  Poisson + Stage Recognition + Rewanz Vabank + Importance +  "
        "Fatigue/Rotation + H2H + Fortress + Two-Leg  |  "
        "Dane: football-data.org  |  TYLKO DO UZYTKU ANALITYCZNEGO"
    ), ParagraphStyle("ft", fontName=F, fontSize=6, textColor=colors.grey, alignment=TA_CENTER)))

    doc.build(story)
    return sciezka


# ================================================================
#  MODUL 16 - INTERFEJS
# ================================================================

def wyswietl_naglowek():
    console.clear()
    t = Text(justify="center")
    t.append(f"\n  >>> FootStats {VERSION} <<<  \n", style="bold white on blue")
    t.append("\n  Poisson | 3 API | Stage Recognition | Pewniaczki | Dom/Wyjazd | PDF  \n", style="dim")
    console.print(Panel(t, border_style="blue"))
    font_info = (
        "[dim green]  Czcionka DejaVu: OK (polskie znaki w PDF)  [/dim green]"
        if FONT_OK else
        "[dim yellow]  Brak DejaVuSans.ttf - ogonki w PDF beda transliterowane  [/dim yellow]"
    )
    console.print(font_info)
    console.print()

def wyswietl_menu_lig(api: APIClient) -> tuple:
    """Dynamiczne menu: lista lig z API /v4/competitions (TIER_ONE)."""
    console.print("[dim]Pobieram liste dostepnych lig z API...[/dim]")
    ligi = api.pobierz_ligi_free()

    t = Table(
        title=f"[bold blue]Dostepne Ligi  [dim]({len(ligi)} rozgrywek - plan FREE)[/dim][/bold blue]",
        box=box.ROUNDED, border_style="blue", show_lines=True
    )
    t.add_column("Nr",   style="bold cyan",  justify="center", width=4)
    t.add_column("Liga", style="bold white", width=38)
    t.add_column("Kraj", style="dim",        justify="center", width=14)
    t.add_column("Kod",  style="dim cyan",   justify="center", width=5)
    for i, liga in enumerate(ligi, start=1):
        t.add_row(str(i), liga["nazwa"], liga["kraj"], liga["kod"])
    console.print(t)
    console.print("[dim yellow]  INFO: Ekstraklasa (Polska) dostepna tylko w planach platnych.[/dim yellow]\n")

    while True:
        wybor_str = Prompt.ask(f"[bold yellow]Numer ligi (1-{len(ligi)})[/bold yellow]", default="1")
        try:
            idx = int(wybor_str)
            if 1 <= idx <= len(ligi):
                liga = ligi[idx-1]
                console.print(f"[dim]Wybrano: [bold]{liga['nazwa']}[/bold] "
                               f"(kod: [cyan]{liga['kod']}[/cyan])[/dim]")
                return liga["kod"], liga["nazwa"], liga["druzyny"]
        except (ValueError, IndexError):
            pass
        console.print(f"[red]Wpisz liczbe 1-{len(ligi)}.[/red]")

def wyswietl_tabele(df: pd.DataFrame, nazwa: str, importance: ImportanceIndex):
    t = Table(title=f"[bold blue]Tabela: {nazwa}[/bold blue]",
              box=box.SIMPLE_HEAVY, border_style="bright_black",
              show_lines=False, header_style="bold cyan")
    for kol, styl, uzas in [
        ("Poz.","dim","center"), ("Druzyna","bold white","left"),
        ("M","dim","center"), ("W","green","center"), ("R","yellow","center"),
        ("P","red","center"), ("Bramki","cyan","center"), ("+/-","magenta","center"),
        ("Pkt","bold yellow","center"), ("Motywacja","bold","left"),
    ]:
        t.add_column(kol, style=styl, justify=uzas)
    n = len(df)
    for _, w in df.iterrows():
        poz = w["Poz."]
        if poz==1:     s = "bold yellow"
        elif poz<=4:   s = "bold green"
        elif poz>=n-2: s = "red"
        else:          s = "white"
        imp = importance.analiza(str(w["Druzyna"]))
        t.add_row(
            f"[{s}]{poz}[/{s}]", str(w["Druzyna"]),
            str(w["M"]), str(w["W"]), str(w["R"]), str(w["P"]),
            str(w["Bramki"]), str(w["+/-"]),
            f"[bold]{w['Pkt']}[/bold]",
            imp["label"],
        )
    console.print(t)

def wyswietl_wyniki(df: pd.DataFrame, limit: int = 10):
    t = Table(title=f"[bold blue]Ostatnie {limit} Wynikow[/bold blue]",
              box=box.MINIMAL_DOUBLE_HEAD, border_style="bright_black", header_style="bold cyan")
    t.add_column("Data",  style="dim",        justify="center")
    t.add_column("Gosp.", style="bold white",  justify="right")
    t.add_column("Wyn.",  style="bold yellow", justify="center")
    t.add_column("Gosc",  style="bold white",  justify="left")
    for _, w in df.tail(limit).iloc[::-1].iterrows():
        gg, ga = w["gole_g"], w["gole_a"]
        if gg>ga:   kg,ka = "bold green","dim red"
        elif gg<ga: kg,ka = "dim red","bold green"
        else:       kg=ka = "yellow"
        t.add_row(_s(w["data"]), f"[{kg}]{w['gospodarz']}[/{kg}]",
                  f"{gg}-{ga}", f"[{ka}]{w['goscie']}[/{ka}]")
    console.print(t)

def wyswietl_predykcje(wynik: dict):
    g,a      = wynik["gospodarz"], wynik["gosc"]
    pw,pr,pp = wynik["p_wygrana"], wynik["p_remis"], wynik["p_przegrana"]
    bt,o25   = wynik["btts"], wynik["over25"]
    pewnosc  = wynik.get("pewnosc", 20)
    klas     = wynik.get("klasyfikacja", {})

    # Zbierz wszystkie aktywne ikony czynnikow
    ikony = ""
    for k in ["heur_g","heur_a"]:   ikony += wynik.get(k,{}).get("ikony","")
    for k in ["h2h_g","h2h_a"]:     ikony += wynik.get(k,{}).get("ikona","")
    fort_ikona = wynik.get("fortress_g",{}).get("ikona","")
    if fort_ikona: ikony += fort_ikona

    nt = Text(justify="center")
    nt.append(f"\n  {g}  ", style="bold white")
    nt.append(f"  {wynik['wynik_g']} : {wynik['wynik_a']}  ", style="bold yellow on blue")
    nt.append(f"  {a}  \n", style="bold white")
    # v2.6 – etykieta meczu
    typ_meczu = klas.get("typ", "LIGA")
    if typ_meczu == "REWANZ":
        ag, aa = klas.get("agg_g","?"), klas.get("agg_a","?")
        nt.append(f"\n  [REWANZ – wynik 1. meczu: {ag}:{aa}]  \n", style="bold cyan")
    elif typ_meczu == "FINAL":
        nt.append(f"\n  [FINAL / MECZ BEZ REWANZU]  \n", style="bold magenta")
    elif typ_meczu == "PUCHAR_1":
        nt.append("\n  [PUCHAR 1/2 – pierwsza noga]  \n", style="bold yellow")
    elif wynik.get("knockout"):
        nt.append("\n  [Faza Pucharowa]  \n", style="bold yellow")
    # Uwaga o dogrywce
    if wynik.get("single"):
        nt.append(f"\n  ⚠️  Mozliwa dogrywka/karne (remis {pr:.0f}%)  \n", style="bold magenta")
    if ikony.strip():
        nt.append(f"\n  Czynniki v2.6: {ikony.strip()}  \n", style="bold cyan")
    if pewnosc >= 80:   kp = "bold green"
    elif pewnosc >= 55: kp = "bold yellow"
    else:               kp = "bold red"
    nt.append(f"\n  Pewnosc modelu: [{kp}]{pewnosc}%[/{kp}]  \n")
    nt.append("\n  Najbardziej prawdopodobny wynik  \n", style="dim italic")
    console.print(Panel(nt, border_style="blue", padding=(0,4)))
    console.print()

    # Pasek szans 1 X 2
    W  = 50
    sg = max(1,int(pw/100*W)); sr = max(1,int(pr/100*W)); sa = max(1,W-sg-sr)
    pasek = Text()
    pasek.append("[" + "="*sg, style="bold green")
    pasek.append("|" + "="*sr + "|", style="bold yellow")
    pasek.append("="*sa + "]", style="bold red")
    console.print(Align.center(pasek))
    console.print(Align.center(Text(
        f"  {g[:14]:>14} {pw:5.1f}%  |  X {pr:4.1f}%  |  {pp:5.1f}% {a[:14]:<14}  ", style="dim")))
    console.print()

    # Tabela wskaznikow Poissona + wszystkie czynniki v2.5
    h2h_g  = wynik.get("h2h_g",{})
    h2h_a  = wynik.get("h2h_a",{})
    fort_g = wynik.get("fortress_g",{})

    ts = Table(title="[bold cyan]Analiza Poissona + Czynniki v2.5[/bold cyan]",
               box=box.ROUNDED, border_style="cyan", show_header=False)
    ts.add_column("O", style="dim",        justify="right",  width=28)
    ts.add_column("W", style="bold white", justify="center", width=16)
    for lbl, val in [
        ("Lambda G (ocz. gole)",    f"[green]{wynik['lambda_g']}[/green]"),
        ("Lambda A (ocz. gole)",    f"[red]{wynik['lambda_a']}[/red]"),
        ("Forma G (pkt/mecz)",      str(wynik["forma_g"])),
        ("Forma A (pkt/mecz)",      str(wynik["forma_a"])),
        ("─"*28,                    "─"*16),
        (f"1 – Wygrana {g[:12]}",   f"[bold green]{pw}%[/bold green]"),
        ("X – Remis",               f"[bold yellow]{pr}%[/bold yellow]"),
        (f"2 – Wygrana {a[:12]}",   f"[bold red]{pp}%[/bold red]"),
        ("─"*28,                    "─"*16),
        ("BTTS",                    f"[cyan]{'TAK' if bt>=50 else 'NIE'} {bt}%[/cyan]"),
        ("Over 2.5",                f"[magenta]{'OV' if o25>=50 else 'UN'} {o25}%[/magenta]"),
        ("Under 2.5",               f"[magenta]{wynik['under25']}%[/magenta]"),
        ("─"*28,                    "─"*16),
        ("Motywacja G",             wynik.get("imp_g",{}).get("label","?")),
        ("Motywacja A",             wynik.get("imp_a",{}).get("label","?")),
        ("─"*28,                    "─"*16),
        ("Rotacja G",               "🔄 TAK" if wynik.get("heur_g",{}).get("rotacja") else "–"),
        ("Zmeczenie G",             "😫 TAK" if wynik.get("heur_g",{}).get("zmeczenie") else "–"),
        ("Rotacja A",               "🔄 TAK" if wynik.get("heur_a",{}).get("rotacja") else "–"),
        ("Zmeczenie A",             "😫 TAK" if wynik.get("heur_a",{}).get("zmeczenie") else "–"),
        ("─"*28,                    "─"*16),
        (f"H2H {g[:10]} (24 mies.)",
            f"🏅 Patent" if h2h_g.get("patent") else
            f"⚔️ Zemsta" if h2h_g.get("zemsta") else
            f"–  ({h2h_g.get('n_h2h',0)} meczow)"),
        (f"H2H {a[:10]} (24 mies.)",
            f"🏅 Patent" if h2h_a.get("patent") else
            f"⚔️ Zemsta" if h2h_a.get("zemsta") else
            f"–  ({h2h_a.get('n_h2h',0)} meczow)"),
        ("Home Fortress",           f"🏰 {fort_g.get('seria',0)} mecze" if fort_g.get("fortress") else "–"),
        ("─"*28,                    "─"*16),
        (f"Pewnosc modelu [{kp}]",  f"[{kp}]{pewnosc}%[/{kp}]"),
    ]:
        ts.add_row(lbl, val)

    tt = Table(title="[bold magenta]Top 5 Wynikow[/bold magenta]",
               box=box.ROUNDED, border_style="magenta", header_style="bold magenta")
    tt.add_column("Wynik",  justify="center", style="bold white", width=10)
    tt.add_column("Szansa", justify="center", style="cyan",       width=8)
    glowny = f"{wynik['wynik_g']}:{wynik['wynik_a']}"
    for ws, prob in wynik["top5"]:
        tt.add_row(f"{ws} ◀" if ws==glowny else ws, f"{prob}%")
    console.print(Columns([ts, tt], equal=False, expand=False))
    console.print()

    if wynik.get("knockout") and wynik.get("korekta_opis"):
        console.print(Panel(wynik["korekta_opis"], border_style="magenta",
                             title="[bold magenta]Logika Dwumeczu[/bold magenta]"))
        console.print()

    # H2H tabela historyczna (jesli dostepna)
    h2h_df = h2h_g.get("h2h_df")
    if h2h_df is not None and not h2h_df.empty:
        th = Table(title=f"[bold yellow]H2H: {g} vs {a}  (ostatnie 24 mies.)[/bold yellow]",
                   box=box.MINIMAL, border_style="yellow", header_style="bold yellow")
        th.add_column("Data",  style="dim",        justify="center", width=11)
        th.add_column("Gosp.", style="bold white",  justify="right",  width=14)
        th.add_column("Wynik", style="bold yellow", justify="center", width=7)
        th.add_column("Gosc",  style="bold white",  justify="left",   width=14)
        for _, r in h2h_df.iloc[::-1].iterrows():
            gg2, ga2 = int(r["gole_g"]), int(r["gole_a"])
            kg = "bold green" if gg2>ga2 else("yellow" if gg2==ga2 else "dim red")
            ka = "bold red"   if gg2>ga2 else("yellow" if gg2==ga2 else "bold green")
            th.add_row(_s(r["data"]), f"[{kg}]{r['gospodarz']}[/{kg}]",
                       f"{gg2}–{ga2}", f"[{ka}]{r['goscie']}[/{ka}]")
        console.print(th)
        console.print()

    ty = Table(title="[bold yellow]Typy Bukmacherskie[/bold yellow]",
               box=box.ROUNDED, border_style="yellow", header_style="bold yellow", show_lines=True)
    ty.add_column("Typ",    style="bold white", justify="left",   width=36)
    ty.add_column("Szansa", style="cyan",       justify="center", width=8)
    ty.add_column("Ocena",  style="bold",       justify="center", width=10)
    for naz,sz,pew in typy_zaklady(wynik):
        if pew=="PEWNY":   kol,ik = "bold green","★ PEWNY"
        elif pew=="DOBRY": kol,ik = "bold yellow","● DOBRY"
        else:              kol,ik = "dim red","○ SLABY"
        ty.add_row(naz, sz, f"[{kol}]{ik}[/{kol}]")
    console.print(ty)
    console.print(Panel(komentarz_analityka(wynik), border_style="dim cyan",
                         title="[dim cyan]Komentarz Analityka[/dim cyan]", padding=(0,2)))
    console.print()

def wybierz_druzyny(df_mecze: pd.DataFrame) -> tuple:
    druzyny = sorted(set(df_mecze["gospodarz"]) | set(df_mecze["goscie"]))
    t = Table(title="[bold blue]Druzyny[/bold blue]",
              box=box.MINIMAL, border_style="bright_black")
    for _ in range(3):
        t.add_column("Nr",      style="dim cyan",   justify="right",  width=4)
        t.add_column("Druzyna", style="bold white", justify="left",   width=16)
    for i in range(0, len(druzyny), 3):
        w = []
        for j in range(3):
            idx = i+j
            w.extend([str(idx+1), druzyny[idx]] if idx < len(druzyny) else ["",""])
        t.add_row(*w)
    console.print(t)
    while True:
        try:
            nr = int(Prompt.ask("\n[bold yellow]Nr GOSPODARZY[/bold yellow]"))
            if 1 <= nr <= len(druzyny): break
            console.print("[red]Zly numer.[/red]")
        except ValueError: console.print("[red]Podaj liczbe.[/red]")
    g = druzyny[nr-1]
    while True:
        try:
            nr = int(Prompt.ask(f"[bold yellow]Nr GOSCI[/bold yellow] (nie {g})"))
            if 1 <= nr <= len(druzyny) and druzyny[nr-1] != g: break
            console.print("[red]Zly numer lub ta sama druzyna.[/red]")
        except ValueError: console.print("[red]Podaj liczbe.[/red]")
    return g, druzyny[nr-1]


# ================================================================
#  MODUL 17 - POBIERANIE DANYCH
# ================================================================

def pobierz_dane(api: APIClient, kod: str, nazwa: str):
    df_tab = df_wyk = df_nad = None
    with Progress(SpinnerColumn(style="blue"), TextColumn("{task.description}"),
                  BarColumn(bar_width=20, complete_style="blue"),
                  console=console, transient=True) as prog:
        t1 = prog.add_task(f"Tabela {nazwa}...", total=1)
        df_tab = api.tabela(kod)
        prog.update(t1, completed=1)
        time.sleep(SLEEP_LOOP)

        t2 = prog.add_task("Wyniki (100 meczow)...", total=1)
        df_wyk = api.wyniki(kod, 100)
        prog.update(t2, completed=1)
        time.sleep(SLEEP_LOOP)

        t3 = prog.add_task("Nadchodzace mecze...", total=1)
        df_nad = api.nadchodzace(kod, 40)
        prog.update(t3, completed=1)

    return df_tab, df_wyk, df_nad


def wyswietl_menu_lig_v27(api: APIClient, af: "APIFootball | None" = None) -> tuple:
    """
    v2.7 Multi-source menu lig.
    Laczy ligi z football-data.org (FDB) i api-sports.io (AF).
    Zwraca (kod_fdb, nazwa, n_druzyn, api_id_af).
    api_id_af != None = liga pochodzi z API-Football.
    """
    console.print("[dim]Pobieram liste dostepnych lig...[/dim]")

    ligi_fdb = api.pobierz_ligi_free()
    ligi_af  = af.ligi_dodatkowe() if af else []

    # Polacz, unikajac duplikatow (to samo KOD)
    kody_fdb = {l["kod"] for l in ligi_fdb}
    ligi_af_extra = [l for l in ligi_af if l["kod"] not in kody_fdb]

    ligi_wszystkie = [{"src": "FDB", **l} for l in ligi_fdb]
    ligi_wszystkie += [{"src": "AF", **l} for l in ligi_af_extra]

    t = Table(
        title=f"[bold blue]Dostepne Ligi  [dim]({len(ligi_wszystkie)} rozgrywek)[/dim][/bold blue]",
        box=box.ROUNDED, border_style="blue", show_lines=False
    )
    t.add_column("Nr",     style="bold cyan",  justify="center", width=4)
    t.add_column("Liga",   style="bold white", width=36)
    t.add_column("Kraj",   style="dim",        justify="center", width=14)
    t.add_column("Kod",    style="dim cyan",   justify="center", width=5)
    t.add_column("Zrodlo", style="dim",        justify="center", width=10)

    for i, liga in enumerate(ligi_wszystkie, start=1):
        src  = liga["src"]
        kol  = "white" if src == "FDB" else "yellow"
        zr   = f"[{kol}]{src}[/{kol}]"
        t.add_row(str(i), liga["nazwa"], liga["kraj"], liga["kod"], zr)

    console.print(t)
    console.print(
        "[dim]FDB=football-data.org | [yellow]AF[/yellow]=api-sports.io (1200+ lig)[/dim]\n"
    )
    if af:
        console.print("[dim green]✓ API-Football aktywne – Ekstraklasa i inne ligi dostepne![/dim green]\n")
    else:
        console.print(
            "[dim yellow]ℹ Dodaj klucz APISPORTS_KEY aby odblokować 1200+ lig (opcja K)[/dim yellow]\n"
        )

    while True:
        wybor_str = Prompt.ask(f"[bold yellow]Numer ligi (1-{len(ligi_wszystkie)})[/bold yellow]", default="1")
        try:
            idx = int(wybor_str)
            if 1 <= idx <= len(ligi_wszystkie):
                liga = ligi_wszystkie[idx-1]
                console.print(f"[dim]Wybrano: [bold]{liga['nazwa']}[/bold] "
                               f"([cyan]{liga['kod']}[/cyan] | {liga['src']})[/dim]")
                api_id = liga.get("api_id")   # None dla FDB lig
                return liga["kod"], liga["nazwa"], liga["druzyny"], api_id
        except (ValueError, IndexError):
            pass
        console.print(f"[red]Wpisz liczbe 1-{len(ligi_wszystkie)}.[/red]")


def pobierz_dane_apisports(af: "APIFootball", api_id: int, nazwa: str):
    """
    Pobiera dane z api-sports.io dla wybranej ligi.
    Zwraca (df_tabela, df_wyniki, df_nadchodzace).
    """
    df_tab = df_wyk = df_nad = None
    with Progress(SpinnerColumn(style="yellow"), TextColumn("{task.description}"),
                  BarColumn(bar_width=20, complete_style="yellow"),
                  console=console, transient=True) as prog:
        t1 = prog.add_task(f"Tabela {nazwa} (API-Football)...", total=1)
        df_tab = af.tabela_liga(api_id)
        prog.update(t1, completed=1)
        time.sleep(3)   # API-Football: 100 req/dzien – oszczednosc

        t2 = prog.add_task("Wyniki (100 meczow)...", total=1)
        df_wyk = af.wyniki_liga(api_id)
        prog.update(t2, completed=1)
        time.sleep(3)

        t3 = prog.add_task("Nadchodzace mecze...", total=1)
        df_nad = af.nadchodzace_liga(api_id)
        prog.update(t3, completed=1)

    if df_tab is None:
        console.print("[yellow]Brak tabeli z API-Football – generuje z wynikow...[/yellow]")
        if df_wyk is not None:
            # Minimal tabela z wynikow
            df_tab = _generuj_tabele_z_wynikow(df_wyk)

    return df_tab, df_wyk, df_nad


def _generuj_tabele_z_wynikow(df_wyk: pd.DataFrame) -> pd.DataFrame:
    """
    Generuje uproszczona tabele ligowa z DataFrame wynikow.
    Przydatne gdy API nie zwroci standings lub dla niestandardowych lig.
    """
    if df_wyk is None or df_wyk.empty:
        return pd.DataFrame()

    druzyny = sorted(set(df_wyk["gospodarz"]) | set(df_wyk["goscie"]))
    rows = []
    for d in druzyny:
        dom = df_wyk[df_wyk["gospodarz"] == d]
        wyj = df_wyk[df_wyk["goscie"]    == d]
        m   = len(dom) + len(wyj)
        if m == 0:
            continue
        w = (dom["gole_g"] > dom["gole_a"]).sum() + (wyj["gole_a"] > wyj["gole_g"]).sum()
        r = (dom["gole_g"] == dom["gole_a"]).sum() + (wyj["gole_a"] == wyj["gole_g"]).sum()
        p = m - w - r
        bz = int(dom["gole_g"].sum()) + int(wyj["gole_a"].sum())
        bs = int(dom["gole_a"].sum()) + int(wyj["gole_g"].sum())
        pkt= int(w*3 + r)
        rows.append({
            "Druzyna": d, "M": m, "W": int(w), "R": int(r), "P": int(p),
            "BZ": bz, "BS": bs, "Bramki": f"{bz}:{bs}", "+/-": bz-bs, "Pkt": pkt
        })
    df = pd.DataFrame(rows).sort_values("Pkt", ascending=False).reset_index(drop=True)
    df.insert(0, "Poz.", range(1, len(df)+1))
    return df


# ================================================================
#  MODUL 13d – SZYBKIE PEWNIACZKI (2 DNI) + SCOUT BOT  (v2.7.1)
# ================================================================
#
#  Dostepne PRZED zaladowaniem ligi (w glownym menu startowym).
#  Nie wymaga zadnych reqow poza Bzzoiro (juz zaladowanym na start).
#
#  Szybkie Pewniaczki 48h:
#    - Skanuje nadchodzace 48h z Bzzoiro ML
#    - Filtruje typy >= prog%
#    - Grupuje wg dni
#    - Pokazuje kursy bukmacherskie z Bzzoiro
#
#  Scout Bot – ocena ryzyka przed meczem:
#    - Dla kazdego pewniaczka: ocenia dodatkowe czynniki ryzyka
#    - Sprawdza spread kursow (niski kurs = mala wartosc)
#    - Liczy wartosc oczekiwana: EV = P * kurs - 1
#    - Ostrzega gdy ML sugeruje zbyt duza pewnosc (overconfidence)
#    - Ocenia: ZYSK (+) / NEUTRALNY (0) / STRATA (-) na dluga mete
#
#  Analiza kuponu:
#    - Ocenia wprowadzony kupon bukmacherski
#    - Sprawdza kazdy mecz przez Bzzoiro ML
#    - Wylicza EV kazdego zdarzenia i AKU
# ================================================================


def szybkie_pewniaczki_2dni(
    bzzoiro: "BzzoiroClient",
    prog: float = PEWNIACZEK_PROG,
    godziny: int = 48,
) -> list:
    """
    Skanuje nadchodzace mecze (domyslnie 48h) z Bzzoiro ML.

    Nie wymaga zaladowania zadnej ligi. Dziala wylacznie na danych ML.
    Kazdy mecz oceniany jest przez Scout Bot (EV, wartosc zakl., ryzyko).

    Parametry:
        bzzoiro  – klient BzzoiroClient
        prog     – minimalny prog pewnosci (domyslnie 75%)
        godziny  – horyzont czasowy w godzinach (domyslnie 48)

    Zwraca liste slownikow z pewniaczkami + ocena Scout Bota.
    """
    if not bzzoiro or not getattr(bzzoiro, "_valid", False):
        console.print("[yellow]Bzzoiro niedostepne – brak danych ML.[/yellow]")
        return []

    teraz    = datetime.now()
    granica  = teraz + timedelta(hours=godziny)

    console.print(f"[dim]🔍 Skanowanie Bzzoiro ML na {godziny}h...[/dim]")
    try:
        lista_ml = bzzoiro.predykcje_tygodnia()
    except Exception as e:
        console.print(f"[red]Bzzoiro blad: {e}[/red]")
        return []

    console.print(f"[dim]   Pobrano {len(lista_ml)} wydarzen.[/dim]")

    wyniki = []
    for ev in lista_ml:
        g    = str(ev.get("gosp",  "") or "").strip()
        a    = str(ev.get("gosc",  "") or "").strip()
        liga = str(ev.get("liga",  "") or "?")
        d    = str(ev.get("data",  "") or "")[:10]
        godz = str(ev.get("godzina","") or "–")[:5]

        if not g or not a or not d:
            continue

        # Filtruj tylko mecze w horyzoncie czasowym
        try:
            dm = datetime.strptime(
                f"{d} {godz}" if godz not in ("–","") else d,
                "%Y-%m-%d %H:%M" if godz not in ("–","") else "%Y-%m-%d"
            )
        except ValueError:
            try:
                dm = datetime.strptime(d, "%Y-%m-%d")
            except ValueError:
                continue
        if not (teraz <= dm <= granica):
            continue

        pred_ml = ev.get("pred_ml")
        odds    = ev.get("odds") or {}

        if not pred_ml:
            continue

        # Parsuj ML przez universalny parser (wszystkie formaty Bzzoiro)
        wyp = _bzz_parse_prob(pred_ml)
        if wyp is None:
            continue
        pw, pr, pp, bt, o25 = wyp
        u25 = round(100.0 - o25, 1)

        # Zbierz typy pewne
        typy = _typy_pewne(pw, pr, pp, bt, o25, u25, g, a, prog)
        if not typy:
            continue

        # ── Scout Bot: ocena wartosci kazdego typu ──────────────────
        # Expected Value (EV) = P * kurs - 1
        # EV > 0 = zysk na dluga mete, EV < 0 = strata
        scout = _scout_bot_ocen(typy, odds, pw, pr, pp, bt, o25, u25)

        # Oczekiwany wynik (most likely score ML)
        ms = (pred_ml.get("most_likely_score") or {})
        wg = int(ms.get("home", 1)); wa = int(ms.get("away", 0))

        wyniki.append({
            "data":       d,
            "godzina":    godz,
            "dt":         dm,           # datetime do sortowania
            "gospodarz":  g,
            "goscie":     a,
            "liga":       liga,
            "typy":       typy,
            "pw": pw, "pr": pr, "pp": pp,
            "bt": bt, "o25": o25,
            "wynik_g":    wg,
            "wynik_a":    wa,
            "odds":       odds,
            "scout":      scout,
        })

    # Sortuj: najpierw czasowo, potem najlepsza szansa malejaco
    wyniki.sort(key=lambda x: (x["dt"], -max(v for _, v in x["typy"])))
    return wyniki


def _scout_bot_ocen(
    typy: list,
    odds: dict,
    pw: float, pr: float, pp: float,
    bt: float, o25: float, u25: float,
) -> dict:
    """
    Scout Bot: ocenia wartosc kazdego typu przez pryzmat EV i spread.

    Logika:
      EV = P_model * kurs_bukmacher - 1.0
      EV > 0   → zysk w dlugim terminie (warto brac)
      EV 0.0   → neutralnie
      EV < 0   → strata strukturalna (bookmaker ma przewage)

    Oceny ryzyka:
      ✅ WARTOSC  – EV > +3% i ML >= 70%
      ⚡ SLABA    – EV 0-3% lub ML 60-70%
      ⚠️  UWAGA   – kurs < 1.3 (bookmaker zabezpiecza sie nisko)
      ❌ STRATA   – EV < 0 (bookmaker przecenia szanse)

    Parametry:
        typy  – lista (opis, szansa%) z _typy_pewne()
        odds  – dict kursow z Bzzoiro {home, draw, away, btts, over_2_5 ...}
        pw..u25 – prawdopodobienstwta z ML (%)

    Zwraca slownik: {oceny: [(opis, ev, ocena_str)], best_ev, ostrzezenia}
    """
    # Mapowanie typow na prawdopodobienstwta i klucze kursow
    P_MAP = {
        "1":        (pw,   "home"),
        "1X":       (pw + pr, None),
        "X2":       (pr + pp, None),
        "12":       (pw + pp, None),
        "2":        (pp,   "away"),
        "X":        (pr,   "draw"),
        "BTTS":     (bt,   "btts"),
        "Over 2.5": (o25,  "over_2_5"),
        "Under 2.5":(u25,  "under_2_5"),
    }

    oceny = []
    all_ev = []
    ostrzezenia = []

    for typ_opis, szansa in typy:
        # Dopasuj typ do P_MAP
        p_val = szansa / 100.0   # juz jako ulamek
        kurs  = None
        for klucz, (p_ref, odds_key) in P_MAP.items():
            if klucz in typ_opis.upper() or klucz in typ_opis:
                # Sprawdz kurs
                if odds_key and isinstance(odds, dict):
                    k = odds.get(odds_key)
                    if k:
                        try:
                            kurs = float(str(k).replace(",", "."))
                        except (ValueError, TypeError):
                            kurs = None
                break

        if kurs and kurs > 1.0:
            ev = round(p_val * kurs - 1.0, 3)
        else:
            ev = None

        # Okresl ocene
        if ev is None:
            # Brak kursu – tylko ocena ML
            if szansa >= 82:
                ocena = "✅ ML WYSOKI"
            elif szansa >= 72:
                ocena = "⚡ ML SREDNI"
            else:
                ocena = "⚠️  ML GRANICZNY"
        elif ev > 0.05:
            ocena = "✅ WARTOSC+"     # EV > 5%: wyraznie na plus
        elif ev > 0.01:
            ocena = "⚡ LEKKO+"      # EV 1-5%: slaba wartosc
        elif ev >= -0.01:
            ocena = "➖ NEUTRALNY"   # EV ~0: wash
        elif kurs and kurs < 1.35:
            ocena = "⚠️  NISKI KURS" # Kursy ponizej 1.35 sa ryzykowne w AKU
        else:
            ocena = "❌ EV UJEMNY"   # EV < -1%: strata

        if kurs and kurs < 1.3:
            ostrzezenia.append(
                f"Kurs {kurs} jest bardzo niski – 1 strata kasuje wiele zyskow w AKU"
            )
        if szansa >= 90:
            ostrzezenia.append(
                f"{typ_opis[:20]}: ML {szansa:.0f}% – overconfidence, sprawdz w innym zrodle"
            )

        oceny.append({
            "typ":   typ_opis,
            "ev":    ev,
            "kurs":  kurs,
            "ocena": ocena,
        })
        if ev is not None:
            all_ev.append(ev)

    best_ev = max(all_ev) if all_ev else None

    return {
        "oceny":        oceny,
        "best_ev":      best_ev,
        "ostrzezenia":  list(set(ostrzezenia)),   # deduplikacja
    }


def wyswietl_szybkie_pewniaczki(
    wyniki: list,
    prog: float = PEWNIACZEK_PROG,
    godziny: int = 48,
):
    """
    Wyswietla Szybkie Pewniaczki 48h z ocena Scout Bota.

    Grupuje mecze wg dni.
    Dla kazdego pewniaczka pokazuje:
      - Typy z szansa
      - Kursy bukmacherskie
      - EV (Expected Value) z ocena
      - Ostrzezenia Scout Bota
    """
    if not wyniki:
        console.print(Panel(
            f"[yellow]Brak pewniakow >= {prog:.0f}% w nastepnych {godziny}h.[/yellow]\n"
            "[dim]Sprobuj obnizyc prog lub sprawdz za kilka godzin.[/dim]",
            border_style="yellow", title="Szybkie Pewniaczki"
        ))
        return

    teraz = datetime.now()
    granica_dt = teraz + timedelta(hours=godziny)

    # Naglowek
    console.print(Panel(
        f"[bold yellow]⚡ SZYBKIE PEWNIACZKI  "
        f"[white]{len(wyniki)} meczow >= {prog:.0f}%[/white] ⚡[/bold yellow]\n"
        f"[dim]Teraz: {teraz.strftime('%d.%m %H:%M')} → "
        f"{granica_dt.strftime('%d.%m %H:%M')}  "
        f"| Tylko ML Bzzoiro | Scout Bot EV aktywny[/dim]",
        border_style="yellow",
        title="[bold yellow]⚡ SZYBKIE PEWNIACZKI 48h – FootStats[/bold yellow]",
        padding=(0, 2),
    ))
    console.print()

    # Grupuj wg daty
    dni: dict = {}
    for p in wyniki:
        d = p["data"]
        dni.setdefault(d, []).append(p)

    for dzien, mecze in sorted(dni.items()):
        try:
            dzien_str = datetime.strptime(dzien, "%Y-%m-%d").strftime("%A, %d.%m.%Y")
        except ValueError:
            dzien_str = dzien
        console.print(f"\n[bold cyan]── {dzien_str} ──[/bold cyan]")

        for p in mecze:
            g, a = p["gospodarz"], p["goscie"]
            kol  = "green" if p.get("scout", {}).get("best_ev", -1) and p["scout"]["best_ev"] > 0.03 else "white"

            console.print(
                f"  [bold {kol}]{g} vs {a}[/bold {kol}]  "
                f"[dim]{p['godzina']}  {p['liga']}[/dim]  "
                f"[dim yellow]Typ: {p['wynik_g']}:{p['wynik_a']}[/dim yellow]"
            )
            console.print(
                f"  [dim]ML:  1={p['pw']:.0f}%  X={p['pr']:.0f}%  2={p['pp']:.0f}%  "
                f"BTTS={p['bt']:.0f}%  Over2.5={p['o25']:.0f}%[/dim]"
            )

            # Kursy z Bzzoiro
            odds = p.get("odds", {}) or {}
            if isinstance(odds, dict) and any(odds.values()):
                o1 = odds.get("home", "–"); ox = odds.get("draw", "–"); o2 = odds.get("away", "–")
                console.print(f"  [dim]Kursy: 1={o1}  X={ox}  2={o2}[/dim]")

            # Typy pewne + ocena Scout Bota
            scout = p.get("scout", {})
            oceny_idx = {oc["typ"]: oc for oc in scout.get("oceny", [])}

            t_s = Table(box=box.SIMPLE, show_header=False, pad_edge=False, padding=(0, 1))
            t_s.add_column("Typ",   style="white",        width=28)
            t_s.add_column("Sz.",   style="bold yellow",  width=7,  justify="right")
            t_s.add_column("Kurs",  style="dim cyan",     width=6,  justify="right")
            t_s.add_column("EV",    style="dim",          width=8,  justify="right")
            t_s.add_column("Ocena", style="bold",         width=18)

            for tn, tv in p["typy"]:
                oc    = oceny_idx.get(tn, {})
                kurs  = f"{oc.get('kurs','–')}" if oc.get("kurs") else "–"
                ev    = f"{oc.get('ev',0)*100:+.1f}%" if oc.get("ev") is not None else "–"
                ocena = oc.get("ocena", "")
                # Kolor oceny
                if "WARTOSC" in ocena:  kol_o = "bold green"
                elif "LEKKO"  in ocena: kol_o = "green"
                elif "STRATA" in ocena or "UJEMNY" in ocena: kol_o = "red"
                elif "UWAGA"  in ocena or "NISKI"  in ocena: kol_o = "yellow"
                else:                   kol_o = "dim"
                t_s.add_row(tn, f"{tv:.1f}%", kurs, ev, f"[{kol_o}]{ocena}[/{kol_o}]")

            console.print(t_s)

            # Ostrzezenia Scout Bota
            for ost in scout.get("ostrzezenia", []):
                console.print(f"  [yellow]⚠️  Scout: {ost}[/yellow]")

            console.print()

    # Legenda EV
    console.print(
        "[dim]EV = Expected Value: % zysku/straty na dluga mete per 1 PLN postawiony\n"
        "✅ WARTOSC+ = EV>5%  ⚡ LEKKO+ = EV 1-5%  ➖ = neutralnie  "
        "❌ = strata strukturalna  ⚠️ = niski kurs < 1.35[/dim]\n"
    )


# ================================================================
#  MODUL 18 - GLOWNA PETLA
# ================================================================

def _reinicjuj_systemy(df_tabela, df_wyniki, n_druzyn, kod_ligi):
    """Tworzy/odswierza wszystkie systemy analityczne po zmianie ligi."""
    return {
        "importance":     ImportanceIndex(df_tabela, n_druzyn),
        "heurystyka_eng": HeurystaZmeczeniaRotacji(df_wyniki),
        "h2h_sys":        AnalizaH2H(df_wyniki),
        "fortress_sys":   HomeFortress(df_wyniki),
        "klasyfikator":   KlasyfikatorMeczu(df_wyniki, kod_ligi),
        "dw_sys":         AnalizaDomWyjazd(df_wyniki),
    }


def _wyswietl_menu_startowe(bzzoiro):
    """
    Ekran startowy po walidacji kluczy API.
    Daje mozliwosc uruchomienia Szybkich Pewniaczek 48h (opcja P)
    PRZED zaladowaniem jakiejkolwiek ligi – zero reqow FDB.
    """
    console.print()
    if bzzoiro:
        console.print(Panel(
            "[bold yellow]⚡ P[/bold yellow]  – [bold yellow]Szybkie Pewniaczki 48h[/bold yellow]  "
            "[dim](Bzzoiro ML, Scout Bot EV, bez ladowania ligi)[/dim]\n"
            "[bold]Enter[/bold] – Zaladuj konkretna lige i pelna analize",
            border_style="dim yellow",
            title="[dim]Co chcesz zrobic?[/dim]",
            padding=(0, 2),
        ))
    else:
        console.print(Panel(
            "[bold]Enter[/bold]  Zaladuj konkretna lige\n"
            "[dim yellow]Dodaj klucz BZZOIRO_KEY aby odblokować Szybkie Pewniaczki[/dim yellow]",
            border_style="dim",
            title="[dim]Start[/dim]",
            padding=(0, 2),
        ))
    console.print()


def _analiza_kuponu(bzzoiro):
    """
    Opcja A - Analiza Kuponu Bukmacherskiego.
    Uzytkownik wpisuje mecze z kuponu, Scout Bot ocenia EV i ryzyko.

    Format: Gospodarz vs Goscie | TYP | KURS
    Typy:   1  X  2  1X  X2  12  BTTS  Over2.5  Under2.5
    """
    console.print(Panel(
        "[bold]Wpisz mecze z kuponu[/bold] - jeden na linie:\n"
        "[dim]Format:  Gospodarz vs Goscie | TYP | KURS\n"
        "Przyklad: Real Madryt vs Getafe | 1 | 1.40\n"
        "          Leeds vs Sunderland | 1X | 1.26\n"
        "Typy: 1  X  2  1X  X2  12  BTTS  Over2.5  Under2.5\n"
        "Pusty wiersz = koniec[/dim]",
        border_style="magenta",
        title="[bold magenta]ANALIZA KUPONU – Scout Bot[/bold magenta]",
        padding=(0, 2)
    ))

    wpisy = []
    while True:
        linia = Prompt.ask("[dim magenta]>[/dim magenta]", default="").strip()
        if not linia:
            break
        wpisy.append(linia)

    if not wpisy:
        console.print("[yellow]Brak wpisow.[/yellow]")
        return

    mecze_kuponu = []
    for linia in wpisy:
        czesci = [c.strip() for c in linia.split("|")]
        mecz_str = czesci[0] if czesci else linia
        typ_str  = czesci[1].upper().strip() if len(czesci) > 1 else "?"
        try:
            kurs = float(czesci[2].replace(",", ".")) if len(czesci) > 2 else None
        except (ValueError, IndexError):
            kurs = None
        druz = [d.strip() for d in mecz_str.replace(" - ", " vs ").split(" vs ", 1)]
        g = druz[0] if druz else mecz_str
        a = druz[1] if len(druz) > 1 else "?"
        mecze_kuponu.append({"g": g, "a": a, "typ": typ_str, "kurs": kurs})

    if not mecze_kuponu:
        console.print("[yellow]Brak poprawnych wpisow.[/yellow]")
        return

    bzz_indeks = {}
    if bzzoiro and getattr(bzzoiro, "_valid", False):
        console.print("[dim]Pobieranie ML Bzzoiro...[/dim]")
        try:
            for ev in bzzoiro.predykcje_tygodnia():
                g_b = str(ev.get("gosp", "") or "").strip().lower()
                a_b = str(ev.get("gosc", "") or "").strip().lower()
                if g_b and a_b:
                    bzz_indeks[g_b + "|" + a_b] = ev
        except Exception as ex:
            console.print(f"[yellow]Bzzoiro: {ex}[/yellow]")

    TYP_MAP = {
        "1": "pw", "X": "pr", "2": "pp",
        "1X": "pw_pr", "X2": "pr_pp", "12": "pw_pp",
        "BTTS": "bt", "BTTSTAK": "bt",
        "OVER2.5": "o25", "UNDER2.5": "u25",
    }

    console.print()
    kurs_aku = 1.0
    ev_lista = []

    for mc in mecze_kuponu:
        g, a, typ, kurs = mc["g"], mc["a"], mc["typ"], mc["kurs"]
        console.rule(
            f"[bold white]{g}[/bold white] vs [bold white]{a}[/bold white]"
            + (f"  [dim]{typ}  @{kurs}[/dim]" if kurs else f"  [dim]{typ}[/dim]")
        )

        klucz_ml = g.lower() + "|" + a.lower()
        ev_ml = bzz_indeks.get(klucz_ml)
        p_model = None
        ml_info = "[dim]Brak ML (sprawdz nazwy druzyn)[/dim]"

        if ev_ml:
            wyp = _bzz_parse_prob(ev_ml.get("pred_ml"))
            if wyp:
                pw, pr, pp, bt, o25 = wyp
                u25 = round(100 - o25, 1)
                probs = {
                    "pw": pw, "pr": pr, "pp": pp,
                    "pw_pr": pw+pr, "pr_pp": pr+pp, "pw_pp": pw+pp,
                    "bt": bt, "o25": o25, "u25": u25,
                }
                ml_info = (
                    f"[dim]ML: 1={pw:.0f}%  X={pr:.0f}%  2={pp:.0f}%  "
                    f"BTTS={bt:.0f}%  Ov2.5={o25:.0f}%[/dim]"
                )
                typ_k = typ.replace(" ", "").replace(".", "").upper()
                p_model = probs.get(TYP_MAP.get(typ_k))

        console.print("  " + ml_info)

        ev_str = "–"
        ocena  = "[dim]brak danych[/dim]"
        ev_val = None
        if p_model is not None and kurs:
            ev_val = round(p_model / 100.0 * kurs - 1.0, 3)
            ev_str = f"{ev_val*100:+.1f}%"
            if ev_val > 0.05:
                ocena = "[bold green]WARTOSC+[/bold green]"
            elif ev_val > 0.01:
                ocena = "[green]LEKKO+[/green]"
            elif ev_val >= -0.01:
                ocena = "[dim]NEUTRALNY[/dim]"
            elif kurs and kurs < 1.35:
                ocena = "[yellow]NISKI KURS[/yellow]"
            else:
                ocena = "[red]EV UJEMNY[/red]"
            ev_lista.append(ev_val)

        p_str = f"[cyan]{p_model:.0f}%[/cyan]" if p_model is not None else "[dim]?[/dim]"
        k_str = f"[yellow]@{kurs}[/yellow]" if kurs else "[dim]brak kursu[/dim]"
        console.print(
            f"  Typ: [bold]{typ}[/bold]  Kurs: {k_str}  "
            f"P_ML: {p_str}  EV: {ev_str}  {ocena}"
        )
        if kurs and kurs < 1.3:
            console.print("  [yellow]Kurs < 1.30 – jedna strata kasuje kilka zyskow w AKU[/yellow]")
        if p_model is not None and p_model < 55:
            console.print(f"  [red]P_ML={p_model:.0f}% < 55% – ryzykowny typ[/red]")
        if kurs:
            kurs_aku *= kurs
        console.print()

    console.rule("[bold]Podsumowanie kuponu[/bold]")
    console.print(f"  Kurs AKU: [bold yellow]{kurs_aku:.2f}[/bold yellow]")
    if ev_lista:
        ev_aku = 1.0
        for e in ev_lista:
            ev_aku *= (1 + e)
        ev_aku -= 1.0
        kol = "green" if ev_aku > 0 else ("yellow" if ev_aku > -0.1 else "red")
        console.print(
            f"  EV kuponu: [{kol}]{ev_aku*100:+.1f}%[/{kol}]  "
            f"[dim](na {len(ev_lista)}/{len(mecze_kuponu)} zdarzeniach z ML)[/dim]"
        )
        if ev_aku > 0.02:
            console.print("  [bold green]Kupon na plusie EV[/bold green]")
        elif ev_aku < -0.15:
            console.print("  [red]Kupon zdecydowanie ujemny EV – niepolecany[/red]")
        else:
            console.print("  [yellow]EV bliski zeru – typowe kursy bookmaker[/yellow]")
    else:
        console.print("  [dim]Brak danych ML do obliczenia EV.[/dim]")
    console.print()


def main():
    api_key = _wczytaj_lub_stworz_env()
    _zarejestruj_font()
    wyswietl_naglowek()

    # ── v2.7: SourceManager + walidacja wszystkich kluczy ────────────
    klucze  = _czytaj_wszystkie_klucze()
    sources = SourceManager(klucze)
    sources.waliduj_i_wyswietl()

    api     = APIClient(api_key)
    bzzoiro = sources.bzz if sources.bzzoiro_ok else None

    # ── Ekran startowy: Szybkie Pewniaczki lub zaladuj lige ──────────
    # Opcja P dostepna natychmiast – nie wymaga ladowania zadnej ligi.
    # Skanuje Bzzoiro ML (0 req FDB/AF) i uruchamia Scout Bot EV.
    _wyswietl_menu_startowe(bzzoiro)
    # Bez choices= – Rich crashuje gdy user wpisze nieznany znak (np. "n")
    wybor_start = Prompt.ask(
        "[bold yellow]Twoj wybor (P = Pewniaczki, Enter = zaladuj lige)[/bold yellow]",
        default=""
    ).strip().lower()[:1]

    if wybor_start == "p":
        console.print()
        try:
            prog_start = float(Prompt.ask(
                "[bold yellow]Min. szansa %[/bold yellow]",
                default=str(int(PEWNIACZEK_PROG))
            ))
        except ValueError:
            prog_start = PEWNIACZEK_PROG
        try:
            godz_start = int(Prompt.ask("[bold yellow]Horyzont godziny[/bold yellow]", default="48"))
        except ValueError:
            godz_start = 48

        with Progress(SpinnerColumn(style="yellow"),
                      TextColumn("[yellow]Szukam Pewniakow 48h...[/yellow]"),
                      console=console, transient=True) as pg:
            pg.add_task("", total=None)
            wyniki_start = szybkie_pewniaczki_2dni(bzzoiro, prog_start, godz_start)
        wyswietl_szybkie_pewniaczki(wyniki_start, prog_start, godz_start)

        if not Confirm.ask("[dim]Zaladowac tez konkretna lige?[/dim]", default=True):
            console.print("[dim]Do widzenia.[/dim]")
            return
        console.print()

    # ── Menu lig + pobieranie z petla (powraca jesli brak danych) ───────
    while True:
        kod_ligi, nazwa_ligi, n_druzyn, api_id_af = wyswietl_menu_lig_v27(
            api, sources.af if sources.apisports_ok else None)
        console.print()

        # Pobierz dane z odpowiedniego zrodla
        if api_id_af and sources.apisports_ok:
            df_tabela, df_wyniki, df_nadchodzace = pobierz_dane_apisports(
                sources.af, api_id_af, nazwa_ligi)
        else:
            df_tabela, df_wyniki, df_nadchodzace = pobierz_dane(api, kod_ligi, nazwa_ligi)

        # Sprawdz czy dane sa uzyteczne
        brak_tabeli  = df_tabela is None or (hasattr(df_tabela, 'empty') and df_tabela.empty)
        brak_wynikow = df_wyniki  is None or (hasattr(df_wyniki,  'empty') and df_wyniki.empty)

        if brak_wynikow:
            console.print(Panel(
                f"[bold yellow]Brak danych dla: [white]{nazwa_ligi}[/white][/bold yellow]\n\n"
                "[dim]Mozliwe przyczyny:[/dim]\n"
                "  • Turniej zakonczony (np. MŚ 2022, Euro 2024)\n"
                "  • Liga nie zaczela jeszcze sezonu\n"
                "  • Problem z polaczeniem lub limitem API\n\n"
                "[dim]Wybierz inna lige lub sprawdz polaczenie.[/dim]",
                border_style="yellow", title="⚠ Brak danych", padding=(1, 2)
            ))
            if not Confirm.ask("[yellow]Wybrac inna lige?[/yellow]", default=True):
                console.print("[dim]Do widzenia.[/dim]")
                return
            wyswietl_naglowek()
            sources.waliduj_i_wyswietl()
            continue

        if brak_tabeli:
            # Wygeneruj minimalna tabele z wynikow jesli brak oficjalnych standings
            console.print("[dim yellow]Brak officialnej tabeli – generuje z wynikow...[/dim yellow]")
            df_tabela = _generuj_tabele_z_wynikow(df_wyniki)
            if df_tabela is None or (hasattr(df_tabela, 'empty') and df_tabela.empty):
                console.print("[yellow]Tabela rowniez niedostepna – kontynuuje bez rankingu.[/yellow]")
                # Stworz minimalna tabele z samych nazw druzyn
                druzyny_min = sorted(set(df_wyniki["gospodarz"]) | set(df_wyniki["goscie"]))
                df_tabela = pd.DataFrame({"Druzyna": druzyny_min, "Pkt": [0]*len(druzyny_min)})

        break   # Dane OK – wychodzimy z petli

    sys_anal = _reinicjuj_systemy(df_tabela, df_wyniki, n_druzyn, kod_ligi)

    n_nad = len(df_nadchodzace) if df_nadchodzace is not None else 0
    console.print(
        f"[green]OK: {len(df_wyniki)} wynikow | {len(df_tabela)} druzyn | "
        f"{n_nad} nadchodzacych – {nazwa_ligi}[/green]\n"
    )
    if bzzoiro:
        console.print("[dim green]✓ Bzzoiro ML aktywne – Pewniaczki z cross-walidacja[/dim green]")
    else:
        console.print("[dim yellow]ℹ Bzzoiro nieaktywne – opcja 8 bez ML validation[/dim yellow]")
    if sources.apisports_ok:
        bud = af_budget_status()
        kol = "green" if not bud["ostrzezenie"] else ("yellow" if not bud["krytyczny"] else "red")
        ci  = af_cache_info()
        console.print(
            f"[dim]API-Football: [{kol}]{bud['pozostalo']}/{bud['limit']} req pozostalo[/{kol}] "
            f"| Cache: {ci['wpisy']} wpisow ({ci['rozmiar_kb']}KB, TTL 24h)[/dim]"
        )
    console.print()

    cache_kolejki: list = []
    cache_pewniaczki: list = []

    # ── AI moduły (opcja AI) – ładuj jeśli dostępne ──────────────────
    # OPCJA_AI_FOOTSTATS_PATCH
    _ai_dostepne = False
    try:
        from ai_client   import zapytaj_ai        as _zapytaj_ai    # noqa: F401
        from ai_analyzer import analizuj_mecz_ai  as _analizuj_ai   # noqa: F401
        from ai_analyzer import wyswietl_analiza_ai as _pokaz_ai    # noqa: F401
        from scraper_kursy import szukaj_kursy_meczu as _kursy_ai   # noqa: F401
        _ai_dostepne = True
    except ImportError:
        pass

    while True:
        imp    = sys_anal["importance"]
        heur   = sys_anal["heurystyka_eng"]
        h2h    = sys_anal["h2h_sys"]
        fort   = sys_anal["fortress_sys"]
        klas   = sys_anal["klasyfikator"]
        dw     = sys_anal["dw_sys"]

        console.rule(f"[bold blue]MENU  FootStats {VERSION}[/bold blue]")
        console.print("[bold]1[/bold]  Tabela ligowa  [dim](Importance 2.0 – tryb finalny)[/dim]")
        console.print("[bold]2[/bold]  Ostatnie wyniki")
        console.print("[bold]3[/bold]  Predykcja meczu  [dim](+ H2H/Patent/Fortress/Dom-Wyjazd)[/dim]")
        console.print("[bold]4[/bold]  Porownanie formy  [dim](H2H 24 mies. + historia)[/dim]")
        console.print("[bold]5[/bold]  Analiza kolejki  [dim]([LIGA/PUCHAR/REWANZ/FINAL] v2.6)[/dim]")
        console.print("[bold]6[/bold]  Eksport PDF  [dim](raport z komentarzem)[/dim]")
        console.print("[bold]7[/bold]  Zmien lige")
        console.print(
            "[bold cyan]9[/bold cyan]  "
            "[bold cyan]✈️  Analiza Dom/Wyjazd[/bold cyan]  "
            "[dim cyan](dom vs wyjazd statystyki, wykrywanie Podroznikow)[/dim cyan]"
        )
        console.print(
            "[bold green]P[/bold green]  "
            "[bold green]★ Pewniaczki Tygodnia[/bold green]  "
            "[dim green](ML + Poisson, Scout Bot EV, PDF)[/dim green]"
        )
        console.print(
            "[bold magenta]A[/bold magenta]  "
            "[bold magenta]Analiza Kuponu[/bold magenta]  "
            "[dim magenta](wklej mecze – Scout Bot oceni EV i ryzyko)[/dim magenta]"
        )
        if not sources.bzzoiro_ok or not sources.apisports_ok:
            console.print(
                "[bold magenta]K[/bold magenta]  "
                "[dim magenta]Dodaj klucz API  "
                f"({'Bzzoiro' if not sources.bzzoiro_ok else 'API-Football'})[/dim magenta]"
            )
        if sources.apisports_ok:
            bud = af_budget_status()
            kol = "green" if not bud["ostrzezenie"] else ("yellow" if not bud["krytyczny"] else "red")
            console.print(
                f"[bold dim]C[/bold dim]  "
                f"[dim]Cache API-Football  "
                f"[{kol}]({bud['pozostalo']}/{bud['limit']} req)[/{kol}][/dim]"
            )
        if _ai_dostepne:
            console.print(
                "[bold yellow]I[/bold yellow]  "
                "[bold yellow]🤖 AI Analiza meczu[/bold yellow]  "
                "[dim yellow](Groq 70B / Ollama + kursy bukmacherów)[/dim yellow]"
            )
            console.print(
                "[bold yellow]J[/bold yellow]  "
                "[bold yellow]🤖 AI Analiza kolejki[/bold yellow]  "
                "[dim yellow](wszystkie nadchodzące mecze)[/dim yellow]"
            )
        console.print("[bold]0[/bold]  Wyjscie\n")

        choices = ["0","1","2","3","4","5","6","7","9","a","A","k","K","c","C","p","P","i","I","j","J"]
        wybor = Prompt.ask("[bold yellow]Twoj wybor[/bold yellow]",
                           choices=choices, default="1").lower()

        if wybor == "1":
            console.print()
            wyswietl_tabele(df_tabela, nazwa_ligi, imp)

        elif wybor == "2":
            console.print()
            try:   ile = int(Prompt.ask("Ile meczow?", default="10"))
            except ValueError: ile = 10
            wyswietl_wyniki(df_wyniki, ile)

        elif wybor == "3":
            console.print()
            g, a     = wybierz_druzyny(df_wyniki)
            imp_g    = imp.analiza(g)
            imp_a    = imp.analiza(a)
            data_now = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
            heur_g   = heur.analiza(g, data_now)
            heur_a   = heur.analiza(a, data_now)
            console.print(f"[dim]Obliczam H2H (24 mies.) dla {g} vs {a}...[/dim]")
            h2h_g    = h2h.analiza(g, a)
            time.sleep(SLEEP_LOOP)
            h2h_a    = h2h.analiza(a, g)
            fort_g   = fort.analiza(g)
            klas_m   = klas.klasyfikuj(g, a, "REGULAR_SEASON", data_now, None, None)
            # Dom/Wyjazd – goscie Podroznik?
            dw_a = dw.analiza(a)
            h2h_a_uzup = dict(h2h_a)
            if dw_a.get("podroznik"):
                h2h_a_uzup["mnoznik_atak"] = h2h_a_uzup.get("mnoznik_atak",1.0)*dw_a["bonus_wyjazd"]
                console.print(f"[green]✈️ {a} to Podroznik (+10% lambda ataku)[/green]")

            ikony = (heur_g["ikony"]+heur_a["ikony"]+h2h_g["ikona"]+
                     h2h_a["ikona"]+fort_g.get("ikona","")+dw_a.get("ikona",""))
            console.print(f"[dim]Analiza: {g} vs {a}[/dim]")
            if ikony.strip():
                console.print(f"[dim]Czynniki v2.7: {ikony.strip()}[/dim]")
            console.print(f"[dim]Pewnosc H2H: G={h2h_g['pewnosc']}% | A={h2h_a['pewnosc']}%[/dim]")
            console.print()
            with Progress(SpinnerColumn(style="yellow"),
                          TextColumn("[yellow]Obliczam Poissona + czynniki v2.7...[/yellow]"),
                          console=console, transient=True) as prog2:
                prog2.add_task("", total=None)
                wynik = predict_match(
                    g, a, df_wyniki, imp_g, imp_a, heur_g, heur_a,
                    h2h_g, h2h_a_uzup, fort_g,
                    klasyfikacja=klas_m,
                )
                time.sleep(0.5)
            if wynik: wyswietl_predykcje(wynik)
            else:     console.print("[red]Za malo danych historycznych dla tej pary.[/red]")

        elif wybor == "4":
            console.print()
            g, a = wybierz_druzyny(df_wyniki)
            try:   n_f = int(Prompt.ask("Ile meczow formy?", default="8"))
            except ValueError: n_f = 8
            console.print()
            porownaj_forme(g, a, df_wyniki, n_f)

        elif wybor == "5":
            console.print()
            if df_nadchodzace is None or df_nadchodzace.empty:
                console.print("[yellow]Brak meczow z kompletna obsada.[/yellow]")
            else:
                szac_min = int(n_nad * SLEEP_KOLEJKA * 2 / 60 + 1)
                console.print(
                    f"[dim]{n_nad} meczow | sleep={SLEEP_KOLEJKA}s | "
                    f"szac. czas: ~{szac_min} min[/dim]\n"
                )
                cache_kolejki = analiza_kolejki(
                    df_nadchodzace, df_wyniki, imp, heur, h2h, fort, klas)

        elif wybor == "6":
            console.print()
            if not cache_kolejki:
                console.print("[yellow]Najpierw uruchom analize kolejki (opcja 5).[/yellow]")
                if df_nadchodzace is not None and not df_nadchodzace.empty:
                    if Confirm.ask("Przeanalizowac teraz i eksportowac?"):
                        cache_kolejki = analiza_kolejki(
                            df_nadchodzace, df_wyniki, imp, heur, h2h, fort, klas)
            if cache_kolejki:
                scz = f"FootStats_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
                with Progress(SpinnerColumn(style="blue"),
                              TextColumn("[blue]Tworzenie PDF...[/blue]"),
                              console=console, transient=True) as pg:
                    pg.add_task("", total=None)
                    sciezka = eksportuj_pdf(cache_kolejki, nazwa_ligi, df_tabela, scz)
                console.print(f"[bold green]PDF zapisany:[/bold green] [cyan]{os.path.abspath(sciezka)}[/cyan]")
            else:
                console.print("[yellow]Brak danych do eksportu.[/yellow]")

        elif wybor == "7":
            wyswietl_naglowek()
            while True:
                kod_ligi, nazwa_ligi, n_druzyn, api_id_af = wyswietl_menu_lig_v27(
                    api, sources.af if sources.apisports_ok else None)
                console.print()
                if api_id_af and sources.apisports_ok:
                    df_t2, df_w2, df_n2 = pobierz_dane_apisports(
                        sources.af, api_id_af, nazwa_ligi)
                else:
                    df_t2, df_w2, df_n2 = pobierz_dane(api, kod_ligi, nazwa_ligi)

                brak_w2 = df_w2 is None or (hasattr(df_w2, 'empty') and df_w2.empty)
                brak_t2 = df_t2 is None or (hasattr(df_t2, 'empty') and df_t2.empty)

                if brak_w2:
                    console.print(Panel(
                        f"[yellow]Brak danych dla: {nazwa_ligi}\n"
                        "[dim]Turniej moze byc zakonczony lub jeszcze nie ruszyl.[/dim][/yellow]",
                        border_style="yellow", padding=(0,2)
                    ))
                    if not Confirm.ask("[yellow]Wybrac inna lige?[/yellow]", default=True):
                        break
                    continue

                if brak_t2:
                    df_t2 = _generuj_tabele_z_wynikow(df_w2)
                    if df_t2 is None or (hasattr(df_t2,'empty') and df_t2.empty):
                        druzyny_min = sorted(set(df_w2["gospodarz"]) | set(df_w2["goscie"]))
                        df_t2 = pd.DataFrame({"Druzyna": druzyny_min, "Pkt": [0]*len(druzyny_min)})

                df_tabela, df_wyniki, df_nadchodzace = df_t2, df_w2, df_n2
                sys_anal = _reinicjuj_systemy(df_tabela, df_wyniki, n_druzyn, kod_ligi)
                cache_kolejki = []; cache_pewniaczki = []
                n_nad = len(df_nadchodzace) if df_nadchodzace is not None else 0
                console.print(f"[green]Liga: {nazwa_ligi} | {len(df_wyniki)} wynikow | {n_nad} nadchodzacych[/green]\n")
                break

        elif wybor in ("8", "p"):
            # ── PEWNIACZKI TYGODNIA (scalona opcja P) ───────────────
            console.print()
            if not bzzoiro:
                console.print("[yellow]Opcja P wymaga klucza Bzzoiro.[/yellow]")
                console.print("[dim]Dodaj BZZOIRO_KEY w opcji K.[/dim]")
            else:
                try:
                    prog_p = float(Prompt.ask(
                        "[bold green]Min. szansa %[/bold green]",
                        default=str(int(PEWNIACZEK_PROG))
                    ))
                except ValueError:
                    prog_p = PEWNIACZEK_PROG

                console.print(
                    "  [yellow]1[/yellow] Szybkie – tylko ML Bzzoiro, biezace 48h (0 req FDB)\n"
                    "  [yellow]2[/yellow] Pelne   – Poisson biezacej ligi + ML + inne ligi FDB"
                )
                tryb = Prompt.ask("[bold cyan]Tryb[/bold cyan]", default="2").strip()

                cache_pewniaczki = []
                if tryb == "1":
                    try:
                        godz_p = int(Prompt.ask("[yellow]Horyzont godzin[/yellow]", default="48"))
                    except ValueError:
                        godz_p = 48
                    with Progress(SpinnerColumn(style="yellow"),
                                  TextColumn("[yellow]Skanowanie ML...[/yellow]"),
                                  console=console, transient=True) as pg:
                        pg.add_task("", total=None)
                        cache_pewniaczki = szybkie_pewniaczki_2dni(bzzoiro, prog_p, godz_p)
                    wyswietl_szybkie_pewniaczki(cache_pewniaczki, prog_p, godz_p)
                else:
                    skanuj_inne = False
                    if sources._status.get("fdb"):
                        skanuj_inne = Confirm.ask(
                            f"[yellow]Skanowac inne ligi FDB? (~{int(10*SLEEP_LOOP//60)+1} min)[/yellow]",
                            default=True
                        )
                    with Progress(SpinnerColumn(style="green"),
                                  TextColumn("[green]{task.description}[/green]"),
                                  console=console, transient=True) as pg:
                        pg.add_task("Analizowanie...", total=None)
                        cache_pewniaczki = pewniaczki_tygodnia(
                            api, df_wyniki, df_nadchodzace, nazwa_ligi,
                            imp, heur, h2h, fort, dw, klas,
                            bzzoiro=bzzoiro,
                            skanuj_inne_ligi=skanuj_inne,
                            prog=prog_p,
                        )
                    wyswietl_pewniaczki(cache_pewniaczki, prog_p)

                if cache_pewniaczki and Confirm.ask(
                    "[bold cyan]Eksportowac do PDF?[/bold cyan]", default=True
                ):
                    scz = f"Pewniaczki_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
                    with Progress(SpinnerColumn(style="cyan"),
                                  TextColumn("[cyan]PDF...[/cyan]"),
                                  console=console, transient=True) as pg2:
                        pg2.add_task("", total=None)
                        sciezka_pdf = eksportuj_pdf_pewniaczki(cache_pewniaczki, prog_p, scz)
                    console.print(f"[bold green]PDF:[/bold green] [cyan]{os.path.abspath(sciezka_pdf)}[/cyan]")

        elif wybor == "9":
            # ── ANALIZA DOM/WYJAZD ──────────────────────────────────
            console.print()
            druzyny = sorted(set(df_wyniki["gospodarz"]) | set(df_wyniki["goscie"]))
            t_d = Table(title="[bold blue]Druzyny[/bold blue]",
                        box=box.MINIMAL, border_style="bright_black")
            for _ in range(3):
                t_d.add_column("Nr", style="dim cyan", justify="right", width=4)
                t_d.add_column("Druzyna", style="bold white", justify="left", width=16)
            for idx in range(0, len(druzyny), 3):
                wrs = []
                for j in range(3):
                    ii = idx + j
                    wrs.extend([str(ii+1), druzyny[ii]] if ii < len(druzyny) else ["",""])
                t_d.add_row(*wrs)
            console.print(t_d)

            while True:
                try:
                    nr = int(Prompt.ask("\n[bold cyan]Nr druzyny do analizy Dom/Wyjazd[/bold cyan]"))
                    if 1 <= nr <= len(druzyny): break
                except ValueError: pass
                console.print("[red]Zly numer.[/red]")
            druzyna_sel = druzyny[nr - 1]

            try:   n_dw = int(Prompt.ask("Ostatnie N meczow dom/wyjazd?", default="10"))
            except ValueError: n_dw = 10

            dw.wyswietl(druzyna_sel, n_dw)

            # Opcjonalnie porownaj z druga druzyna
            if Confirm.ask("Porownac z inna druzyna?", default=False):
                while True:
                    try:
                        nr2 = int(Prompt.ask("[bold cyan]Nr drugiej druzyny[/bold cyan]"))
                        if 1 <= nr2 <= len(druzyny) and druzyny[nr2-1] != druzyna_sel: break
                    except ValueError: pass
                    console.print("[red]Zly numer.[/red]")
                dw.wyswietl(druzyny[nr2-1], n_dw)

        elif wybor == "k":
            # ── DODAJ BRAKUJACY KLUCZ ───────────────────────────────
            console.print()
            if not sources.bzzoiro_ok:
                k = sources.dodaj_klucz_interaktywnie(ENV_BZZOIRO)
                if k:
                    sources.bzz   = BzzoiroClient(k)
                    ok, msg = sources.bzz.waliduj()
                    if ok:
                        bzzoiro = sources.bzz
                        sources._status["bzz"] = True
                        console.print(f"[bold green]Bzzoiro aktywne: {msg}[/bold green]")
                    else:
                        console.print(f"[red]Bzzoiro: {msg}[/red]")
            elif not sources.apisports_ok:
                k = sources.dodaj_klucz_interaktywnie(ENV_APISPORTS)
                if k:
                    sources.af = APIFootball(k)
                    ok, msg = sources.af.waliduj()
                    sources._status["af"] = ok
                    console.print(f"[{'bold green' if ok else 'red'}]API-Football: {msg}[/{'bold green' if ok else 'red'}]")

        elif wybor == "c":
            # ── ZARZADZANIE CACHE API-FOOTBALL ──────────────────────
            console.print()
            bud = af_budget_status()
            ci  = af_cache_info()

            t_c = Table(title="[bold yellow]Cache & Budzet API-Football[/bold yellow]",
                        box=box.ROUNDED, border_style="yellow")
            t_c.add_column("Metryka",    style="dim",        justify="right", width=22)
            t_c.add_column("Wartosc",    style="bold white", justify="left",  width=30)
            kol_b = "green" if not bud["ostrzezenie"] else ("yellow" if not bud["krytyczny"] else "red")
            t_c.add_row("Dzien",         bud["dzien"])
            t_c.add_row("Req uzyto",     f"[{kol_b}]{bud['uzyto']}/{bud['limit']}[/{kol_b}]")
            t_c.add_row("Req pozostalo", f"[{kol_b}]{bud['pozostalo']}[/{kol_b}]")
            t_c.add_row("Prog blokady",  f"{AF_BLOCK_THRESHOLD} req")
            t_c.add_row("Prog ostrz.",   f"{AF_WARN_THRESHOLD} req")
            t_c.add_row("Cache wpisy",   str(ci["wpisy"]))
            t_c.add_row("Cache rozmiar", f"{ci['rozmiar_kb']} KB")
            t_c.add_row("Cache TTL",     f"{AF_CACHE_TTL_H}h")
            t_c.add_row("Najstarszy wpis", ci["najstarszy"] or "–")
            t_c.add_row("Najnowszy wpis",  ci["najnowszy"]  or "–")
            console.print(t_c)

            # Historia ostatnich reqow
            if bud["historia"]:
                console.print("[dim]Ostatnie 5 zapytan AF:[/dim]")
                for h in bud["historia"]:
                    console.print(f"  [dim]{h['ts']}  {h['endpoint']}[/dim]")
            console.print()

            if ci["wpisy"] > 0:
                if Confirm.ask(
                    "[yellow]Wyczysc disk cache API-Football? "
                    "(dane beda pobrane ponownie przy nastepnym uzyciu)[/yellow]",
                    default=False
                ):
                    af_cache_clear()
            else:
                console.print("[dim]Cache jest pusty.[/dim]")

        elif wybor == "a":
            # ── ANALIZA KUPONU ───────────────────────────────────────
            console.print()
            _analiza_kuponu(bzzoiro)

        elif wybor in ("i",):
            # ── AI ANALIZA POJEDYNCZEGO MECZU ───────────────────────
            console.print()
            if not _ai_dostepne:
                console.print("[red]Brak modułów AI. Sprawdź ai_client.py i ai_analyzer.py.[/red]")
            else:
                g, a = wybierz_druzyny(df_wyniki)
                console.print()

                # Oblicz predykcję FootStats
                imp_g  = imp.analiza(g, df_tabela, n_druzyn, kod_ligi, datetime.now())
                imp_a  = imp.analiza(a, df_tabela, n_druzyn, kod_ligi, datetime.now())
                heur_g = heur.analiza(g, df_wyniki)
                heur_a = heur.analiza(a, df_wyniki)
                h2h_g  = h2h.analiza(g, a)
                h2h_a  = h2h.analiza(a, g)
                fort_g = fort.analiza(g)
                klas_m = klas.klasyfikuj(g, a, "REGULAR_SEASON", datetime.now(), None, None)

                with Progress(SpinnerColumn(style="yellow"),
                              TextColumn("[yellow]Obliczam Poissona...[/yellow]"),
                              console=console, transient=True) as _pg:
                    _pg.add_task("", total=None)
                    wynik_fs = predict_match(
                        g, a, df_wyniki, imp_g, imp_a, heur_g, heur_a,
                        h2h_g, h2h_a, fort_g, klasyfikacja=klas_m)

                if not wynik_fs:
                    console.print("[red]Za mało danych dla tej pary.[/red]")
                else:
                    wyswietl_predykcje(wynik_fs)

                    # Pobierz kursy z Betexplorer
                    console.print()
                    _liga_slug = Prompt.ask(
                        "[dim]Liga dla kursów bukmacherskich (Enter=pomiń)[/dim]",
                        default=""
                    ).strip()
                    _kursy = None
                    if _liga_slug:
                        with Progress(SpinnerColumn(style="cyan"),
                                      TextColumn("[cyan]Pobieram kursy...[/cyan]"),
                                      console=console, transient=True) as _pg2:
                            _pg2.add_task("", total=None)
                            try:
                                _kursy = _kursy_ai(g, a, _liga_slug)
                            except Exception as _e:
                                console.print(f"[yellow]Kursy niedostępne: {_e}[/yellow]")

                    # Pobierz formę jako string
                    def _forma_str(druz, n=5):
                        try:
                            df_f = df_wyniki[
                                (df_wyniki["gospodarz"]==druz) | (df_wyniki["goscie"]==druz)
                            ].tail(n)
                            wyniki = []
                            for _, r in df_f.iterrows():
                                if r["gospodarz"] == druz:
                                    wyniki.append("W" if r["gole_g"]>r["gole_a"] else ("R" if r["gole_g"]==r["gole_a"] else "P"))
                                else:
                                    wyniki.append("W" if r["gole_a"]>r["gole_g"] else ("R" if r["gole_g"]==r["gole_a"] else "P"))
                            return "".join(wyniki)
                        except Exception:
                            return "-"

                    _h2h_opis = wynik_fs["h2h_g"].get("opis", "-") or "-"

                    with Progress(SpinnerColumn(style="yellow"),
                                  TextColumn("[yellow]🤖 AI analizuje mecz...[/yellow]"),
                                  console=console, transient=True) as _pg3:
                        _pg3.add_task("", total=None)
                        _wynik_ai = _analizuj_ai(
                            gospodarz          = g,
                            goscie             = a,
                            p_wygrana          = wynik_fs["p_wygrana"],
                            p_remis            = wynik_fs["p_remis"],
                            p_przegrana        = wynik_fs["p_przegrana"],
                            btts               = wynik_fs["btts"],
                            over25             = wynik_fs["over25"],
                            forma_g            = _forma_str(g),
                            forma_a            = _forma_str(a),
                            h2h_opis           = _h2h_opis,
                            pewnosc_modelu     = wynik_fs.get("pewnosc", 0),
                            komentarz_footstats= komentarz_analityka(wynik_fs),
                            kursy              = _kursy,
                        )
                    _pokaz_ai(_wynik_ai)

        elif wybor in ("j",):
            # ── AI ANALIZA CAŁEJ KOLEJKI ─────────────────────────────
            console.print()
            if not _ai_dostepne:
                console.print("[red]Brak modułów AI.[/red]")
            elif df_nadchodzace is None or df_nadchodzace.empty:
                console.print("[yellow]Brak nadchodzących meczów. Najpierw wybierz ligę (opcja 7).[/yellow]")
            else:
                if not cache_kolejki:
                    console.print("[yellow]Najpierw uruchom analizę kolejki (opcja 5) dla pełnych danych.[/yellow]")
                    if not Confirm.ask("Kontynuować z uproszczoną analizą?", default=True):
                        pass
                    else:
                        cache_kolejki = analiza_kolejki(
                            df_nadchodzace, df_wyniki, imp, heur, h2h, fort, klas)

                if cache_kolejki:
                    _liga_slug_j = Prompt.ask(
                        "[dim]Liga dla kursów bukmacherskich (Enter=pomiń)[/dim]",
                        default=""
                    ).strip()

                    console.print(f"[cyan]Analizuję {len(cache_kolejki)} meczów z AI...[/cyan]")
                    _wyniki_ai_j = []
                    for _i, _m in enumerate(cache_kolejki, 1):
                        _g = _m.get("gospodarz", "")
                        _a = _m.get("gosc", "")
                        console.print(f"  [{_i}/{len(cache_kolejki)}] {_g} vs {_a}")
                        _k = None
                        if _liga_slug_j:
                            try:
                                _k = _kursy_ai(_g, _a, _liga_slug_j)
                            except Exception:
                                pass
                        try:
                            _wyn = _analizuj_ai(
                                gospodarz      = _g,
                                goscie         = _a,
                                p_wygrana      = _m.get("p_wygrana", 33),
                                p_remis        = _m.get("p_remis", 33),
                                p_przegrana    = _m.get("p_przegrana", 34),
                                btts           = _m.get("btts", 0),
                                over25         = _m.get("over25", 0),
                                pewnosc_modelu = _m.get("pewnosc", 0),
                                komentarz_footstats = _m.get("komentarz", ""),
                                kursy          = _k,
                            )
                            _pokaz_ai(_wyn)
                            _wyniki_ai_j.append(_wyn)
                        except Exception as _e:
                            console.print(f"  [red]Błąd AI dla {_g} vs {_a}: {_e}[/red]")

                    if _wyniki_ai_j:
                        import json as _json
                        _plik_ai = f"ai_kolejka_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
                        Path(_plik_ai).write_text(
                            _json.dumps(_wyniki_ai_j, ensure_ascii=False, indent=2),
                            encoding="utf-8"
                        )
                        console.print(f"[green]Zapisano: {_plik_ai}[/green]")

        elif wybor == "0":
            console.print(f"\n[bold blue]Do zobaczenia! FootStats {VERSION}[/bold blue]\n")
            break

        console.print()


if __name__ == "__main__":
    main()
