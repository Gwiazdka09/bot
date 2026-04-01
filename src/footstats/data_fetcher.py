import time
import pandas as pd
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.panel import Panel
from rich.prompt import Prompt
from rich import box
from rich.table import Table
from footstats.utils.console import console
from footstats.utils.helpers import _s
from footstats.config import SLEEP_LOOP, VERSION
from footstats.scrapers.football_data import APIClient
from footstats.scrapers.api_football import APIFootball

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
