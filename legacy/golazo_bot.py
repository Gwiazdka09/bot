"""
GOLAZO BOT - Predyktor Wynikow Pilkarskich
Model Rokladu Poissona | football-data.org API

INSTRUKCJA INSTALACJI (Windows 11 - CMD lub PowerShell):
1. Sprawdz wersje Pythona:
       python --version
2. Zainstaluj wymagane biblioteki:
       pip install requests pandas scipy rich
3. Zdobadz darmowy klucz API:
   - Wejdz na: https://www.football-data.org/client/register
   - Zarejestruj sie (darmowy plan - 10 zapytan/min)
   - Skopiuj klucz z e-maila i wklej go ponizej w zmienna API_KEY
4. Uruchom skrypt:
       python golazo_bot.py
"""

import sys
import time
import requests
import pandas as pd
from scipy.stats import poisson
import numpy as np
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.prompt import Prompt
from rich.text import Text
from rich import box
from rich.columns import Columns
from rich.align import Align

# =============================================================
#   WPISZ TUTAJ SWOJ KLUCZ API
# =============================================================
import os; from dotenv import load_dotenv; load_dotenv(".env")
API_KEY = os.getenv("FOOTBALL_API_KEY", "")

# Dostepne ligi (kody z football-data.org)
LIGI = {
    "1": {"nazwa": "Premier League (Anglia)",  "kod": "PL",  "emoji": "[EN]"},
    "2": {"nazwa": "La Liga (Hiszpania)",       "kod": "PD",  "emoji": "[ES]"},
    "3": {"nazwa": "Bundesliga (Niemcy)",       "kod": "BL1", "emoji": "[DE]"},
    "4": {"nazwa": "Serie A (Wlochy)",          "kod": "SA",  "emoji": "[IT]"},
    "5": {"nazwa": "Ligue 1 (Francja)",         "kod": "FL1", "emoji": "[FR]"},
    "6": {"nazwa": "Ekstraklasa (Polska)",      "kod": "PPL", "emoji": "[PL]"},
    "7": {"nazwa": "Champions League",          "kod": "CL",  "emoji": "[CL]"},
    "8": {"nazwa": "Eredivisie (Holandia)",     "kod": "DED", "emoji": "[NL]"},
}

# Stale konfiguracyjne
BASE_URL       = "https://api.football-data.org/v4"
HEADERS        = {"X-Auth-Token": API_KEY}
MAX_GOLE_SYMUL = 8   # Maks. liczba goli w macierzy Poissona
OSTATNIE_N     = 30  # Ile ostatnich meczow pobierac na druzyne

console = Console()


# =============================================================
#   MODUL 1 - POBIERANIE DANYCH Z API
# =============================================================

def _get(endpoint, params=None):
    """Pomocnicza funkcja wykonujaca zapytanie GET do football-data.org."""
    url = f"{BASE_URL}{endpoint}"
    try:
        r = requests.get(url, headers=HEADERS, params=params, timeout=15)
        if r.status_code == 200:
            return r.json()
        elif r.status_code == 429:
            # Przekroczono limit - poczekaj 60 sekund
            console.print("[yellow]Limit zapytan API. Czekam 60 sekund...[/yellow]")
            time.sleep(60)
            return _get(endpoint, params)
        elif r.status_code == 403:
            console.print("[red]Blad 403: Nieprawidlowy klucz API lub liga niedostepna w planie.[/red]")
            return None
        else:
            console.print(f"[red]Blad HTTP {r.status_code}[/red]")
            return None
    except requests.exceptions.ConnectionError:
        console.print("[red]Brak polaczenia z internetem.[/red]")
        return None
    except requests.exceptions.Timeout:
        console.print("[red]Timeout - serwer nie odpowiada.[/red]")
        return None


