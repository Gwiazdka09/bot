"""
FootStats Daily Agent
=====================
Codzienne uruchamianie o 8:00: Bzzoiro → forma → Groq → gotowy kupon.

Użycie:
    python -m footstats.daily_agent
    python -m footstats.daily_agent --stawka 10 --dni 2
    python -m footstats.daily_agent --tylko-kupon   # bez formy (szybciej)
    python -m footstats.daily_agent --waliduj       # + Groq walidacja kuponu A
"""

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

LOGS_DIR = Path(__file__).parent.parent.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sep(tytul: str):
    console.rule(f"[bold cyan]{tytul}[/bold cyan]")


def _blad(msg: str):
    console.print(f"[bold red]BŁĄD:[/bold red] {msg}")
    sys.exit(1)


def _norm(name: str) -> str:
    """Normalizacja nazwy drużyny do porównań: lowercase, bez znaków specjalnych."""
    return name.lower().replace(".", "").replace("-", " ").replace("  ", " ").strip()


# ── Krok 1: Bzzoiro ───────────────────────────────────────────────────────────

def _pobierz_kandydatow(dni: int = 2) -> tuple[list, dict]:
    """
    Bzzoiro ML → (wyniki, indeks_kursow).
    indeks_kursow: klucz=(norm_gosp, norm_gosc) → {odds, gospodarz, goscie, liga}
    """
    from dotenv import load_dotenv
    load_dotenv()

    from footstats.scrapers.bzzoiro import BzzoiroClient, ENV_BZZOIRO
    from footstats.core.quick_picks import szybkie_pewniaczki_2dni
    from footstats.config import AGENT_KANDYDAT_PROG

    klucz = os.getenv(ENV_BZZOIRO, "")
    if not klucz:
        _blad("Brak BZZOIRO_API_KEY w .env")

    c = BzzoiroClient(klucz)
    ok, msg = c.waliduj()
    if not ok:
        _blad(f"Bzzoiro: {msg}")

    wyniki = szybkie_pewniaczki_2dni(c, prog=AGENT_KANDYDAT_PROG, godziny=dni * 24)
    console.print(f"[dim]Bzzoiro: {len(wyniki)} kandydatów w oknie {dni*24}h[/dim]")

    # Buduj indeks: (norm_gosp, norm_gosc) → dane meczu
    indeks: dict = {}
    for w in wyniki:
        g = w.get("gospodarz", "")
        a = w.get("goscie", "")
        indeks[(_norm(g), _norm(a))] = {
            "odds":      w.get("odds", {}),
            "gospodarz": g,
            "goscie":    a,
            "liga":      w.get("liga", ""),
        }

    return wyniki, indeks


# ── Krok 2: Forma SofaScore ───────────────────────────────────────────────────

def _wzbogac_forme_top(wyniki: list, top_n: int = 6) -> None:
    """Pobiera formę + kontuzje dla TOP N meczów przez SofaScore."""
    try:
        from footstats.scrapers.form_scraper import pobierz_forme_meczu, PLAYWRIGHT_OK
        if not PLAYWRIGHT_OK:
            console.print("[yellow]SofaScore niedostępny (Playwright) — pomijam formę[/yellow]")
            return
    except ImportError:
        console.print("[yellow]form_scraper niedostępny — pomijam formę[/yellow]")
        return

    def _max_ev(w):
        return max((v for _, v in w.get("typy", [(None, 0)])), default=0)

    top = sorted(wyniki, key=_max_ev, reverse=True)[:top_n]
    console.print(f"[dim]SofaScore: pobieram formę dla {len(top)} meczów...[/dim]")

    for w in top:
        g = w.get("gospodarz", "")
        a = w.get("goscie", "")
        if not g or not a:
            continue
        try:
            forma = pobierz_forme_meczu(g, a)
            fh = forma.get("home", {})
            fa = forma.get("away", {})
            if fh.get("form"):
                w["sofa_forma_g"] = f"{''.join(fh['form'])}({fh.get('goals_scored',0)}:{fh.get('goals_conceded',0)})"
            if fa.get("form"):
                w["sofa_forma_a"] = f"{''.join(fa['form'])}({fa.get('goals_scored',0)}:{fa.get('goals_conceded',0)})"
            inj_g = [i.get("name", "?") for i in fh.get("injuries", [])[:3]]
            inj_a = [i.get("name", "?") for i in fa.get("injuries", [])[:3]]
            if inj_g:
                w["sofa_kontuzje_g"] = ", ".join(inj_g)
            if inj_a:
                w["sofa_kontuzje_a"] = ", ".join(inj_a)
        except Exception:
            pass


def _wzbogac_o_betbuilder(wyniki: list) -> None:
    try:
        from footstats.core.bet_builder import estimate_lambdas_from_probs, get_betbuilder_suggestions
    except ImportError:
        return
    
    console.print("[dim]BetBuilder: Estymacja macierzy Poissona i generowanie sugestii łączonych...[/dim]")
    for w in wyniki:
        pw = w.get("pw", 0) / 100.0
        pp = w.get("pp", 0) / 100.0
        o25 = w.get("o25", 0) / 100.0
        
        if pw > 0 or pp > 0:
            # Estymujemy bazowe expected goals (lambda) na bazie probability
            lh, la = estimate_lambdas_from_probs(pw, pp, o25)
            ref_avg = w.get("referee_avg_y")
            sugestie = get_betbuilder_suggestions(lh, la, ref_avg_yellow=ref_avg)
            if sugestie:
                w["bet_builder"] = sugestie

# ── Krok 3: Groq AI ───────────────────────────────────────────────────────────

