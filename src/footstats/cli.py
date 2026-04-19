"""FootStats CLI – Main entry point (MODUL 18)."""
import os
import time
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
from rich.prompt import Prompt, Confirm
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.panel import Panel
from rich.table import Table
from rich import box

from footstats.utils.console import console
from footstats.utils.helpers import _s
from footstats.utils.cache import af_budget_status, af_cache_info, af_cache_clear, AF_BLOCK_THRESHOLD, AF_WARN_THRESHOLD, AF_CACHE_TTL_H
from footstats.config import (
    VERSION, SLEEP_LOOP, SLEEP_KOLEJKA, PEWNIACZEK_PROG,
    ENV_FOOTBALL, ENV_APISPORTS, ENV_BZZOIRO,
    _wczytaj_lub_stworz_env, _czytaj_wszystkie_klucze,
)
from footstats.export.pdf_font import _zarejestruj_font, FONT_OK
from footstats.scrapers.football_data import APIClient
from footstats.scrapers.api_football import APIFootball
from footstats.scrapers.bzzoiro import BzzoiroClient
from footstats.scrapers.source_manager import SourceManager
from footstats.core.importance import ImportanceIndex
from footstats.core.fatigue import HeurystaZmeczeniaRotacji
from footstats.core.h2h import AnalizaH2H
from footstats.core.fortress import HomeFortress
from footstats.core.classifier import KlasyfikatorMeczu
from footstats.core.form import AnalizaDomWyjazd, porownaj_forme
from footstats.core.poisson import predict_match
from footstats.core.value_bet import typy_zaklady
from footstats.core.confidence import komentarz_analityka
from footstats.core.weekly_picks import (
    pewniaczki_tygodnia, wyswietl_pewniaczki, eksportuj_pdf_pewniaczki,
)
from footstats.core.queue_analysis import analiza_kolejki
from footstats.core.quick_picks import (
    szybkie_pewniaczki_2dni, wyswietl_szybkie_pewniaczki,
)
from footstats.data_fetcher import (
    pobierz_dane, wyswietl_menu_lig_v27, pobierz_dane_apisports,
    _generuj_tabele_z_wynikow,
)
from footstats.export.tables import (
    wyswietl_naglowek, wyswietl_tabele, wyswietl_wyniki,
    wyswietl_predykcje, wybierz_druzyny,
)
from footstats.export.pdf import eksportuj_pdf
from footstats.ai.analyzer import (
    ai_analiza_pewniaczki, ai_sprawdz_kupon, ai_groq_dostepny,
)


def _wyswietl_ai_pewniaczki(dane: dict, stawka: float = 5.0):
    """Renderuje wynik JSON z ai_analiza_pewniaczki() za pomocą Rich."""
    if "top3" not in dane:
        raw = dane.get("_raw") or dane.get("uzasadnienie") or str(dane)
        console.print(Panel(
            str(raw),
            title="[bold yellow]🤖 AI – Analiza Pewniaczków + Kupony[/bold yellow]",
            border_style="yellow",
            padding=(1, 2),
        ))
        return

    # TOP 3
    tbl = Table(
        title="🥇 TOP 3 Pojedyncze Typy",
        box=box.SIMPLE_HEAVY,
        show_header=True,
        header_style="bold yellow",
        padding=(0, 1),
    )
    tbl.add_column("Mecz", style="cyan", no_wrap=True, max_width=32)
    tbl.add_column("Typ", style="bold white", justify="center", width=6)
    tbl.add_column("Kurs", justify="right", width=6)
    tbl.add_column("EV netto", justify="right", width=10)
    tbl.add_column("Uzasadnienie", style="dim")

    for t in dane.get("top3", []):
        ev = t.get("ev_netto")
        try:
            ev_str = f"[green]+{float(ev):.1f}%[/green]" if ev is not None and float(ev) > 0 else f"[red]{float(ev):.1f}%[/red]"
        except (TypeError, ValueError):
            ev_str = str(ev) if ev is not None else "?"
        tbl.add_row(
            t.get("mecz", "?"),
            t.get("typ", "?"),
            str(t.get("kurs", "?")),
            ev_str,
            t.get("uzasadnienie", ""),
        )
    console.print(tbl)

    def _kupon_panel(kupon: dict, title: str, color: str):
        if not kupon:
            return
        lines = []
        for z in kupon.get("zdarzenia", []):
            lines.append(f"  {z.get('nr', '?')}. {z.get('mecz', '?')}  [bold]{z.get('typ', '?')}[/bold] @ {z.get('kurs', '?')}")
        kl = kupon.get("kurs_laczny", "?")
        wn = kupon.get("wygrana_netto", "?")
        lines.append(f"\n  Kurs łączny: [bold]{kl}[/bold]  →  Stawka {stawka:.0f} PLN  →  [bold green]~{wn} PLN netto[/bold green]")
        console.print(Panel(
            "\n".join(lines),
            title=f"[bold {color}]{title}[/bold {color}]",
            border_style=color,
            padding=(0, 1),
        ))

    _kupon_panel(dane.get("kupon_a"), "💰 KUPON A  (~50 PLN)", "green")
    _kupon_panel(dane.get("kupon_b"), "🚀 KUPON B  (~100 PLN)", "magenta")

    ost = dane.get("ostrzezenia")
    if ost:
        console.print(Panel(
            f"[yellow]{ost}[/yellow]",
            title="[bold red]⚠️  Ryzyka[/bold red]",
            border_style="red",
            padding=(0, 2),
        ))