def pobierz_tabele(kod_ligi):
    """Pobiera aktualna tabele ligowa i zwraca jako pandas DataFrame."""
    dane = _get(f"/competitions/{kod_ligi}/standings")
    if not dane:
        return None

    # standings[0] = tabela TOTAL (laczone wyniki domowe i wyjezdne)
    wiersze = []
    for wpis in dane["standings"][0]["table"]:
        wiersze.append({
            "Poz.":    wpis["position"],
            "Druzyna": wpis["team"]["shortName"],
            "M":       wpis["playedGames"],
            "W":       wpis["won"],
            "R":       wpis["draw"],
            "P":       wpis["lost"],
            "Bramki":  f"{wpis['goalsFor']}:{wpis['goalsAgainst']}",
            "+/-":     wpis["goalDifference"],
            "Pkt":     wpis["points"],
        })
    return pd.DataFrame(wiersze)


def pobierz_wyniki(kod_ligi, limit=100):
    """
    Pobiera ostatnie rozegrane mecze z ligi.
    Zwraca DataFrame: data, gospodarz, goscie, gole_g, gole_a
    """
    dane = _get(
        f"/competitions/{kod_ligi}/matches",
        params={"status": "FINISHED", "limit": limit}
    )
    if not dane:
        return None

    mecze = []
    for m in dane.get("matches", []):
        ft = m.get("score", {}).get("fullTime", {})
        gole_g = ft.get("home")
        gole_a = ft.get("away")
        if gole_g is None or gole_a is None:
            continue
        mecze.append({
            "data":      m["utcDate"][:10],
            "gospodarz": m["homeTeam"]["shortName"],
            "goscie":    m["awayTeam"]["shortName"],
            "gole_g":    int(gole_g),
            "gole_a":    int(gole_a),
        })
    return pd.DataFrame(mecze) if mecze else None


# =============================================================
#   MODUL 2 - MODEL STATYSTYCZNY (ROZKLAD POISSONA)
# =============================================================

def _oblicz_sile_druzyn(df_mecze):
    """
    Oblicza wspolczynniki sily ataku i obrony dla kazdej druzyny.

    Metoda:
      sila_ataku(X)  = srednia_goli_X / srednia_ligi
      sila_obrony(X) = srednia_straconych_X / srednia_ligi

    Wspolczynnik > 1.0 = powyzej sredniej ligi
    Wspolczynnik < 1.0 = ponizej sredniej ligi

    Zwraca: (slownik_sil, srednia_ligi)
    """
    # Srednia bramek w lidze jako punkt odniesienia
    sr_g = df_mecze["gole_g"].mean()  # srednia goli gospodarzy
    sr_a = df_mecze["gole_a"].mean()  # srednia goli gosci
    srednia_ligi = (sr_g + sr_a) / 2

    if srednia_ligi == 0:
        srednia_ligi = 1.0  # Zabezpieczenie przed dzieleniem przez zero

    druzyny = set(df_mecze["gospodarz"]).union(set(df_mecze["goscie"]))
    sily = {}

    for druz in druzyny:
        mecze_dom  = df_mecze[df_mecze["gospodarz"] == druz]   # Mecze u siebie
        mecze_wyj  = df_mecze[df_mecze["goscie"] == druz]      # Mecze na wyjezdzie
        n = len(mecze_dom) + len(mecze_wyj)

        if n == 0:
            continue

        # Laczna suma goli strzelonych i straconych
        strzal = mecze_dom["gole_g"].sum() + mecze_wyj["gole_a"].sum()
        strata = mecze_dom["gole_a"].sum() + mecze_wyj["gole_g"].sum()

        # Srednia na mecz, znormalizowana przez srednia ligi
        sily[druz] = {
            "atak":   (strzal / n) / srednia_ligi,
            "obrona": (strata / n) / srednia_ligi,
            "mecze":  n,
        }

    return sily, srednia_ligi


