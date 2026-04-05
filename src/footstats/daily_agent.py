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

    klucz = os.getenv(ENV_BZZOIRO, "")
    if not klucz:
        _blad("Brak BZZOIRO_API_KEY w .env")

    c = BzzoiroClient(klucz)
    ok, msg = c.waliduj()
    if not ok:
        _blad(f"Bzzoiro: {msg}")

    wyniki = szybkie_pewniaczki_2dni(c, prog=0.55, godziny=dni * 24)
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


# ── Krok 3: Groq AI ───────────────────────────────────────────────────────────

def _analizuj_groq(wyniki: list) -> dict:
    from footstats.ai.analyzer import ai_analiza_pewniaczki, ai_groq_dostepny
    if not ai_groq_dostepny():
        _blad("Brak GROQ_API_KEY w .env")
    console.print("[dim]Groq: analizuję i buduję kupony...[/dim]")
    return ai_analiza_pewniaczki(wyniki, pobierz_forme=False)


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
        t2.add_column("Mecz", min_width=32)
        t2.add_column("Typ", width=8)
        t2.add_column("Kurs", width=6)
        t2.add_column("Źródło", width=10)
        for z in zdarzenia:
            zrodlo = "[green]Bzzoiro✓[/green]" if z.get("_verified") else "[dim]Groq[/dim]"
            t2.add_row(
                str(z.get("nr", "")),
                z.get("mecz", "?"),
                z.get("typ", "?"),
                f"{z.get('kurs', 0):.2f}",
                zrodlo,
            )
        console.print(t2)

        kurs_l = kupon.get("kurs_laczny", 0) or 0
        wyg    = stawka * kurs_l * 0.88
        console.print(
            f"  Kurs łączny: [bold]{kurs_l:.2f}[/bold]  |  "
            f"Wygrana netto: [bold green]{wyg:.2f} PLN[/bold green]"
        )

    if dane.get("ostrzezenia"):
        console.print()
        console.print(Panel(
            str(dane["ostrzezenia"]),
            title="[yellow]Ostrzeżenia[/yellow]",
            border_style="yellow",
        ))


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
    parser.add_argument("--stawka",   type=float, default=5.0,  help="Stawka kupon A (PLN, domyślnie 5)")
    parser.add_argument("--stawka-b", type=float, default=5.0,  help="Stawka kupon B (PLN, domyślnie 5)")
    parser.add_argument("--dni",      type=int,   default=2,    help="Horyzont w dniach (domyślnie 2)")
    parser.add_argument("--tylko-kupon", action="store_true",   help="Pomiń formę SofaScore")
    parser.add_argument("--waliduj",     action="store_true",   help="Uruchom walidację Groq kuponu A")
    args = parser.parse_args()

    console.print()
    console.print(Panel(
        f"[bold]FootStats Daily Agent[/bold]  |  {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
        f"Horyzont: {args.dni} dni  |  Stawka A: {args.stawka} PLN  |  Stawka B: {args.stawka_b} PLN",
        border_style="cyan",
    ))

    _sep("KROK 1 — Bzzoiro ML")
    wyniki, indeks = _pobierz_kandydatow(dni=args.dni)
    if not wyniki:
        _blad("Bzzoiro nie zwróciło żadnych kandydatów.")

    if not args.tylko_kupon:
        _sep("KROK 2 — Forma SofaScore")
        _wzbogac_forme_top(wyniki, top_n=6)

    _sep("KROK 3 — Groq AI")
    dane = _analizuj_groq(wyniki)

    _sep("KROK 4 — Weryfikacja kursów (anty-halucynacja)")
    dane = _weryfikuj_kupony(dane, indeks)

    _wyswietl(dane, args.stawka, args.stawka_b)

    if args.waliduj:
        _waliduj_kupon_groq(dane, args.stawka, "kupon_a")

    # Zapisz do TXT
    sciezka_txt = _zapisz_txt(dane, args.stawka, args.stawka_b)

    # Powiadomienie Windows
    kupon_a = dane.get("kupon_a", {})
    kupon_b = dane.get("kupon_b", {})
    ile_nog_a = len(kupon_a.get("zdarzenia", []))
    ile_nog_b = len(kupon_b.get("zdarzenia", []))
    kurs_a = kupon_a.get("kurs_laczny", 0) or 0
    kurs_b = kupon_b.get("kurs_laczny", 0) or 0
    notif_tekst = (
        f"Kupon A: {ile_nog_a} nog @{kurs_a:.2f} | "
        f"Kupon B: {ile_nog_b} nog @{kurs_b:.2f}\n"
        f"Plik: {sciezka_txt.name}"
    )
    _powiadomienie_windows("FootStats - gotowy kupon", notif_tekst)

    console.print()
    console.print("[bold green]Gotowe.[/bold green] Powodzenia!\n")


if __name__ == "__main__":
    main()