#  MODUL 18 - GLOWNA PETLA
# ================================================================

def _ai_blok_pewniaczki(wyniki_p: list):
    """
    Blok AI po wyswietleniu Szybkich Pewniakow.
    Pyta czy uruchomic analize Groq, wyswietla wynik i oferuje
    sprawdzenie wlasnego kuponu.
    """
    if not wyniki_p:
        return
    if not ai_groq_dostepny():
        console.print("[dim yellow]AI niedostepne – dodaj GROQ_API_KEY w .env (opcja K)[/dim yellow]")
        return

    if not Confirm.ask(
        "[bold yellow]🤖 Analiza AI + propozycja kuponów (Groq llama-3.1-8b)?[/bold yellow]",
        default=True,
    ):
        return

    # Analiza listy pewniaczków
    console.print("[dim yellow]AI analizuje typy...[/dim yellow]")
    try:
        with Progress(SpinnerColumn(style="yellow"),
                      TextColumn("[yellow]Groq: analizuję pewniaczki...[/yellow]"),
                      console=console, transient=True) as pg:
            pg.add_task("", total=None)
            analiza = ai_analiza_pewniaczki(wyniki_p)
        _wyswietl_ai_pewniaczki(analiza)
    except Exception as e:
        console.print(f"[red]AI blad: {e}[/red]")
        return

    # Opcja: sprawdz wlasny kupon
    if not Confirm.ask("[dim]Sprawdzić własny kupon przez AI?[/dim]", default=False):
        return

    console.print(
        "[dim]Wpisz typy kuponu, np.:[/dim]\n"
        "[dim cyan]PSG 1X @1.31, Bayern wygrana @1.55, Leverkusen 1 @1.88[/dim cyan]"
    )
    picks_text = Prompt.ask("[bold cyan]Twój kupon[/bold cyan]").strip()
    if not picks_text:
        return

    try:
        stawka_str = Prompt.ask("[yellow]Stawka (PLN)[/yellow]", default="5")
        stawka = float(stawka_str)
    except ValueError:
        stawka = 5.0

    console.print("[dim yellow]AI sprawdza kupon...[/dim yellow]")
    try:
        with Progress(SpinnerColumn(style="cyan"),
                      TextColumn("[cyan]Groq: oceniam kupon...[/cyan]"),
                      console=console, transient=True) as pg:
            pg.add_task("", total=None)
            ocena = ai_sprawdz_kupon(picks_text, stawka, wzorzec_ml=wyniki_p)
        console.print(Panel(
            ocena,
            title="[bold cyan]🤖 AI – Ocena Twojego Kuponu[/bold cyan]",
            border_style="cyan",
            padding=(1, 2),
        ))
    except Exception as e:
        console.print(f"[red]AI blad: {e}[/red]")


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
        _ai_blok_pewniaczki(wyniki_start)

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

        # ── Nagłówek ──────────────────────────────────────────────────────
        console.print()
        menu_tbl = Table(
            show_header=False, box=box.SIMPLE_HEAD,
            border_style="bright_black", padding=(0, 1),
            min_width=58,
        )
        menu_tbl.add_column("klucz", style="bold", width=4, justify="right")
        menu_tbl.add_column("nazwa", min_width=22)
        menu_tbl.add_column("opis", style="dim", min_width=28)

        # ── SEKCJA: LIGA ──────────────────────────────────────────────────
        menu_tbl.add_row("[bright_black]──[/bright_black]", "[bright_black]LIGA[/bright_black]", "")
        menu_tbl.add_row("1", "Tabela ligowa",     "Importance 2.0, tryb finalny")
        menu_tbl.add_row("2", "Ostatnie wyniki",   "N ostatnich meczow")
        menu_tbl.add_row("3", "Predykcja meczu",   "H2H / Patent / Fortress / Dom-Wyjazd")
        menu_tbl.add_row("4", "Porownanie formy",  "H2H 24 mies. + historia")
        menu_tbl.add_row("5", "Analiza kolejki",   "LIGA / PUCHAR / REWANZ / FINAL")
        menu_tbl.add_row("6", "Eksport PDF",       "Raport z komentarzem")
        menu_tbl.add_row("7", "Zmien lige",        "Przelacz na inna lige / kraj")
        menu_tbl.add_row("[cyan]9[/cyan]", "[cyan]Dom / Wyjazd[/cyan]", "Statystyki H/A, wykrywanie Podroznikow")

        # ── SEKCJA: AI ────────────────────────────────────────────────────
        menu_tbl.add_row("", "", "")
        menu_tbl.add_row("[bright_black]──[/bright_black]", "[bright_black]TYPY AI  (Groq 70B)[/bright_black]", "")
        menu_tbl.add_row(
            "[green]P[/green]", "[green]Pewniaczki Tygodnia[/green]",
            "ML + Poisson, Scout Bot EV, PDF" + (" [dim](Bzzoiro OK)[/dim]" if bzzoiro else " [yellow](bez Bzzoiro)[/yellow]"),
        )
        menu_tbl.add_row("[green]A[/green]", "[green]Analiza Kuponu[/green]",  "Scout Bot oceni EV i ryzyko")
        if _ai_dostepne:
            menu_tbl.add_row("[yellow]I[/yellow]", "[yellow]AI Analiza meczu[/yellow]",  "Groq + kursy bukmacherow")
            menu_tbl.add_row("[yellow]J[/yellow]", "[yellow]AI Analiza kolejki[/yellow]","Wszystkie nadchodzace mecze")

        # ── SEKCJA: NARZEDZIA ─────────────────────────────────────────────
        menu_tbl.add_row("", "", "")
        menu_tbl.add_row("[bright_black]──[/bright_black]", "[bright_black]NARZEDZIA[/bright_black]", "")
        menu_tbl.add_row("[blue]D[/blue]", "[blue]Dashboard[/blue]", "Streamlit: ROI, bankroll, accuracy")
        if sources.apisports_ok:
            bud = af_budget_status()
            kol = "green" if not bud["ostrzezenie"] else ("yellow" if not bud["krytyczny"] else "red")
            menu_tbl.add_row(
                "C", "Cache API-Football",
                f"[{kol}]{bud['pozostalo']}/{bud['limit']} req[/{kol}] pozostalo",
            )
        if not sources.bzzoiro_ok or not sources.apisports_ok:
            brak = "Bzzoiro" if not sources.bzzoiro_ok else "API-Football"
            menu_tbl.add_row("[magenta]K[/magenta]", "[magenta]Dodaj klucz API[/magenta]", brak)

        menu_tbl.add_row("", "", "")
        menu_tbl.add_row("[red]0[/red]", "[red]Wyjscie[/red]", "")

        console.print(
            Panel(menu_tbl, title=f"[bold blue]FootStats {VERSION}[/bold blue]  [dim]{nazwa_ligi}[/dim]",
                  border_style="blue", padding=(0, 1)),
        )

        choices = ["0","1","2","3","4","5","6","7","9","a","A","k","K","c","C","p","P","i","I","j","J","d","D"]
        wybor = Prompt.ask("[bold yellow]>[/bold yellow]",
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
                    _ai_blok_pewniaczki(cache_pewniaczki)
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
                    _ai_blok_pewniaczki(cache_pewniaczki)

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
                        # cache_kolejki = [{"mecz": row, "predykcja": wynik, "klasyfikacja": klas}]
                        _pred_raw = _m.get("predykcja")
                        _pred = _pred_raw if _pred_raw is not None else {}
                        _mecz_raw = _m.get("mecz")
                        _mecz = _mecz_raw if _mecz_raw is not None else {}
                        # Pobierz nazwy z predykcji (zawiera gospodarz/gosc z predict_match)
                        # Pobierz nazwy — _pred to dict, _mecz to pandas Series lub dict
                        _g = _pred.get("gospodarz", "") if isinstance(_pred, dict) else ""
                        _a = _pred.get("gosc", "")      if isinstance(_pred, dict) else ""
                        if not _g and _mecz_raw is not None:
                            try:
                                _g = str(_mecz_raw["gospodarz"]) if "gospodarz" in _mecz_raw.index else ""
                            except Exception:
                                pass
                        if not _a and _mecz_raw is not None:
                            try:
                                _a = str(_mecz_raw["goscie"]) if "goscie" in _mecz_raw.index else ""
                            except Exception:
                                pass
                        if not _g or not _a:
                            continue  # pomijaj mecze bez nazw drużyn
                        console.print(f"  [{_i}/{len(cache_kolejki)}] {_g} vs {_a}")
                        _k = None
                        if _liga_slug_j:
                            try:
                                _k = _kursy_ai(_g, _a, _liga_slug_j)
                            except Exception:
                                pass
                        # Pobierz formę jako string
                        def _fstr(druz, n=5):
                            try:
                                df_f = df_wyniki[
                                    (df_wyniki["gospodarz"]==druz)|(df_wyniki["goscie"]==druz)
                                ].tail(n)
                                r2=[]
                                for _, rw in df_f.iterrows():
                                    if rw["gospodarz"]==druz:
                                        r2.append("W" if rw["gole_g"]>rw["gole_a"] else("R" if rw["gole_g"]==rw["gole_a"] else "P"))
                                    else:
                                        r2.append("W" if rw["gole_a"]>rw["gole_g"] else("R" if rw["gole_g"]==rw["gole_a"] else "P"))
                                return "".join(r2)
                            except Exception:
                                return "-"
                        try:
                            _wyn = _analizuj_ai(
                                gospodarz           = _g,
                                goscie              = _a,
                                p_wygrana           = _pred.get("p_wygrana", 33),
                                p_remis             = _pred.get("p_remis",   33),
                                p_przegrana         = _pred.get("p_przegrana", 34),
                                btts                = _pred.get("btts", 0),
                                over25              = _pred.get("over25", 0),
                                forma_g             = _fstr(_g),
                                forma_a             = _fstr(_a),
                                h2h_opis            = _pred.get("h2h_g", {}).get("opis", "-") or "-",
                                pewnosc_modelu      = _pred.get("pewnosc", 0),
                                komentarz_footstats = komentarz_analityka(_pred),
                                kursy               = _k,
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

        elif wybor == "d":
            import subprocess, sys as _sys
            dash_path = Path(__file__).parents[2] / "dashboard.py"
            if not dash_path.exists():
                console.print("[red]Nie znaleziono dashboard.py[/red]")
            else:
                console.print(
                    f"[bold blue]Uruchamianie Dashboard...[/bold blue]\n"
                    f"[dim]streamlit run {dash_path}[/dim]\n"
                    "[dim](nacisnij Ctrl+C w terminalu aby zatrzymac)[/dim]"
                )
                try:
                    subprocess.Popen(
                        [_sys.executable, "-m", "streamlit", "run", str(dash_path)],
                        creationflags=subprocess.CREATE_NEW_CONSOLE if hasattr(subprocess, "CREATE_NEW_CONSOLE") else 0,
                    )
                    console.print("[green]Dashboard uruchomiony w nowym oknie (http://localhost:8501)[/green]")
                except FileNotFoundError:
                    console.print("[red]Brak streamlit. Zainstaluj: pip install streamlit[/red]")
                except Exception as _e:
                    console.print(f"[red]Blad uruchamiania dashboard: {_e}[/red]")

        elif wybor == "0":
            console.print(f"\n[bold blue]Do zobaczenia! FootStats {VERSION}[/bold blue]\n")
            break

        console.print()


if __name__ == "__main__":
    main()