def predict_match(gospodarz, gosc, df_mecze):
    """
    Glowna funkcja predykcji - przewiduje wynik meczu Poissona.

    Kroki algorytmu:
    1. Filtruje mecze obu druzyn z bazy danych
    2. Oblicza wspolczynniki sily (atak/obrona) kazdej druzyny
    3. Oblicza lambde (oczekiwana liczba goli) dla obu druzyn:
         lambda_g = atak_G * obrona_A * srednia_ligi * BONUS_DOMOWY
         lambda_a = atak_A * obrona_G * srednia_ligi
    4. Buduje macierz prawdopodobienstw NxN (rozklad Poissona)
    5. Sumuje prawdopodobienstwa wygranej/remisu/przegranej

    Zwraca slownik ze wszystkimi wynikami analizy.
    """
    BONUS_DOMOWY = 1.15  # Premia za gre u siebie (statystycznie ok. 15%)

    # Filtruj mecze obu druzyn (ostatnie N)
    maska = (
        (df_mecze["gospodarz"] == gospodarz) |
        (df_mecze["goscie"]    == gospodarz) |
        (df_mecze["gospodarz"] == gosc)      |
        (df_mecze["goscie"]    == gosc)
    )
    df_filtr = df_mecze[maska].tail(OSTATNIE_N)

    if len(df_filtr) < 4:
        console.print(f"[yellow]Za malo danych ({len(df_filtr)} meczow) dla: {gospodarz} / {gosc}[/yellow]")
        return None

    sily, srednia_ligi = _oblicz_sile_druzyn(df_filtr)

    if gospodarz not in sily:
        console.print(f"[red]Brak danych dla druzyny: {gospodarz}[/red]")
        return None
    if gosc not in sily:
        console.print(f"[red]Brak danych dla druzyny: {gosc}[/red]")
        return None

    sg = sily[gospodarz]  # Sily druzyny gospodarzy
    sa = sily[gosc]       # Sily druzyny gosci

    # Oblicz lambdy rozkladu Poissona
    # Lambda = oczekiwana srednia liczba goli w meczu
    lambda_g = sg["atak"] * sa["obrona"] * srednia_ligi * BONUS_DOMOWY
    lambda_a = sa["atak"] * sg["obrona"] * srednia_ligi

    # Zbuduj macierz prawdopodobienstw dla wynikow 0:0 do MAX:MAX
    N = MAX_GOLE_SYMUL + 1
    macierz = np.zeros((N, N))
    for i in range(N):
        for j in range(N):
            # P(wynik i:j) = P_Poisson(i|lambda_g) * P_Poisson(j|lambda_a)
            macierz[i][j] = poisson.pmf(i, lambda_g) * poisson.pmf(j, lambda_a)

    # Prawdopodobienstwa ogolnych istnien meczu
    p_wygrana   = float(np.sum(np.tril(macierz, -1)))  # gospodarz wygrywa (i > j)
    p_remis     = float(np.sum(np.diag(macierz)))       # remis (i == j)
    p_przegrana = float(np.sum(np.triu(macierz,  1)))   # gosc wygrywa (i < j)

    # Normalizacja (obciecie MAX_GOLE powoduje ze suma < 1.0)
    suma = p_wygrana + p_remis + p_przegrana
    if suma > 0:
        p_wygrana   /= suma
        p_remis     /= suma
        p_przegrana /= suma

    # Najbardziej prawdopodobny konkretny wynik (argmax macierzy)
    idx = np.unravel_index(np.argmax(macierz), macierz.shape)
    wynik_g, wynik_a = int(idx[0]), int(idx[1])

    # Top 5 wynikow wg prawdopodobienstwa
    flat = [(macierz[i][j], i, j) for i in range(N) for j in range(N)]
    flat.sort(reverse=True)
    top5 = [(f"{g}:{a}", round(p * 100, 1)) for p, g, a in flat[:5]]

    return {
        "gospodarz":     gospodarz,
        "gosc":          gosc,
        "lambda_g":      round(lambda_g, 2),
        "lambda_a":      round(lambda_a, 2),
        "p_wygrana":     round(p_wygrana * 100, 1),
        "p_remis":       round(p_remis * 100, 1),
        "p_przegrana":   round(p_przegrana * 100, 1),
        "wynik_g":       wynik_g,
        "wynik_a":       wynik_a,
        "top5_wyniki":   top5,
        "mecze_g":       sg["mecze"],
        "mecze_a":       sa["mecze"],
        "sila_ataku_g":  round(sg["atak"], 2),
        "sila_ataku_a":  round(sa["atak"], 2),
        "sila_obrony_g": round(sg["obrona"], 2),
        "sila_obrony_a": round(sa["obrona"], 2),
    }


