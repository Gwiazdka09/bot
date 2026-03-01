"""
████████╗ ██████╗  ██████╗ ████████╗███████╗████████╗ █████╗ ████████╗███████╗
██╔════╝██╔═══██╗██╔═══██╗╚══██╔══╝██╔════╝╚══██╔══╝██╔══██╗╚══██╔══╝██╔════╝
█████╗  ██║   ██║██║   ██║   ██║   ███████╗   ██║   ███████║   ██║   ███████╗
██╔══╝  ██║   ██║██║   ██║   ██║   ╚════██║   ██║   ██╔══██║   ██║   ╚════██║
██║     ╚██████╔╝╚██████╔╝   ██║   ███████║   ██║   ██║  ██║   ██║   ███████║
╚═╝      ╚═════╝  ╚═════╝    ╚═╝   ╚══════╝   ╚═╝   ╚═╝  ╚═╝   ╚═╝   ╚══════╝

  FootStats v2.5 Psychology & History
  Poisson | H2H 24mth | Patent/Zemsta | Home Fortress | Importance 2.0
  Confidence Meter | Dynamic Menu | Fatigue/Rotation | Rate-Limit Guard | PDF | .env

INSTALACJA:
  pip install requests pandas scipy rich reportlab python-dotenv

CZCIONKA PDF (polskie znaki):
  Pobierz DejaVuSans.ttf z https://dejavu-fonts.github.io/
  i umies w tym samym folderze co footstats.py

ZMIANY v2.5 (Psychology & History):
  1. AnalizaH2H - filtr 24 mies., Patent (dominacja) +10%, Zemsta 3+ goli +15%
  2. HomeFortress - seria 5 meczow bez porazki u siebie -> obrona +10%
  3. ImportanceIndex 2.0 - prog 5 kolejek, miejsca 1-3 i spadek +20%, wakacje -10%
  4. ConfidenceMeter - pewnosc typu wg swiezosci danych H2H (0-100%)
  5. Optymalizacja API - sleep przy H2H, komunikat 429, cache sesji
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
VERSION         = "v2.5 Psychology & History"
MAX_GOLE        = 8
OSTATNIE_N      = 15
BONUS_DOMOWY    = 1.15
SLEEP_KOLEJKA   = 6.0    # pauza miedzy meczami kolejki (10 req/min)
SLEEP_LOOP      = 6.0    # pauza miedzy zapytaniami w petli pobierania
CACHE_TTL_MIN   = 30     # cache wazny 30 minut

ROTACJA_DNI     = 4      # mecz CL w ciagu N dni -> rotacja skladu
ROTACJA_KARA    = 0.80   # atak -20%
ZMECZ_GODZ      = 72     # poprzedni mecz < 72h -> zmeczenie
ZMECZ_KARA_OBR  = 0.85   # obrona -15% (wiecej straconych goli)
ZEMSTA_MIN_GOLE = 3      # min. roznica goli w H2H -> zemsta
ZEMSTA_BONUS    = 1.15   # atak +15%

# ── v2.5 NOWE STALE ────────────────────────────────────────────────
H2H_OKNO_DNI       = 730  # filtr H2H: bierz tylko mecze z ostatnich 24 miesiecy (2*365)
H2H_MIN_MECZE      = 2    # min. liczba meczow H2H do aktywacji bonusu Patent
PATENT_BONUS       = 1.10 # dominacja w H2H (wszystkie wygrane): przesuniecie szans +10%
FORTRESS_MECZE     = 5    # seria meczow bez porazki u siebie -> Home Fortress
FORTRESS_BONUS_OBR = 1.10 # obrona gospodarz +10%
IMP2_PROG_FINAL    = 5    # Importance 2.0: zostalo <= N kolejek -> "tryb finalny"
IMP2_BONUS_FINAL   = 1.20 # miejsca 1-3 i zagrozeni spadkiem: atak +20%
IMP2_WAKACJE       = 0.90 # srodek tabeli w "trybie finalnym": wydajnosc -10%
CONFIDENCE_H2H_MAX = 5    # liczba swiezych meczow H2H = 100% pewnosci

# ================================================================
#  MODUL 0 - BEZPIECZENSTWO
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
    _stworz_gitignore()
    if not ENV_FILE.exists():
        console.print(Panel(
            "[bold yellow]Nie znaleziono pliku .env![/bold yellow]\n\n"
            "Klucz API bedzie przechowywany bezpiecznie w [cyan].env[/cyan]\n"
            "(wykluczonym z Git).\n\n"
            "Darmowy klucz: [bold]https://www.football-data.org/client/register[/bold]",
            border_style="yellow", title="Pierwsze uruchomienie", padding=(1, 3)
        ))
        klucz = Prompt.ask("[bold cyan]Wpisz klucz API football-data.org[/bold cyan]").strip()
        ENV_FILE.write_text(f'FOOTBALL_API_KEY="{klucz}"\n', encoding="utf-8")
        console.print(f"[green]Zapisano: {ENV_FILE.resolve()}[/green]\n")
    load_dotenv(ENV_FILE)
    klucz = os.getenv("FOOTBALL_API_KEY", "").strip().strip('"').strip("'")
    if not klucz:
        console.print("[red]Klucz API pusty w .env.[/red]")
        klucz = Prompt.ask("[bold cyan]Wpisz klucz API[/bold cyan]").strip()
        set_key(str(ENV_FILE), "FOOTBALL_API_KEY", klucz)
    return klucz

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
    s = str(data_str)
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:len(fmt)], fmt)
        except ValueError:
            continue
    return None

# ================================================================
#  MODUL 3 - HTTP + CACHE + RATE GUARD
# ================================================================

_API_CACHE: dict = {}
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

def _cache_get(klucz: str):
    wpis = _API_CACHE.get(klucz)
    if wpis:
        delta = (datetime.now() - wpis["ts"]).total_seconds()
        if delta < CACHE_TTL_MIN * 60:
            console.print(f"[dim cyan]Cache HIT [{int(delta//60)}min]: {klucz[:55]}[/dim cyan]")
            return wpis["data"]
    return None

def _cache_set(klucz: str, dane):
    _API_CACHE[klucz] = {"ts": datetime.now(), "data": dane}

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
#  MODUL 5 - IMPORTANCE INDEX 2.0 (v2.5)
# ================================================================

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

def _korekta_dwumecz(lg, la, first_leg_g, first_leg_a, jest_gospodarzem_1: bool):
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
) -> dict | None:
    """
    Kompletna predykcja z:
      1. Wazona forma historyczna
      2. Importance Index 2.0 (motywacja + tryb finalny)
      3. Heurystyka zmeczenia/rotacji (v2.4)
      4. AnalizaH2H: Patent +10%, Zemsta +15% (v2.5)
      5. HomeFortress: twierdza domowa +10% obrona (v2.5)
      6. Logika dwumeczu (knockout)
    Zwraca dict z pelna analiza lub None jesli za malo danych.
    """
    importance_g = importance_g or {"bonus_atak": 1.0, "komentarz": ""}
    importance_a = importance_a or {"bonus_atak": 1.0, "komentarz": ""}
    heurystyka_g = heurystyka_g or {"mnoznik_atak": 1.0, "mnoznik_obr": 1.0, "opis": ""}
    heurystyka_a = heurystyka_a or {"mnoznik_atak": 1.0, "mnoznik_obr": 1.0, "opis": ""}
    h2h_g        = h2h_g        or {"mnoznik_atak": 1.0, "mnoznik_szans": 1.0, "opis": "", "pewnosc": 20, "n_h2h": 0}
    h2h_a        = h2h_a        or {"mnoznik_atak": 1.0, "mnoznik_szans": 1.0, "opis": "", "pewnosc": 20, "n_h2h": 0}
    fortress_g   = fortress_g   or {"bonus_obrona": 1.0, "fortress": False, "opis": ""}

    maska = (
        (df_mecze["gospodarz"] == g) | (df_mecze["goscie"] == g) |
        (df_mecze["gospodarz"] == a) | (df_mecze["goscie"] == a)
    )
    df_f = df_mecze[maska].tail(OSTATNIE_N)
    if len(df_f) < 4:
        return None

    sily, srednia = _oblicz_sile_wazona(df_f)
    if g not in sily or a not in sily:
        return None

    sg, sa = sily[g], sily[a]

    # Lambda z WSZYSTKIMI czynnikami v2.5
    # fortress_g["bonus_obrona"] > 1 → gospodarz broni sie lepiej (goscie strzelaja mniej)
    lambda_g = max(0.05,
        sg["atak"]
        * sa["obrona"]
        * srednia
        * BONUS_DOMOWY
        * importance_g["bonus_atak"]
        * heurystyka_g["mnoznik_atak"]
        * h2h_g["mnoznik_atak"]           # Zemsta/Patent H2H
        / heurystyka_a["mnoznik_obr"]     # zmeczenie obrony goscia
    )
    lambda_a = max(0.05,
        sa["atak"]
        * sg["obrona"]
        * srednia
        * importance_a["bonus_atak"]
        * heurystyka_a["mnoznik_atak"]
        * h2h_a["mnoznik_atak"]           # Zemsta/Patent H2H gosci
        / heurystyka_g["mnoznik_obr"]     # zmeczenie obrony gosp.
        / fortress_g["bonus_obrona"]      # 🏰 HomeFortress: goscie dostaja trudniej strzelac
    )

    # Korekta szans Patent (przesuniecie w macierzy prawdopodobienstw)
    patent_mnoznik_g = h2h_g.get("mnoznik_szans", 1.0)
    patent_mnoznik_a = h2h_a.get("mnoznik_szans", 1.0)
    lambda_g *= patent_mnoznik_g
    lambda_a *= patent_mnoznik_a

    # Zabezpieczenie
    lambda_g = max(0.05, lambda_g)
    lambda_a = max(0.05, lambda_a)

    # Korekta rewanzowa
    korekta_opis = ""
    jest_knockout = _czy_knockout(stage)
    if jest_knockout and first_leg_g is not None:
        lambda_g, lambda_a, korekta_opis = _korekta_dwumecz(
            lambda_g, lambda_a, first_leg_g, first_leg_a, jest_gospodarzem_1=False)

    # Macierz Poissona
    N = MAX_GOLE + 1
    M = np.zeros((N, N))
    for i in range(N):
        for j in range(N):
            M[i][j] = poisson.pmf(i, lambda_g) * poisson.pmf(j, lambda_a)

    pw  = float(np.sum(np.tril(M, -1)))
    pr  = float(np.sum(np.diag(M)))
    pp  = float(np.sum(np.triu(M,  1)))
    suma = pw + pr + pp or 1.0
    pw /= suma; pr /= suma; pp /= suma

    btts   = (1 - poisson.pmf(0, lambda_g)) * (1 - poisson.pmf(0, lambda_a))
    over25 = 1.0 - sum(M[i][j] for i in range(N) for j in range(N) if i+j <= 2)
    over25 = min(over25 / suma, 1.0)

    idx  = np.unravel_index(np.argmax(M), M.shape)
    flat = sorted([(M[i][j], i, j) for i in range(N) for j in range(N)], reverse=True)
    top5 = [(f"{i}:{j}", round(p*100, 1)) for p, i, j in flat[:5]]

    # Confidence Meter – laczna pewnosc z H2H i danych ogolnych
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
        "korekta_opis": korekta_opis,
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
#  MODUL 14 - ANALIZA KOLEJKI
# ================================================================

def analiza_kolejki(
    df_nad: pd.DataFrame,
    df_wyk: pd.DataFrame,
    importance_idx: ImportanceIndex,
    heurystyka_eng: HeurystaZmeczeniaRotacji,
    h2h_sys: AnalizaH2H,
    fortress_sys: HomeFortress,
) -> list:
    """
    Analizuje wszystkie nadchodzace mecze z pelnym zestawem czynnikow v2.5:
      - Importance Index 2.0 (tryb finalny 5 kolejek)
      - Heurystyka zmeczenia/rotacji
      - AnalizaH2H (Patent + Zemsta, filtr 24 mies.)
      - HomeFortress (twierdza domowa)
      - Confidence Meter (kolumna Pewnosc %)
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
    t.add_column("Data",      style="dim",          justify="center", width=11)
    t.add_column("Gospodarz", style="bold white",   justify="right",  width=14)
    t.add_column("Goscie",    style="bold white",   justify="left",   width=14)
    t.add_column("Typ.wyn.",  style="bold yellow",  justify="center", width=7)
    t.add_column("1",         style="green",        justify="center", width=5)
    t.add_column("X",         style="yellow",       justify="center", width=5)
    t.add_column("2",         style="red",          justify="center", width=5)
    t.add_column("BTTS",      style="cyan",         justify="center", width=8)
    t.add_column("Ov2.5",     style="magenta",      justify="center", width=6)
    t.add_column("Czynniki",  style="bold",         justify="left",   width=18)
    t.add_column("Pewnosc",   style="bold cyan",    justify="center", width=8)

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
                          "-","-","-","-","-","[dim]-[/dim]","–")
                continue

            # Wszystkie systemy analityczne v2.5
            imp_g    = importance_idx.analiza(g)
            imp_a    = importance_idx.analiza(a)
            heur_g   = heurystyka_eng.analiza(g, data_full)
            heur_a   = heurystyka_eng.analiza(a, data_full)
            # H2H z sleep – ochrona limitu 10 req/min
            h2h_g    = h2h_sys.analiza(g, a)
            time.sleep(SLEEP_KOLEJKA)
            h2h_a    = h2h_sys.analiza(a, g)
            fort_g   = fortress_sys.analiza(g)

            wynik = predict_match(
                g, a, df_wyk,
                imp_g, imp_a,
                heur_g, heur_a,
                h2h_g, h2h_a,
                fort_g,
                flg, fla, stage
            )

            # Kolumna ikon czynnikow
            ikony = (
                heur_g.get("ikony","") +
                heur_a.get("ikony","") +
                h2h_g.get("ikona","") +
                h2h_a.get("ikona","") +
                fort_g.get("ikona","")
            )
            # Nie duplikuj ikon identycznych (np. dwa ⚔️)
            czynniki = (ikony + " " + imp_g["label_plain"][:9]).strip() or "–"

            if wynik:
                wyniki.append({"mecz": mecz, "predykcja": wynik})
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
                    f"[{kp}]{pewnosc}%[/{kp}]",
                )
            else:
                t.add_row(data_str, g, a, "[dim]brak danych[/dim]",
                          "-","-","-","-","-","[dim]-[/dim]","–")

            # Sleep po kazdej parze (nie tylko na koncu) – juz uwzgledniamy sleep H2H wyzej
            if i < n - 1:
                time.sleep(SLEEP_KOLEJKA)

    console.print(t)
    console.print(
        "\n[dim]Legenda: 🔄 Rotacja/CL | 😫 Zmeczenie <72h | ⚔️ Zemsta H2H | 🏅 Patent H2H | "
        "🏰 Twierdza | 🏆👑 High Stakes | 🆘 Spadek | 🏖️  Wakacje[/dim]\n"
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
        f"Model: Poisson + Importance + Fatigue/Rotation + H2H Revenge{note}"
    ), s_sub))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#1a5276"), spaceAfter=8))

    # Tabela zbiorcza
    story.append(Paragraph(_pdf("Przeglad Kolejki"), s_h1))
    nagl  = [_pdf(x) for x in ["Data","Gospodarz","Goscie","Typ","1%","X%","2%","BTTS","Ov2.5","Czynniki"]]
    dane_t = [nagl]
    for wpis in wyniki_kolejki:
        m, w = wpis["mecz"], wpis["predykcja"]
        ikony = (w.get("heur_g",{}).get("ikony","") + w.get("heur_a",{}).get("ikony","") +
                 w.get("zemsta_g",{}).get("ikona","") + w.get("zemsta_a",{}).get("ikona",""))
        cz = _pdf((ikony + " " + w.get("imp_g",{}).get("label_plain",""))[:14].strip())
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
            cz,
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
    widths = [1.8*cm,2.4*cm,2.4*cm,1.4*cm,1*cm,1*cm,1*cm,1.8*cm,1.8*cm,2*cm]
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
        blok.append(Paragraph(_pdf(f"{_s(m.get('data','-'))}  |  {g}  vs  {a}"), s_h2))
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
        f"FootStats {VERSION}  |  Poisson + Importance + Fatigue/Rotation + H2H Revenge + Two-Leg  |  "
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
    t.append("\n  Poisson | Dynamic Menu | Rotation | Fatigue | Revenge | Cache | PDF | .env  \n", style="dim")
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

    # Zbierz wszystkie aktywne ikony czynnikow v2.5
    ikony = ""
    for k in ["heur_g","heur_a"]:   ikony += wynik.get(k,{}).get("ikony","")
    for k in ["h2h_g","h2h_a"]:     ikony += wynik.get(k,{}).get("ikona","")
    fort_ikona = wynik.get("fortress_g",{}).get("ikona","")
    if fort_ikona: ikony += fort_ikona

    nt = Text(justify="center")
    nt.append(f"\n  {g}  ", style="bold white")
    nt.append(f"  {wynik['wynik_g']} : {wynik['wynik_a']}  ", style="bold yellow on blue")
    nt.append(f"  {a}  \n", style="bold white")
    if wynik.get("knockout"):
        nt.append("\n  [REWANZ – Faza Pucharowa]  \n", style="bold magenta")
    if ikony.strip():
        nt.append(f"\n  Czynniki v2.5: {ikony.strip()}  \n", style="bold cyan")
    # Confidence Meter w naglowku
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