def _analizuj_groq(
    wyniki: list,
    cel_wygrana_a: float | None = None,
    cel_wygrana_b: float | None = None,
    stawka: float = 10.0,
) -> dict:
    from footstats.ai.analyzer import ai_analiza_pewniaczki, ai_groq_dostepny
    if not ai_groq_dostepny():
        _blad("Brak GROQ_API_KEY w .env")
    console.print("[dim]Groq: analizuję i buduję kupony...[/dim]")
    return ai_analiza_pewniaczki(
        wyniki,
        pobierz_forme=False,
        cel_wygrana_a=cel_wygrana_a,
        cel_wygrana_b=cel_wygrana_b,
        stawka=stawka,
    )


# ── Krok 4: Weryfikacja halucynacji ──────────────────────────────────────────

_TYP_DO_ODDS_KEY = {
    "1":           "home",
    "2":           "away",
    "x":           "draw",
    "over 2.5":    "over_2_5",
    "over":        "over_2_5",
    "o2.5":        "over_2_5",
    "under 2.5":   "under_2_5",
    "under":       "under_2_5",
    "btts":        "btts",
    "obie strzelą": "btts",
}


def _znajdz_mecz(mecz_str: str, indeks: dict) -> dict | None:
    """
    Próbuje dopasować string 'Drużyna A vs Drużyna B' do indeksu Bzzoiro.
    Zwraca wpis indeksu lub None jeśli brak dopasowania.
    """
    parts = mecz_str.lower().replace(" - ", " vs ").split(" vs ")
    if len(parts) != 2:
        return None
    ng, na = _norm(parts[0].strip()), _norm(parts[1].strip())

    # 1. Dokładne dopasowanie
    if (ng, na) in indeks:
        return indeks[(ng, na)]

    # 2. Częściowe dopasowanie (substring w obu kierunkach)
    for (ig, ia), dane in indeks.items():
        if (ng in ig or ig in ng) and (na in ia or ia in na):
            return dane

    return None


def _weryfikuj_kupony(dane: dict, indeks: dict) -> dict:
    """
    Sprawdza każdą nogę w kupon_a i kupon_b:
    - Jeśli mecz istnieje w Bzzoiro: podmienia kurs na rzeczywisty
    - Jeśli mecz NIE istnieje: usuwa nogę (halucynacja Groq) i loguje ostrzeżenie
    Zwraca zmodyfikowany słownik dane.
    """
    usuniete: list[str] = []

    for kupon_key in ("kupon_a", "kupon_b"):
        kupon = dane.get(kupon_key, {})
        zdarzenia = kupon.get("zdarzenia", [])
        if not zdarzenia:
            continue

        zweryfikowane = []
        for z in zdarzenia:
            mecz_str = z.get("mecz", "")
            typ_raw  = z.get("typ", "").strip()
            wpis     = _znajdz_mecz(mecz_str, indeks)

            if wpis is None:
                usuniete.append(f"{mecz_str} [{typ_raw}] — brak w Bzzoiro")
                continue

            # Podmień kurs na rzeczywisty z Bzzoiro
            odds_key = _TYP_DO_ODDS_KEY.get(typ_raw.lower())
            if odds_key:
                rzeczywisty = (wpis["odds"] or {}).get(odds_key)
                if rzeczywisty:
                    z["kurs"]      = float(rzeczywisty)
                    z["mecz"]      = f"{wpis['gospodarz']} vs {wpis['goscie']}"
                    z["_verified"] = True

            zweryfikowane.append(z)

        # Przenumeruj
        for i, z in enumerate(zweryfikowane, 1):
            z["nr"] = i

        # Przelicz kurs łączny i wygraną
        if zweryfikowane:
            kurs_l = 1.0
            for z in zweryfikowane:
                kurs_l *= z.get("kurs", 1.0)
            kupon["zdarzenia"]   = zweryfikowane
            kupon["kurs_laczny"] = round(kurs_l, 2)
        else:
            dane[kupon_key] = {}

    if usuniete:
        ostrzegawcze = dane.get("ostrzezenia", "") or ""
        dane["ostrzezenia"] = ostrzegawcze + "\n⚠️  USUNIĘTE HALUCYNACJE: " + " | ".join(usuniete)
        console.print(f"[red]Usunięto {len(usuniete)} halucynowanych nóg:[/red]")
        for u in usuniete:
            console.print(f"  [dim]- {u}[/dim]")

    return dane


# ── Krok 5a: Zapis do pliku TXT ──────────────────────────────────────────────