# =============================================================
#   MODUL 3 - INTERFEJS RICH (KOLOROWY TERMINAL)
# =============================================================

def wyswietl_naglowek():
    """Wyswietla kolorowy baner startowy aplikacji."""
    console.clear()
    t = Text(justify="center")
    t.append("\n  >>> GOLAZO BOT <<<  ", style="bold white on dark_green")
    t.append("  Predyktor Wynikow Pilkarskich  \n", style="bold yellow on black")
    t.append("\n  Model: Rozklad Poissona  |  Zrodlo: football-data.org  \n", style="dim")
    console.print(Panel(t, border_style="green"))
    console.print()


def wyswietl_menu_lig():
    """Wyswietla tabele z dostepnymi ligami i zwraca wybrany kod."""
    t = Table(
        title="[bold green]Wybierz Lige[/bold green]",
        box=box.ROUNDED, border_style="green", show_lines=True
    )
    t.add_column("Nr",   style="bold cyan",  justify="center", width=4)
    t.add_column("Liga", style="bold white")
    t.add_column("Kod",  style="dim",        justify="center")
    for nr, info in LIGI.items():
        t.add_row(nr, f"{info['emoji']}  {info['nazwa']}", info["kod"])
    console.print(t)

    wybor = Prompt.ask(
        "\n[bold yellow]Wpisz numer ligi[/bold yellow]",
        choices=list(LIGI.keys()), default="1"
    )
    return LIGI[wybor]["kod"]


def wyswietl_tabele_ligowa(df, nazwa_ligi):
    """Wyswietla tabele ligowa z kolorowaniem pozycji i stref."""
    t = Table(
        title=f"[bold green]Tabela: {nazwa_ligi}[/bold green]",
        box=box.SIMPLE_HEAVY, border_style="bright_black",
        show_lines=False, header_style="bold cyan", row_styles=["", "dim"]
    )
    # Definicje kolumn
    kolumny = [
        ("Poz.",    "dim",         "center"),
        ("Druzyna", "bold white",  "left"),
        ("M",       "dim",         "center"),
        ("W",       "green",       "center"),
        ("R",       "yellow",      "center"),
        ("P",       "red",         "center"),
        ("Bramki",  "cyan",        "center"),
        ("+/-",     "magenta",     "center"),
        ("Pkt",     "bold yellow", "center"),
    ]
    for kol, styl, uzas in kolumny:
        t.add_column(kol, style=styl, justify=uzas)

    n = len(df)
    for _, w in df.iterrows():
        poz = w["Poz."]
        # Kolorowanie: zloto (1), zielony (2-4), czerwony (strefa spadkowa)
        if   poz == 1:      s = "bold yellow"
        elif poz <= 4:      s = "bold green"
        elif poz >= n - 2:  s = "red"
        else:               s = "white"

        t.add_row(
            f"[{s}]{poz}[/{s}]", str(w["Druzyna"]),
            str(w["M"]), str(w["W"]), str(w["R"]), str(w["P"]),
            str(w["Bramki"]), str(w["+/-"]), f"[bold]{w['Pkt']}[/bold]",
        )
    console.print(t)


