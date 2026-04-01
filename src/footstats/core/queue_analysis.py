import time
import pandas as pd
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich import box
from footstats.utils.console import console
from footstats.utils.helpers import _s
from footstats.config import (
    VERSION, SLEEP_KOLEJKA,
)
from footstats.core.poisson import predict_match
from footstats.core.importance import ImportanceIndex
from footstats.core.fatigue import HeurystaZmeczeniaRotacji
from footstats.core.h2h import AnalizaH2H
from footstats.core.fortress import HomeFortress
from footstats.core.classifier import KlasyfikatorMeczu

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