def _zapisz_txt(dane: dict, stawka_a: float, stawka_b: float) -> Path:
    """Zapisuje kupon do F:/bot/logs/kupon_YYYY-MM-DD.txt. Zwraca ścieżkę."""
    dzis = datetime.now().strftime("%Y-%m-%d")
    sciezka = LOGS_DIR / f"kupon_{dzis}.txt"

    linie: list[str] = []
    linie.append(f"FootStats Daily Agent — {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    linie.append("=" * 60)

    for label, kupon_key, stawka in [
        ("KUPON A", "kupon_a", stawka_a),
        ("KUPON B", "kupon_b", stawka_b),
    ]:
        kupon     = dane.get(kupon_key, {})
        zdarzenia = kupon.get("zdarzenia", [])
        if not zdarzenia:
            continue
        linie.append(f"\n{label} — stawka {stawka:.0f} PLN")
        linie.append("-" * 40)
        for z in zdarzenia:
            verified = "✓" if z.get("_verified") else " "
            linie.append(
                f"  {z.get('nr', '?')}. [{verified}] {z.get('mecz','?')}  |  "
                f"{z.get('typ','?')}  @{z.get('kurs', 0):.2f}"
            )
        kurs_l = kupon.get("kurs_laczny", 0) or 0
        wyg    = stawka * kurs_l * 0.88
        linie.append(f"  Kurs łączny: {kurs_l:.2f}  |  Wygrana netto: {wyg:.2f} PLN")

    top3 = dane.get("top3", [])
    if top3:
        linie.append("\nTOP 3 MECZÓW")
        linie.append("-" * 40)
        for i, row in enumerate(top3, 1):
            ev = row.get("ev_netto", 0) or 0
            linie.append(
                f"  {i}. {row.get('mecz','?')}  {row.get('typ','?')}  "
                f"@{row.get('kurs', 0):.2f}  EV={ev:+.1f}%"
            )
            uzas = row.get("uzasadnienie", "")
            if uzas:
                linie.append(f"     {uzas}")

    if dane.get("ostrzezenia"):
        linie.append("\nOSTRZEŻENIA")
        linie.append(str(dane["ostrzezenia"]))

    tekst = "\n".join(linie) + "\n"
    sciezka.write_text(tekst, encoding="utf-8")
    console.print(f"[dim]Kupon zapisany: {sciezka}[/dim]")
    return sciezka


# ── Krok 5b: Powiadomienie Windows ───────────────────────────────────────────

def _powiadomienie_windows(tytul: str, tekst: str) -> None:
    """Wyświetla Windows toast notification przez PowerShell (bez dodatkowych pakietów)."""
    ps_script = f"""
Add-Type -AssemblyName System.Windows.Forms
$n = New-Object System.Windows.Forms.NotifyIcon
$n.Icon = [System.Drawing.SystemIcons]::Information
$n.Visible = $true
$n.BalloonTipTitle = '{tytul.replace("'", "''")}'
$n.BalloonTipText  = '{tekst.replace("'", "''")}'
$n.BalloonTipIcon  = 'Info'
$n.ShowBalloonTip(8000)
Start-Sleep -Milliseconds 8500
$n.Dispose()
"""
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        console.print(f"[dim]Powiadomienie nieudane: {e}[/dim]")


# ── Krok 5: Wyświetl wyniki ───────────────────────────────────────────────────

def _wyswietl(dane: dict, stawka_a: float, stawka_b: float):
    if "top3" not in dane:
        console.print("[yellow]Brak danych JSON — surowa odpowiedź Groq:[/yellow]")
        console.print(dane.get("_raw", "brak"))
        return

    _sep("TOP 3 MECZÓW")
    t = Table(show_header=True, header_style="bold magenta")
    t.add_column("#", width=2)
    t.add_column("Mecz", min_width=32)
    t.add_column("Typ", width=8)
    t.add_column("Kurs", width=6)
    t.add_column("EV%", width=8)
    t.add_column("Uzasadnienie")
    for i, row in enumerate(dane.get("top3", []), 1):
        ev = row.get("ev_netto", 0) or 0
        kolor = "green" if ev > 5 else "yellow"
        t.add_row(
            str(i),
            row.get("mecz", "?"),
            row.get("typ", "?"),
            f"{row.get('kurs', 0):.2f}",
            f"[{kolor}]{ev:+.1f}%[/{kolor}]",
            row.get("uzasadnienie", ""),
        )
    console.print(t)

    for label, kupon_key, stawka in [
        ("KUPON A", "kupon_a", stawka_a),
        ("KUPON B", "kupon_b", stawka_b),
    ]:
        kupon = dane.get(kupon_key, {})
        zdarzenia = kupon.get("zdarzenia", [])
        if not zdarzenia:
            continue

        _sep(f"{label} — stawka {stawka:.0f} PLN")
        t2 = Table(show_header=True, header_style="bold blue")
        t2.add_column("#", width=2)
        t2.add_column("Mecz", min_width=30)
        t2.add_column("Typ", width=8)
        t2.add_column("Kurs", width=6)
        t2.add_column("Pewnosc", width=8)
        t2.add_column("Kelly", width=8)
        t2.add_column("Zrodlo", width=10)
        for z in zdarzenia:
            zrodlo  = "[green]Bzzoiro[/green]" if z.get("_verified") else "[dim]Groq[/dim]"
            pct     = z.get("pewnosc_pct")
            pct_str = f"{pct}%" if pct else "?"
            kelly   = z.get("kelly_stake")
            k_str   = f"[cyan]{kelly}PLN[/cyan]" if kelly else "?"
            t2.add_row(
                str(z.get("nr", "")),
                z.get("mecz", "?"),
                z.get("typ", "?"),
                f"{z.get('kurs', 0):.2f}",
                pct_str,
                k_str,
                zrodlo,
            )
        console.print(t2)

        kurs_l  = kupon.get("kurs_laczny", 0) or 0
        wyg     = stawka * kurs_l * 0.88
        szansa  = kupon.get("szansa_wygranej_pct")
        szansa_str = f"  |  Szansa: [bold {'green' if szansa and szansa >= 40 else 'yellow'}]{szansa}%[/bold {'green' if szansa and szansa >= 40 else 'yellow'}]" if szansa else ""
        console.print(
            f"  Kurs łączny: [bold]{kurs_l:.2f}[/bold]  |  "
            f"Wygrana netto: [bold green]{wyg:.2f} PLN[/bold green]"
            f"{szansa_str}"
        )

    if dane.get("ostrzezenia"):
        console.print()
        console.print(Panel(
            str(dane["ostrzezenia"]),
            title="[yellow]Ostrzeżenia[/yellow]",
            border_style="yellow",
        ))


# ── Krok 1b: API-Football Ekstraklasa ───────────────────────────────────────

def _pobierz_apifootball_ekstraklasa(dni: int = 3) -> list[dict]:
    """Dociąga kandydatów z Ekstraklasy przez API-Football (jeśli klucz dostępny)."""
    from dotenv import load_dotenv
    load_dotenv()
    klucz = os.getenv("APISPORTS_KEY", "").strip()
    if not klucz:
        return []
    try:
        from footstats.scrapers.api_football import APIFootball
        af = APIFootball(klucz)
        return af.kandydaci_liga(api_id=106, godziny=dni * 24, prog_pw=0.50)
    except Exception as e:
        console.print(f"[dim]API-Football Ekstraklasa: {e}[/dim]")
        return []


# ── Krok 4b: Kelly Criterion ──────────────────────────────────────────────────

def _dodaj_kelly(dane: dict, bankroll: float) -> None:
    """Dodaje kelly_stake do każdego zdarzenia w kuponach i top3."""
    try:
        from footstats.core.kelly import kelly_stake
        from footstats.config import AGENT_BANKROLL
        from footstats.core.calibration import get_stake_multiplier, calibration_summary
    except ImportError:
        return

    # Guard: bankroll musi być dodatnią liczbą — DB może zwrócić None
    if not isinstance(bankroll, (int, float)) or bankroll <= 0:
        bankroll = AGENT_BANKROLL

    # Etap 6: kalibracja stawki (Forma Bota 3 kupony + hit-rate 10 kuponów)
    multiplier = get_stake_multiplier()  # łączy oba sygnały
    cal = calibration_summary()
    if cal.get("n", 0) > 0:
        forma_info = f" | Forma3: {cal.get('forma_multiplier', 1.0)}x ({cal.get('forma_note', '')})"
        console.print(
            f"[dim]Kalibracja: hit={cal['hit_rate']:.0%} ({cal['won']}/{cal['n']}) "
            f"→ multiplier={multiplier}x — {cal['note']}{forma_info}[/dim]"
        )
    # Zabezpieczenie: multiplier nigdy None
    if not isinstance(multiplier, (int, float)) or multiplier <= 0:
        multiplier = 1.0
    effective_bankroll = bankroll * multiplier

    for kupon_key in ("kupon_a", "kupon_b"):
        for z in dane.get(kupon_key, {}).get("zdarzenia", []):
            p    = (z.get("pewnosc_pct") or 50) / 100.0
            odds = z.get("kurs") or 1.0
            try:
                z["kelly_stake"] = kelly_stake(p, odds, bankroll=effective_bankroll)
            except (TypeError, ZeroDivisionError):
                z["kelly_stake"] = 1.0

    for row in dane.get("top3", []):
        p    = (row.get("pewnosc_pct") or 50) / 100.0
        odds = row.get("kurs") or 1.0
        try:
            row["kelly_stake"] = kelly_stake(p, odds, effective_bankroll)
        except (TypeError, ZeroDivisionError):
            row["kelly_stake"] = 1.0


# ── Krok 6: Walidacja Groq ────────────────────────────────────────────────────

def _waliduj_kupon_groq(dane: dict, stawka: float, kupon_key: str = "kupon_a") -> None:
    from footstats.ai.analyzer import ai_sprawdz_kupon

    kupon     = dane.get(kupon_key, {})
    zdarzenia = kupon.get("zdarzenia", [])
    if not zdarzenia:
        return

    picks_text = "\n".join(
        f"{z.get('nr')}. {z.get('mecz')} | {z.get('typ')} @{z.get('kurs')}"
        for z in zdarzenia
    )
    _sep(f"WALIDACJA GROQ — {kupon_key.upper()}")
    console.print(ai_sprawdz_kupon(picks_text, stawka=stawka))


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="FootStats Daily Agent")
    parser.add_argument("--stawka",   type=float, default=10.0, help="Stawka kupon A (PLN, domyslnie 10)")
    parser.add_argument("--stawka-b", type=float, default=5.0,  help="Stawka kupon B (PLN, domyslnie 5)")
    parser.add_argument("--dni",      type=int,   default=3,    help="Horyzont w dniach (domyslnie 3)")
    parser.add_argument("--tylko-kupon", action="store_true",   help="Pomiń formę SofaScore")
    parser.add_argument("--waliduj",     action="store_true",   help="Uruchom walidację Groq kuponu A")
    parser.add_argument("--cel-a",   type=float, default=None,  help="Cel wygranej netto kupon A (PLN)")
    parser.add_argument("--cel-b",   type=float, default=None,  help="Cel wygranej netto kupon B (PLN)")
    parser.add_argument(
        "--faza", choices=["draft", "final"], default=None,
        help="Faza: draft (08:00, bez skladow) lub final (1h przed meczem, ze skladami)"
    )
    parser.add_argument(
        "--date", default=None,
        help="Data YYYY-MM-DD (domyslnie: dzis) — etykieta logów i update_pending"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Tryb podgladu: nie zapisuje do DB, TXT, nie wysyla Telegram/Windows"
    )
    args = parser.parse_args()

    from footstats.config import AGENT_BANKROLL
    from footstats.core.bankroll import get_current_bankroll

    current_bankroll = get_current_bankroll()
    date_label = args.date or datetime.now().strftime("%Y-%m-%d")
    dry_tag    = "  [yellow]⚠ DRY-RUN[/yellow]" if args.dry_run else ""

    console.print()
    console.print(Panel(
        f"[bold]FootStats Daily Agent[/bold]  |  {date_label}{dry_tag}\n"
        f"Horyzont: {args.dni} dni  |  Stawka A: {args.stawka} PLN  |  Stawka B: {args.stawka_b} PLN  |  Bankroll: {current_bankroll} PLN",
        border_style="cyan",
    ))

    # Krok 0: Auto-update wynikow pending meczow (pomijamy w dry-run)
    _sep("KROK 0 — Auto-update wynikow")
    if args.dry_run:
        console.print("[yellow]DRY-RUN: pomijam update_pending[/yellow]")
    else:
        try:
            from footstats.scrapers.results_updater import update_pending
            stats_upd = update_pending(days_back=3, dry_run=False, verbose=True)
            if stats_upd["updated"] > 0:
                console.print(f"[green]Zaktualizowano {stats_upd['updated']} wynikow w backtest.db[/green]")
        except Exception as e:
            console.print(f"[dim]Auto-update wynikow: {e}[/dim]")

        # Krok 0b: Analiza porażek AI (Pętla Feedbacku) — uruchamiana po update wyników
        try:
            from footstats.ai.post_match_analyzer import analizuj_porazki
            stats_fb = analizuj_porazki(days_back=14, dry_run=False)
            if stats_fb["analyzed"] > 0:
                console.print(
                    f"[dim]Pętla Feedbacku: przeanalizowano {stats_fb['analyzed']} porażek[/dim]"
                )
        except Exception as e:
            console.print(f"[dim]Analiza porażek (feedback): {e}[/dim]")

    _sep("KROK 1 — Bzzoiro ML")
    wyniki, indeks = _pobierz_kandydatow(dni=args.dni)

    # Krok 1b: Dociagnij Ekstraklase z API-Football jesli dostepny
    wyniki_ekstra = _pobierz_apifootball_ekstraklasa(args.dni)
    if wyniki_ekstra:
        console.print(f"[dim]API-Football Ekstraklasa: +{len(wyniki_ekstra)} kandydatow[/dim]")
        wyniki = wyniki + wyniki_ekstra
        for w in wyniki_ekstra:
            g = w.get("gospodarz", "")
            a = w.get("goscie", "")
            indeks[(_norm(g), _norm(a))] = {
                "odds": w.get("odds", {}), "gospodarz": g, "goscie": a, "liga": w.get("liga", "")
            }

    if not wyniki:
        _blad("Bzzoiro nie zwrocilo zadnych kandydatow.")

    # Ensemble: oblicz roznica_modeli (Poisson vs Bzzoiro) dla każdego kandydata
    _oblicz_roznica_modeli(wyniki)

    # -- Pre-filtr tokenów: odrzuca mecze bez pełnej nazwy drużyny lub ligi ──
    n_przed_token = len(wyniki)
    wyniki = _pre_filtruj_tokenow(wyniki)
    if len(wyniki) < n_przed_token:
        console.print(
            f"[dim]Pre-filtr tokenów (brak nazw/ligi): "
            f"{n_przed_token} → {len(wyniki)} kandydatów[/dim]"
        )

    # -- Pre-filtr kursów: oszczędza tokeny Groq (odrzuca <1.15 i >15.0) ───────
    n_przed_filter = len(wyniki)
    wyniki = _pre_filtruj_kursy(wyniki)
    if len(wyniki) < n_przed_filter:
        console.print(
            f"[dim]Pre-filtr kursów (1.15–15.0): "
            f"{n_przed_filter} → {len(wyniki)} kandydatów[/dim]"
        )

    # -- Faza draft/final: enrichment składów/sędziego (Decision Score → po Groq) ──
    if args.faza:
        _sep(f"FAZA {args.faza.upper()} — Składy + Sędzia (API-Football)")
        _enrichuj_finalna_faza(wyniki, os.getenv("APISPORTS_KEY", ""))
        console.print(f"[cyan]{args.faza.capitalize()}: {len(wyniki)} kandydatów po wzbogaceniu o składy/sędziego[/cyan]")

        if args.faza == "draft":
            _zapisz_next_final_txt(wyniki)

    if not args.tylko_kupon:
        _sep("KROK 2 — Forma SofaScore")
        _wzbogac_forme_top(wyniki, top_n=12)
        _wzbogac_o_betbuilder(wyniki)

    _sep("KROK 3 — Groq AI")
    dane = _analizuj_groq(wyniki, cel_wygrana_a=args.cel_a, cel_wygrana_b=args.cel_b, stawka=args.stawka)

    _sep("KROK 4 — Weryfikacja kursow (anty-halucynacja)")
    dane = _weryfikuj_kupony(dane, indeks)

    # Krok 4b: Dodaj Kelly do kazdej nogi
    _dodaj_kelly(dane, current_bankroll)

    # Krok 4c: Decision Score post-Groq — teraz pewnosc_pct i ev_netto są rzeczywiste
    if args.faza:
        _ocen_zdarzenia_decision_score(dane, phase=args.faza)

    _wyswietl(dane, args.stawka, args.stawka_b)

    if args.waliduj:
        _waliduj_kupon_groq(dane, args.stawka, "kupon_a")

    # -- Faza: zapisz kupon do SQLite DB (pomijamy w dry-run) ─────────────────
    cid = None
    draft_legs = []
    draft_odds = 1.0
    if args.faza and not args.dry_run:
        kupon_a_db = dane.get("kupon_a", {})
        zdarzenia_db = kupon_a_db.get("zdarzenia", [])
        kurs_db = kupon_a_db.get("kurs_laczny", 1.0) or 1.0
        if zdarzenia_db:
            cid = _zapisz_kupon_do_db(
                zdarzenia_db,
                phase=args.faza,
                groq_resp=dane.get("_raw", ""),
                stake=args.stawka,
                total_odds=kurs_db,
            )
            if cid:
                console.print(f"[green]✅ Kupon zapisany do DB — ID: {cid} | faza: {args.faza}[/green]")
                draft_legs = zdarzenia_db
                draft_odds = kurs_db
    elif args.dry_run and args.faza:
        console.print("[yellow]DRY-RUN: pominięto zapis kuponu do DB[/yellow]")

    # Zapisz do TXT (pomijamy w dry-run)
    if not args.dry_run:
        sciezka_txt = _zapisz_txt(dane, args.stawka, args.stawka_b)
    else:
        console.print("[yellow]DRY-RUN: pominięto zapis TXT[/yellow]")
        sciezka_txt = None

    # Powiadomienie Windows (pomijamy w dry-run)
    kupon_a   = dane.get("kupon_a", {})
    kupon_b   = dane.get("kupon_b", {})
    ile_nog_a = len(kupon_a.get("zdarzenia", []))
    ile_nog_b = len(kupon_b.get("zdarzenia", []))
    kurs_a    = kupon_a.get("kurs_laczny", 0) or 0
    kurs_b    = kupon_b.get("kurs_laczny", 0) or 0
    szansa_a  = kupon_a.get("szansa_wygranej_pct", "?")
    if not args.dry_run and sciezka_txt:
        notif_tekst = (
            f"A: {ile_nog_a}n @{kurs_a:.2f} ({szansa_a}%) | "
            f"B: {ile_nog_b}n @{kurs_b:.2f}\n{sciezka_txt.name}"
        )
        _powiadomienie_windows("FootStats - gotowy kupon", notif_tekst)

    # Telegram (pomijamy w dry-run)
    if not args.dry_run:
        try:
            from footstats.utils.telegram_notify import (
                send_kupon, send_draft_kupon, telegram_dostepny,
            )
            if telegram_dostepny():
                if args.faza == "draft" and cid and draft_legs:
                    ok = send_draft_kupon(cid, draft_legs, draft_odds)
                else:
                    ok = send_kupon(dane, stawka_a=args.stawka, stawka_b=args.stawka_b)
                console.print(f"[dim]Telegram: {'wyslano' if ok else 'blad wysylki'}[/dim]")
        except Exception as e:
            console.print(f"[dim]Telegram niedostepny: {e}[/dim]")
    else:
        console.print("[yellow]DRY-RUN: pominięto Telegram[/yellow]")

    console.print()
    console.print("[bold green]Gotowe.[/bold green] Powodzenia!\n")