def wyswietl_ostatnie_wyniki(df, limit=10):
    """Wyswietla ostatnie wyniki meczow z kolorowaniem zwyciezcy."""
    t = Table(
        title=f"[bold green]Ostatnie {limit} Wynikow[/bold green]",
        box=box.MINIMAL_DOUBLE_HEAD, border_style="bright_black",
        header_style="bold cyan"
    )
    t.add_column("Data",      style="dim",         justify="center")
    t.add_column("Gospodarz", style="bold white",  justify="right")
    t.add_column("Wynik",     style="bold yellow", justify="center")
    t.add_column("Goscie",    style="bold white",  justify="left")

    for _, w in df.tail(limit).iloc[::-1].iterrows():
        gg, ga = w["gole_g"], w["gole_a"]
        if   gg > ga:  kg, ka = "bold green", "dim red"
        elif gg < ga:  kg, ka = "dim red",    "bold green"
        else:          kg = ka = "yellow"

        t.add_row(
            w["data"],
            f"[{kg}]{w['gospodarz']}[/{kg}]",
            f"{gg} - {ga}",
            f"[{ka}]{w['goscie']}[/{ka}]",
        )
    console.print(t)


def wyswietl_predykcje(wynik):
    """
    Wyswietla pena analize predykcji w stylu Golazo:
    - Panel z najbardziej prawdopodobnym wynikiem
    - Wizualny pasek szans [====|==|===]
    - Tabela wspolczynnikow i sil druzyn
    - Top 5 przewidywanych wynikow
    """
    g  = wynik["gospodarz"]
    a  = wynik["gosc"]
    wg = wynik["wynik_g"]
    wa = wynik["wynik_a"]
    pw = wynik["p_wygrana"]
    pr = wynik["p_remis"]
    pp = wynik["p_przegrana"]

    # --- Panel z glownym wynikiem ---
    nt = Text(justify="center")
    nt.append(f"\n  {g}  ", style="bold white")
    nt.append(f"  {wg} : {wa}  ", style="bold yellow on dark_green")
    nt.append(f"  {a}  \n", style="bold white")
    nt.append("\n  Najbardziej prawdopodobny wynik  \n", style="dim italic")
    console.print(Panel(nt, border_style="green", padding=(0, 4)))
    console.print()

    # --- Wizualny pasek szans ---
    W = 50
    sg = max(1, int(pw / 100 * W))
    sr = max(1, int(pr / 100 * W))
    sa = max(1, W - sg - sr)

    pasek = Text()
    pasek.append("[" + "=" * sg, style="bold green")   # Wygrana gospodarzy
    pasek.append("|" + "=" * sr + "|", style="bold yellow")  # Remis
    pasek.append("=" * sa + "]", style="bold red")     # Wygrana gosci

    console.print(Align.center(pasek))
    opis = f"  {g[:14]:>14} {pw:5.1f}%  |  Remis {pr:4.1f}%  |  {pp:5.1f}% {a[:14]:<14}  "
    console.print(Align.center(Text(opis, style="dim")))
    console.print()

    # --- Tabela statystyk ---
    ts = Table(
        title="[bold cyan]Analiza Statystyczna[/bold cyan]",
        box=box.ROUNDED, border_style="cyan", show_header=False
    )
    ts.add_column("Opis",  style="dim",        justify="right",  width=32)
    ts.add_column("Wart",  style="bold white", justify="center", width=14)

    ts.add_row("Lambda (ocz. gole) - Gospodarz",   f"[green]{wynik['lambda_g']}[/green]")
    ts.add_row("Lambda (ocz. gole) - Goscie",       f"[red]{wynik['lambda_a']}[/red]")
    ts.add_row("-" * 32, "-" * 14)
    ts.add_row(f"Szansa wygranej [{g[:10]}]",       f"[bold green]{pw}%[/bold green]")
    ts.add_row("Szansa remisu",                      f"[bold yellow]{pr}%[/bold yellow]")
    ts.add_row(f"Szansa wygranej [{a[:10]}]",       f"[bold red]{pp}%[/bold red]")
    ts.add_row("-" * 32, "-" * 14)
    ts.add_row("Wspolczynnik ataku - Gospodarz",    f"{wynik['sila_ataku_g']}")
    ts.add_row("Wspolczynnik obrony - Gospodarz",   f"{wynik['sila_obrony_g']}")
    ts.add_row("Wspolczynnik ataku - Goscie",       f"{wynik['sila_ataku_a']}")
    ts.add_row("Wspolczynnik obrony - Goscie",      f"{wynik['sila_obrony_a']}")

    # --- Tabela Top 5 ---
    tt = Table(
        title="[bold magenta]Top 5 Wynikow[/bold magenta]",
        box=box.ROUNDED, border_style="magenta", header_style="bold magenta"
    )
    tt.add_column("Wynik",  justify="center", style="bold white", width=10)
    tt.add_column("Szansa", justify="center", style="cyan",       width=8)

    glowny = f"{wynik['wynik_g']}:{wynik['wynik_a']}"
    for ws, prob in wynik["top5_wyniki"]:
        label = f"{ws} <--" if ws == glowny else ws
        tt.add_row(label, f"{prob}%")

    console.print(Columns([ts, tt], equal=False, expand=False))
    console.print()


