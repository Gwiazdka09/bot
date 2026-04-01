import time
from datetime import datetime, timedelta
import pandas as pd
from rich.table import Table
from rich.panel import Panel
from rich import box
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer,
    Table as RLTable, TableStyle, HRFlowable, PageBreak,
)
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from footstats.utils.console import console
from footstats.utils.helpers import _s
from footstats.config import (
    PEWNIACZEK_PROG, PEWNIACZEK_DNI, BZZOIRO_MAX_ROZN,
    VERSION, SLEEP_LOOP,
)
from footstats.core.poisson import predict_match
from footstats.scrapers.bzzoiro import BzzoiroClient, _bzz_parse_prob
from footstats.export.pdf_font import _pdf, PDF_FONT, PDF_FONT_BOLD, FONT_OK

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