# ── Ensemble: roznica_modeli ─────────────────────────────────────────────────

def _oblicz_roznica_modeli(wyniki: list) -> None:
    """
    Oblicza roznica_modeli = max(|P_poisson − P_bzzoiro|) dla win/draw/loss.

    Używa wynik_g/wynik_a z Bzzoiro ML jako przybliżonych lambd Poissona
    (brak potrzeby ładowania bazy historycznej).
    Ustawia pole 'roznica_modeli' in-place na każdym kandydacie.
    """
    try:
        from scipy.stats import poisson as _sps
        from footstats.core.ensemble import ensemble_probs, get_roznica
    except ImportError:
        return

    for k in wyniki:
        pw = k.get("pw", 0) / 100.0
        pr = k.get("pr", 0) / 100.0
        pp = k.get("pp", 0) / 100.0
        if pw + pr + pp < 0.01:
            continue  # brak danych ML Bzzoiro

        p_bzzoiro = {"win": pw, "draw": pr, "loss": pp}

        lh = max(float(k.get("wynik_g", 1) or 1), 0.3)
        la = max(float(k.get("wynik_a", 1) or 1), 0.3)

        p_win = p_draw = p_loss = 0.0
        for i in range(8):
            for j in range(8):
                p = _sps.pmf(i, lh) * _sps.pmf(j, la)
                if i > j:
                    p_win  += p
                elif i == j:
                    p_draw += p
                else:
                    p_loss += p

        p_poisson = {"win": p_win, "draw": p_draw, "loss": p_loss}
        p_ens = ensemble_probs(p_poisson, p_bzzoiro)
        k["roznica_modeli"] = round(get_roznica(p_ens, p_poisson, p_bzzoiro), 3)