def wybierz_druzyny(df_mecze):
    """Wyswietla liste druzyn i prosi o wybranie gospodarzy oraz gosci."""
    druzyny = sorted(set(df_mecze["gospodarz"]).union(set(df_mecze["goscie"])))

    # Wyswietl w 3 kolumnach
    t = Table(
        title="[bold green]Dostepne Druzyny[/bold green]",
        box=box.MINIMAL, border_style="bright_black"
    )
    for _ in range(3):
        t.add_column("Nr",      style="dim cyan",   justify="right",  width=4)
        t.add_column("Druzyna", style="bold white", justify="left",   width=16)

    for i in range(0, len(druzyny), 3):
        wiersz = []
        for j in range(3):
            idx = i + j
            wiersz.extend([str(idx+1), druzyny[idx]] if idx < len(druzyny) else ["", ""])
        t.add_row(*wiersz)

    console.print(t)

    # Wybor z walidacja
    while True:
        try:
            nr_g = int(Prompt.ask("\n[bold yellow]Nr GOSPODARZY[/bold yellow]"))
            if 1 <= nr_g <= len(druzyny):
                break
            console.print("[red]Zly numer.[/red]")
        except ValueError:
            console.print("[red]Wpisz liczbe.[/red]")

    gospodarz = druzyny[nr_g - 1]

    while True:
        try:
            nr_a = int(Prompt.ask(f"[bold yellow]Nr GOSCI[/bold yellow] (nie {gospodarz})"))
            if 1 <= nr_a <= len(druzyny) and nr_a != nr_g:
                break
            console.print("[red]Zly numer lub taka sama druzyna.[/red]")
        except ValueError:
            console.print("[red]Wpisz liczbe.[/red]")

    return druzyny[nr_g - 1], druzyny[nr_a - 1]


# =============================================================
#   MODUL 4 - GLOWNA PETLA PROGRAMU
# =============================================================

def sprawdz_klucz_api():
    """Waliduje czy uzytkownik podmienil domyslny klucz API."""
    if API_KEY.strip() in ("TWOJ_KLUCZ_API_TUTAJ", "", "YOUR_API_KEY"):
        console.print(Panel(
            "[bold red]BRAK KLUCZA API![/bold red]\n\n"
            "Otworz plik [yellow]golazo_bot.py[/yellow] i uzupelnij:\n\n"
            '   [cyan]API_KEY = "twoj-prawdziwy-klucz"[/cyan]\n\n'
            "Bezplatny klucz: [bold]https://www.football-data.org/client/register[/bold]",
            border_style="red", title="Blad Konfiguracji", padding=(1, 4)
        ))
        sys.exit(1)


