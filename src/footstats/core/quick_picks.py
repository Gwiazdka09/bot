import time
from datetime import datetime, timedelta
from rich.table import Table
from rich.panel import Panel
from rich import box
from footstats.utils.console import console
from footstats.utils.helpers import _s
from footstats.config import PEWNIACZEK_PROG
from footstats.scrapers.bzzoiro import BzzoiroClient, _bzz_parse_prob
from footstats.core.weekly_picks import _typy_pewne

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