# ── Nowe: enrichment fazy final ───────────────────────────────────────────

def _enrichuj_finalna_faza(wyniki: list, api_key: str) -> None:
    """
    Faza final: dla każdego kandydata pobiera składy i sędziego z API-Football.
    Aktualizuje pola lineup_ok, referee_neutral, referee_signal in-place.
    """
    if not api_key:
        console.print("[dim]APISPORTS_KEY niedostępny — pomijam enrichment składów/sędziego[/dim]")
        return

    import requests as _req
    from datetime import date
    from footstats.scrapers.lineup_scraper import get_lineup
    from footstats.scrapers.referee_db import referee_signal, get_referee
    from footstats.scrapers.flashscore_match import scrape_match_with_search

    dzis = date.today().isoformat()
    try:
        resp = _req.get(
            "https://v3.football.api-sports.io/fixtures",
            params={"date": dzis, "status": "NS"},
            headers={"x-apisports-key": api_key},
            timeout=15,
        )
        resp.raise_for_status()
        fixtures = resp.json().get("response", [])
    except Exception as e:
        console.print(f"[yellow]API-Football fixtures: {e} — pomijam enrichment[/yellow]")
        return

    # Indeks (norm_home, norm_away) → fixture_data
    idx: dict = {}
    for f in fixtures:
        teams = f.get("teams", {})
        fh = _norm(teams.get("home", {}).get("name", ""))
        fa = _norm(teams.get("away", {}).get("name", ""))
        if fh and fa:
            idx[(fh, fa)] = f

    enriched = 0
    for k in wyniki:
        gh = _norm(k.get("gospodarz", ""))
        ga = _norm(k.get("goscie", ""))

        fixture = idx.get((gh, ga))
        if fixture is None:
            for (fh, fa), f in idx.items():
                if (gh in fh or fh in gh) and (ga in fa or fa in ga):
                    fixture = f
                    break
        if fixture is None:
            continue

        fixture_id = fixture.get("fixture", {}).get("id")

        # Składy
        if fixture_id:
            lineup = get_lineup(fixture_id, api_key)
            k["lineup_ok"] = (
                lineup is not None
                and not lineup.get("home", {}).get("missing_key_players", True)
                and not lineup.get("away", {}).get("missing_key_players", True)
            )
        else:
            k["lineup_ok"] = None

        # Sędzia
        ref_name = (fixture.get("fixture", {}).get("referee") or "").split(",")[0].strip()
        if ref_name:
            ref_data = get_referee(ref_name)
            sig = referee_signal(ref_name)
            k["referee_neutral"] = sig in ("NEUTRALNY", "NIEZNANY")
            k["referee_name"] = ref_name
            k["referee_signal"] = sig
            if ref_data:
                k["referee_avg_y"] = ref_data.get("avg_yellow")
                k["referee_matches"] = ref_data.get("n_matches")
        
        # Fallback Flashscore (jeśli brak sędziego lub dla topowych kuponów)
        # Pobieramy absencje tylko jeśli mecz jest 'ciekawy' lub jesteśmy w fazie FINAL
        szukaj_fs = not k.get("referee_name")
        if szukaj_fs:
            fs_data = scrape_match_with_search(k.get("gospodarz"), k.get("goscie"))
            if fs_data.get("success"):
                if not k.get("referee_name") and fs_data.get("referee"):
                    k["referee_name"] = fs_data["referee"]
                    k["referee_signal"] = referee_signal(fs_data["referee"])
                    # Spróbuj jeszcze raz pobrać statystyki dla nowego nazwiska
                    ref_data = get_referee(fs_data["referee"])
                    if ref_data:
                        k["referee_avg_y"] = ref_data.get("avg_yellow")
                
                # Absencje Flashscore
                abs_h = [f"{a['name']} ({a['reason']})" for a in fs_data["absences"]["home"]]
                abs_a = [f"{a['name']} ({a['reason']})" for a in fs_data["absences"]["away"]]
                if abs_h: k["fs_absencje_g"] = ", ".join(abs_h)
                if abs_a: k["fs_absencje_a"] = ", ".join(abs_a)
                
                if fs_data.get("stadium"):
                    k["stadium"] = fs_data["stadium"]

        enriched += 1
        console.print(
            f"[dim]  {k.get('gospodarz')} vs {k.get('goscie')}: "
            f"lineup_ok={k.get('lineup_ok')} | sędzia={k.get('referee_signal', 'N/A')}[/dim]"
        )

    console.print(f"[cyan]Final enrichment: {enriched}/{len(wyniki)} kandydatów wzbogacono[/cyan]")


