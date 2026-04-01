import pandas as pd
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box
from rich.columns import Columns
from rich.align import Align
from rich.prompt import Prompt
from footstats.utils.console import console
from footstats.utils.helpers import _s
from footstats.config import VERSION, PEWNIACZEK_PROG
import footstats.export.pdf_font as _pdf_font_mod
from footstats.scrapers.football_data import APIClient
from footstats.core.importance import ImportanceIndex
from footstats.core.value_bet import typy_zaklady
from footstats.core.confidence import komentarz_analityka

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
        if _pdf_font_mod.FONT_OK else
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
