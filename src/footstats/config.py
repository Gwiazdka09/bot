import os
from pathlib import Path
from dotenv import load_dotenv, set_key
from footstats.utils.console import console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

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
AGENT_KANDYDAT_PROG = 0.55 # prog pewnosci dla daily_agent (nizszy niz PEWNIACZEK_PROG zeby dac Groq wiecej opcji)
AGENT_BANKROLL      = 100.0 # bankroll do Kelly Criterion (PLN)
AGENT_KELLY_FRACTION = 4    # bezpieczny fractional Kelly: f*/4 (bardziej konserwatywny dla 100 PLN)

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