def _zapisz_next_final_txt(wyniki: list) -> None:
    """
    Zapisuje czas uruchomienia fazy final (pierwszy mecz − 70 min) do data/next_final.txt.
    Fallback: 13:30 gdy brak danych o godzinie meczu.
    """
    from datetime import datetime as _dt, timedelta

    DATA_DIR = Path(__file__).parents[2] / "data"
    DATA_DIR.mkdir(exist_ok=True)

    czasy = []
    for k in wyniki:
        for pole in ("kickoff", "godzina", "datetime", "data", "time", "date"):
            val = k.get(pole)
            if val and isinstance(val, str):
                for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%H:%M"):
                    try:
                        t = _dt.strptime(val[:16], fmt[:len(val[:16])])
                        if t.hour > 0:  # ignoruj daty bez godziny
                            czasy.append(t)
                        break
                    except ValueError:
                        continue

    if czasy:
        pierwszy = min(czasy)
        final_time = pierwszy - timedelta(minutes=70)
        txt = final_time.strftime("%H:%M")
    else:
        txt = "13:30"  # fallback: mecze popołudniowe

    out = DATA_DIR / "next_final.txt"
    out.write_text(txt, encoding="utf-8")
    console.print(f"[dim]next_final.txt → {txt} (czas startu fazy final)[/dim]")