# ================================================================
#  MODUL 18 - GLOWNA PETLA
# ================================================================

def main():
    api_key = _wczytaj_lub_stworz_env()
    _zarejestruj_font()
    wyswietl_naglowek()
    api = APIClient(api_key)

    # Dynamiczne menu lig
    kod_ligi, nazwa_ligi, n_druzyn = wyswietl_menu_lig(api)
    console.print()

    df_tabela, df_wyniki, df_nadchodzace = pobierz_dane(api, kod_ligi, nazwa_ligi)

    if df_tabela is None or df_wyniki is None:
        console.print("[red]Blad pobierania danych. Sprawdz klucz API i internet.[/red]")
        sys.exit(1)

    importance     = ImportanceIndex(df_tabela, n_druzyn)
    heurystyka_eng = HeurystaZmeczeniaRotacji(df_wyniki)
    h2h_sys        = AnalizaH2H(df_wyniki)
    fortress_sys   = HomeFortress(df_wyniki)

    n_nad = len(df_nadchodzace) if df_nadchodzace is not None else 0
    console.print(
        f"[green]OK: {len(df_wyniki)} wynikow | {len(df_tabela)} druzyn | "
        f"{n_nad} nadchodzacych – {nazwa_ligi}[/green]\n"
    )
    console.print(
        f"[dim]Plan FREE: 10 req/min | pauza {SLEEP_KOLEJKA}s miedzy meczami kolejki[/dim]\n"
    )

    cache_kolejki: list = []

    while True:
        console.rule(f"[bold blue]MENU  FootStats {VERSION}[/bold blue]")
        console.print("[bold]1[/bold]  Tabela ligowa  [dim](Importance 2.0 – tryb finalny 5 kolejek)[/dim]")
        console.print("[bold]2[/bold]  Ostatnie wyniki")
        console.print("[bold]3[/bold]  Predykcja meczu  [dim](+ ⚔️🏅🏰 H2H/Patent/Fortress + Pewnosc %)[/dim]")
        console.print("[bold]4[/bold]  Porownanie formy  [dim](H2H 24 mies. + historia)[/dim]")
        console.print("[bold]5[/bold]  Analiza kolejki  [dim](cala kolejka + Pewnosc % v2.5)[/dim]")
        console.print("[bold]6[/bold]  Eksport PDF  [dim](raport z komentarzem analityka)[/dim]")
        console.print("[bold]7[/bold]  Zmien lige")
        console.print("[bold]0[/bold]  Wyjscie\n")

        wybor = Prompt.ask("[bold yellow]Twoj wybor[/bold yellow]",
                           choices=["0","1","2","3","4","5","6","7"], default="1")

        if wybor == "1":
            console.print()
            wyswietl_tabele(df_tabela, nazwa_ligi, importance)

        elif wybor == "2":
            console.print()
            try:   ile = int(Prompt.ask("Ile meczow?", default="10"))
            except ValueError: ile = 10
            wyswietl_wyniki(df_wyniki, ile)

        elif wybor == "3":
            console.print()
            g, a     = wybierz_druzyny(df_wyniki)
            imp_g    = importance.analiza(g)
            imp_a    = importance.analiza(a)
            data_now = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
            heur_g   = heurystyka_eng.analiza(g, data_now)
            heur_a   = heurystyka_eng.analiza(a, data_now)
            console.print(f"[dim]Obliczam H2H (24 mies.) dla {g} vs {a}...[/dim]")
            h2h_g    = h2h_sys.analiza(g, a)
            time.sleep(SLEEP_LOOP)
            h2h_a    = h2h_sys.analiza(a, g)
            fort_g   = fortress_sys.analiza(g)

            # Zestawienie aktywnych czynnikow
            ikony = (heur_g["ikony"] + heur_a["ikony"] +
                     h2h_g["ikona"] + h2h_a["ikona"] +
                     fort_g.get("ikona",""))
            console.print(f"[dim]Analiza: {g} vs {a}[/dim]")
            if ikony.strip():
                console.print(f"[dim]Czynniki v2.5: {ikony.strip()}[/dim]")
            console.print(f"[dim]Pewnosc H2H: G={h2h_g['pewnosc']}% | A={h2h_a['pewnosc']}%[/dim]")
            console.print()
            with Progress(SpinnerColumn(style="yellow"),
                          TextColumn("[yellow]Obliczam Poissona + wszystkie czynniki v2.5...[/yellow]"),
                          console=console, transient=True) as prog:
                prog.add_task("", total=None)
                wynik = predict_match(
                    g, a, df_wyniki,
                    imp_g, imp_a,
                    heur_g, heur_a,
                    h2h_g, h2h_a,
                    fort_g
                )
                time.sleep(0.5)
            if wynik: wyswietl_predykcje(wynik)
            else:     console.print("[red]Za malo danych historycznych dla tej pary.[/red]")

        elif wybor == "4":
            console.print()
            g, a = wybierz_druzyny(df_wyniki)
            try:   n = int(Prompt.ask("Ile meczow formy?", default="8"))
            except ValueError: n = 8
            console.print()
            porownaj_forme(g, a, df_wyniki, n)

        elif wybor == "5":
            console.print()
            if df_nadchodzace is None or df_nadchodzace.empty:
                console.print("[yellow]Brak meczow z kompletna obsada.[/yellow]")
            else:
                # H2H sleep: 2x SLEEP_KOLEJKA per mecz (analiza G + analiza A)
                szac_min = int(n_nad * SLEEP_KOLEJKA * 2 / 60 + 1)
                console.print(
                    f"[dim]{n_nad} meczow | H2H sleep={SLEEP_KOLEJKA}s per zapytanie | "
                    f"szac. czas: ~{szac_min} min[/dim]\n"
                )
                cache_kolejki = analiza_kolejki(
                    df_nadchodzace, df_wyniki,
                    importance, heurystyka_eng,
                    h2h_sys, fortress_sys
                )

        elif wybor == "6":
            console.print()
            if not cache_kolejki:
                console.print("[yellow]Najpierw uruchom analize kolejki (opcja 5).[/yellow]")
                if df_nadchodzace is not None and not df_nadchodzace.empty:
                    if Confirm.ask("Przeanalizowac teraz i eksportowac?"):
                        cache_kolejki = analiza_kolejki(
                            df_nadchodzace, df_wyniki,
                            importance, heurystyka_eng,
                            h2h_sys, fortress_sys
                        )
            if cache_kolejki:
                scz = f"FootStats_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
                with Progress(SpinnerColumn(style="blue"),
                              TextColumn("[blue]Tworzenie PDF...[/blue]"),
                              console=console, transient=True) as prog:
                    prog.add_task("", total=None)
                    sciezka = eksportuj_pdf(cache_kolejki, nazwa_ligi, df_tabela, scz)
                console.print(f"[bold green]PDF zapisany:[/bold green] [cyan]{os.path.abspath(sciezka)}[/cyan]")
            else:
                console.print("[yellow]Brak danych do eksportu.[/yellow]")

        elif wybor == "7":
            wyswietl_naglowek()
            kod_ligi, nazwa_ligi, n_druzyn = wyswietl_menu_lig(api)
            console.print()
            df_tabela, df_wyniki, df_nadchodzace = pobierz_dane(api, kod_ligi, nazwa_ligi)
            if df_tabela is not None and df_wyniki is not None:
                importance     = ImportanceIndex(df_tabela, n_druzyn)
                heurystyka_eng = HeurystaZmeczeniaRotacji(df_wyniki)
                h2h_sys        = AnalizaH2H(df_wyniki)
                fortress_sys   = HomeFortress(df_wyniki)
                cache_kolejki  = []
                n_nad = len(df_nadchodzace) if df_nadchodzace is not None else 0
                console.print(f"[green]Liga: {nazwa_ligi} | {n_nad} nadchodzacych[/green]\n")
            else:
                console.print("[red]Blad pobierania danych.[/red]")

        elif wybor == "0":
            console.print(f"\n[bold blue]Do zobaczenia! FootStats {VERSION}[/bold blue]\n")
            break

        console.print()


if __name__ == "__main__":
    main()
