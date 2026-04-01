import requests
from datetime import datetime
from dotenv import set_key
from footstats.scrapers.football_data import APIClient
from footstats.scrapers.api_football import APIFootball
from footstats.scrapers.bzzoiro import BzzoiroClient
from footstats.utils.console import console
from footstats.utils.cache import (
    af_budget_status, af_cache_info,
    AF_WARN_THRESHOLD, AF_BLOCK_THRESHOLD,
)
from footstats.config import (
    ENV_FOOTBALL, ENV_APISPORTS, ENV_BZZOIRO, VERSION,
    CACHE_TTL_MIN, ENV_FILE,
)
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt
from rich import box

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
            from dotenv import load_dotenv
            load_dotenv(ENV_FILE, override=True)
            return k
        return None

    @property
    def bzzoiro_ok(self) -> bool:
        return self._status.get("bzz", False)

    @property
    def apisports_ok(self) -> bool:
        return self._status.get("af", False)