# ── Nowe: fazy i decision score ────────────────────────────────────────────

def _pre_filtruj_kursy(kandydaci: list[dict]) -> list[dict]:
    """
    Pre-filtr kursów (przed Groq): odrzuca kandydatów bez żadnego kursu w 1.15–15.0.
    Cel: mniej tokenów do Groq, szybsze i tańsze uruchamianie.
    Kandydaci bez pola 'odds' (np. z API-Football) są zawsze zachowywani.
    """
    MIN_KURS, MAX_KURS = 1.15, 15.0
    wynik = []
    for k in kandydaci:
        odds_dict = k.get("odds") or {}
        if not odds_dict:
            wynik.append(k)  # brak danych → zostaw
            continue
        wartosci = [v for v in odds_dict.values() if isinstance(v, (int, float)) and v > 0]
        if any(MIN_KURS <= v <= MAX_KURS for v in wartosci):
            wynik.append(k)
    return wynik


def _pre_filtruj_tokenow(kandydaci: list[dict]) -> list[dict]:
    """
    Walidacja zabezpieczająca tokeny: odrzuca mecze bez pełnej nazwy drużyny 
    lub przypisanej ligi. Zapobiega to marnowaniu zapytań do gorszych lig/braków danych.
    """
    wynik = []
    for k in kandydaci:
        gospodarz = k.get("gospodarz") or k.get("home", "")
        goscie = k.get("goscie") or k.get("away", "")
        liga = k.get("liga", "")
        
        if gospodarz and str(gospodarz).strip() and goscie and str(goscie).strip() and liga and str(liga).strip():
            wynik.append(k)
    return wynik



def _ocen_zdarzenia_decision_score(dane: dict, phase: str = "draft") -> None:
    """
    Oblicza Decision Score dla nóg kuponu PO KROKU 3 (Groq).
    Teraz 'pewnosc_pct' i 'ev_netto' są rzeczywiste — scoring ma sens.
    Annotuje zdarzenia polem 'decision_score'. Nie usuwa nóg z kuponu.
    """
    from footstats.core.decision_score import score_kandydat, PROG_DRAFT, PROG_FINAL
    threshold = PROG_FINAL if phase == "final" else PROG_DRAFT

    _sep(f"DECISION SCORE — post-Groq [{phase.upper()}] (próg ≥ {threshold})")

    for kupon_key in ("kupon_a", "kupon_b"):
        zdarzenia = dane.get(kupon_key, {}).get("zdarzenia", [])
        if not zdarzenia:
            continue
        console.print(f"[dim]{kupon_key.upper()}:[/dim]")
        for z in zdarzenia:
            pct = z.get("pewnosc_pct") or 50
            w = {
                "ev_netto":       z.get("ev_netto", 0),
                "pewnosc":        pct,   # score_kandydat auto-normalizuje int>1 → /100
                "czynniki":       z.get("czynniki", []),
                "roznica_modeli": z.get("roznica_modeli", 0.0),
                "accuracy":       z.get("accuracy"),
            }
            ctx = {
                "lineup_ok":       z.get("lineup_ok"),
                "referee_neutral": z.get("referee_neutral", True),
            }
            sc, reasons = score_kandydat(w, context=ctx, phase=phase)
            z["decision_score"] = sc
            z["decision_reasons"] = reasons
            ikona = "[green]✅[/green]" if sc >= threshold else "[yellow]⚠️ [/yellow]"
            console.print(
                f"  {ikona} {z.get('mecz', '?')} [{z.get('typ', '?')}] "
                f"score={sc}/{threshold} | pewność={pct}%"
            )