def pobierz_dane_ligi(kod_ligi, nazwa_ligi):
    """Pobiera tabele i wyniki dla wybranej ligi z animacja postepy."""
    df_tab = df_wyk = None
    with Progress(
        SpinnerColumn(style="green"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=30, complete_style="green"),
        console=console, transient=True
    ) as prog:
        t1 = prog.add_task(f"Pobieram tabele {nazwa_ligi}...", total=1)
        df_tab = pobierz_tabele(kod_ligi)
        prog.update(t1, completed=1)
        time.sleep(0.2)

        t2 = prog.add_task("Pobieram wyniki meczow...", total=1)
        df_wyk = pobierz_wyniki(kod_ligi, limit=100)
        prog.update(t2, completed=1)

    return df_tab, df_wyk


def main():
    """Glowna funkcja - petla menu bota Golazo."""
    sprawdz_klucz_api()
    wyswietl_naglowek()

    # Wybor ligi
    kod_ligi = wyswietl_menu_lig()
    nazwa_ligi = next(v["nazwa"] for v in LIGI.values() if v["kod"] == kod_ligi)
    console.print()

    # Pobieranie danych
    df_tabela, df_wyniki = pobierz_dane_ligi(kod_ligi, nazwa_ligi)

    if df_tabela is None or df_wyniki is None:
        console.print("[red]Blad pobierania danych. Sprawdz klucz API i internet.[/red]")
        sys.exit(1)

    console.print(
        f"[green]OK: {len(df_wyniki)} meczow, tabela z {len(df_tabela)} druzyn - liga: {nazwa_ligi}[/green]\n"
    )

    # Glowna petla menu
    while True:
        console.rule("[bold cyan]MENU[/bold cyan]")
        console.print("[bold]1[/bold]  Tabela ligowa")
        console.print("[bold]2[/bold]  Ostatnie wyniki")
        console.print("[bold]3[/bold]  Przewiduj wynik meczu  [dim](Poisson)[/dim]")
        console.print("[bold]4[/bold]  Zmien lige")
        console.print("[bold]0[/bold]  Wyjscie\n")

        wybor = Prompt.ask(
            "[bold yellow]Twoj wybor[/bold yellow]",
            choices=["0","1","2","3","4"], default="1"
        )

        if wybor == "1":
            console.print()
            wyswietl_tabele_ligowa(df_tabela, nazwa_ligi)

        elif wybor == "2":
            console.print()
            try:
                ile = int(Prompt.ask("Ile ostatnich meczow?", default="10"))
            except ValueError:
                ile = 10
            wyswietl_ostatnie_wyniki(df_wyniki, limit=ile)

        elif wybor == "3":
            console.print()
            gospodarz, gosc = wybierz_druzyny(df_wyniki)
            console.print(f"\n[dim]Analizuje: {gospodarz} vs {gosc}...[/dim]\n")

            with Progress(
                SpinnerColumn(style="yellow"),
                TextColumn("[yellow]Obliczam rozklad Poissona...[/yellow]"),
                console=console, transient=True
            ) as prog:
                prog.add_task("", total=None)
                wynik = predict_match(gospodarz, gosc, df_wyniki)
                time.sleep(0.5)

            if wynik:
                wyswietl_predykcje(wynik)

        elif wybor == "4":
            wyswietl_naglowek()
            kod_ligi = wyswietl_menu_lig()
            nazwa_ligi = next(v["nazwa"] for v in LIGI.values() if v["kod"] == kod_ligi)
            console.print()
            df_tabela, df_wyniki = pobierz_dane_ligi(kod_ligi, nazwa_ligi)
            if df_tabela is not None and df_wyniki is not None:
                console.print(f"[green]Liga zmieniona na: {nazwa_ligi}[/green]\n")

        elif wybor == "0":
            console.print("\n[bold green]Do zobaczenia! Powodzenia z typami![/bold green]\n")
            break

        console.print()


if __name__ == "__main__":
    main()