def _decision_score_kandydat(kandydat: dict, phase: str = "draft") -> tuple[int, list[str]]:
    """Wrapper — konwertuje kandydata Bzzoiro → format decision_score."""
    from footstats.core.decision_score import score_kandydat
    w = {
        "ev_netto":       kandydat.get("ev_netto", 0),
        "pewnosc":        kandydat.get("pewnosc", 0.5),
        "czynniki":       kandydat.get("czynniki", []),
        "roznica_modeli": kandydat.get("roznica_modeli", 0.0),
        "accuracy":       kandydat.get("accuracy", 0.0),
    }
    context = {
        "lineup_ok":       kandydat.get("lineup_ok", None),
        "referee_neutral": kandydat.get("referee_neutral", True),
    }
    return score_kandydat(w, context=context, phase=phase)


def _filtruj_przez_decision_score(
    kandydaci: list[dict],
    phase: str = "draft",
    prog: int | None = None,
) -> list[dict]:
    """
    Filtruje kandydatów przez decision_score.
    Dodaje 'decision_score' i 'decision_reasons' do każdego kandydata.
    Zwraca tylko kandydatów >= prog.
    """
    from footstats.core.decision_score import PROG_DRAFT, PROG_FINAL
    threshold = prog if prog is not None else (PROG_FINAL if phase == "final" else PROG_DRAFT)

    wynik = []
    for k in kandydaci:
        sc, reasons = _decision_score_kandydat(k, phase=phase)
        k["decision_score"] = sc
        k["decision_reasons"] = reasons
        if sc >= threshold:
            wynik.append(k)
    return wynik


def _zapisz_kupon_do_db(
    kandydaci: list[dict],
    phase: str,
    groq_resp: str | None,
    stake: float,
    total_odds: float,
) -> int | None:
    """
    Zapisuje kupon do SQLite coupon_tracker. Zwraca coupon_id lub None.

    DRAFT → nowy rekord status=DRAFT.
    FINAL → szuka dzisiejszego DRAFT i promuje do ACTIVE;
            jeśli brak DRAFT — tworzy nowy rekord (fallback).
    """
    try:
        from footstats.core.coupon_tracker import (
            save_coupon, init_coupon_tables,
            get_draft_today, promote_to_active
        )
        from footstats.core.bankroll import process_bet, get_current_bankroll
        init_coupon_tables()
        current_bankroll = get_current_bankroll()
        
        def _parse_home_away(k: dict) -> tuple[str, str]:
            """Wyciąga home/away: wprost z pól lub przez split 'mecz'."""
            home = k.get("gospodarz") or k.get("home", "")
            away = k.get("goscie")    or k.get("away", "")
            if not home and not away:
                mecz = k.get("mecz", "")
                if " vs " in mecz:
                    parts = mecz.split(" vs ", 1)
                    home, away = parts[0].strip(), parts[1].strip()
                elif " - " in mecz:
                    parts = mecz.split(" - ", 1)
                    home, away = parts[0].strip(), parts[1].strip()
            return home, away

        legs = []
        for k in kandydaci:
            home, away = _parse_home_away(k)
            legs.append({
                "home":           home,
                "away":           away,
                "tip":            k.get("typ") or k.get("tip", ""),
                "odds":           k.get("kurs", 1.0),
                "decision_score": k.get("decision_score", 0),
                "mecz":           k.get("mecz", f"{home} vs {away}"),
            })
        from datetime import datetime as _dt
        match_date = _dt.now().strftime("%Y-%m-%d")
        avg_score = int(sum(k.get("decision_score", 0) for k in kandydaci) / max(len(kandydaci), 1))

        if phase == "final":
            draft_row = get_draft_today()
            if draft_row:
                try:
                    promote_to_active(
                        coupon_id=draft_row["id"],
                        legs=legs,
                        groq_reasoning=groq_resp or "",
                        decision_score=avg_score,
                        total_odds=round(total_odds, 2),
                    )
                    console.print(f"[green]Kupon #{draft_row['id']} DRAFT → ACTIVE[/green]")
                    return draft_row["id"]
                except Exception as promo_err:
                    console.print(
                        f"[red]BŁĄD promote_to_active(#{draft_row['id']}): {promo_err}"
                        f" — tworzę nowy kupon ACTIVE jako fallback[/red]"
                    )
            else:
                console.print("[yellow]Brak dzisiejszego DRAFT — tworzę nowy kupon ACTIVE[/yellow]")

        cid = save_coupon(
            phase=phase,
            kupon_type="A",
            legs=legs,
            total_odds=round(total_odds, 2),
            stake_pln=stake,
            groq_reasoning=groq_resp or "",
            decision_score=avg_score,
            match_date_first=match_date,
        )

        # Faza final: save_coupon tworzy DRAFT — od razu promuj do ACTIVE
        if cid and phase == "final":
            from footstats.core.coupon_tracker import update_coupon_status, STATUS_ACTIVE
            update_coupon_status(cid, STATUS_ACTIVE)
            console.print(f"[green]Kupon #{cid} → ACTIVE[/green]")

        if cid and stake > 0:
            process_bet(stake, f"Kupon A ID={cid} ({phase})")

        return cid
    except Exception as e:
        import traceback
        console.print(f"[red]BŁĄD _zapisz_kupon_do_db [{phase}]: {e}[/red]")
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        return None


if __name__ == "__main__":
    main()
