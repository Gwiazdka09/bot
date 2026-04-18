"""
FootStats Evening Agent
=======================
Uruchamiany o 23:00 — weryfikuje wyniki kuponów przez API-Football.

Użycie:
    python -m footstats.evening_agent
    python -m footstats.evening_agent --date 2026-04-09
"""

import os
import re
import sys
import argparse
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from footstats.utils.normalize import normalize_team_name

import requests
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from footstats.core.coupon_tracker import (
    get_active_coupons,
    get_coupon_legs,
    update_coupon_status,
    init_coupon_tables,
    STATUS_ACTIVE,
)
from footstats.core.backtest import init_db, update_result, _oblicz_tip_correct
from footstats.core.bankroll import process_win

console = Console()

API_BASE = "https://v3.football.api-sports.io"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    """
    Normalizuje nazwę drużyny dla fuzzy-matchingu.
    Deleguje do normalize_team_name: usuwa prefiksy (FC, KS, TSG, al-...),
    diakrytyki, znaki specjalne i stosuje mappingi z data/team_mappings.json.
    """
    return normalize_team_name(s)


def _similar(a: str, b: str) -> float:
    """
    Podobieństwo nazw drużyn 0–1.
    Obsługuje skróty (PSG = Paris Saint-Germain) i warianty (Lyon ~ Lyonnais).
    """
    na, nb = _norm(a), _norm(b)

    # 1. Dokładne dopasowanie
    if na == nb:
        return 1.0

    # 2. Sprawdź czy jedna jest akronimem drugiej (PSG → Paris Saint-Germain)
    def _initials(s: str) -> str:
        return "".join(w[0] for w in s.split() if w)

    if na == _initials(nb) or nb == _initials(na):
        return 0.85

    # 3. Sprawdź czy tokeny z a są prefiksem tokenów w b (Lyon → Lyonnais)
    tokens_a = na.split()
    tokens_b = nb.split()
    if all(any(tb.startswith(ta) for tb in tokens_b) for ta in tokens_a if len(ta) >= 3):
        return 0.80
    if all(any(ta.startswith(tb) for ta in tokens_a) for tb in tokens_b if len(tb) >= 3):
        return 0.80

    # 4. SequenceMatcher fallback
    return SequenceMatcher(None, na, nb).ratio()


def _wynik_z_fixture(fixture: dict) -> tuple[str, str, str] | None:
    """
    Parsuje fixture z API-Football.
    Zwraca (home_name, away_name, 'HG-AG') lub None jeśli mecz niezakończony.
    """
    status = fixture.get("fixture", {}).get("status", {}).get("short", "")
    if status not in ("FT", "AET", "PEN"):
        return None
    teams = fixture.get("teams", {})
    home = teams.get("home", {}).get("name", "")
    away = teams.get("away", {}).get("name", "")
    goals = fixture.get("goals", {})
    hg, ag = goals.get("home"), goals.get("away")
    if hg is None or ag is None:
        return None
    return home, away, f"{hg}-{ag}"


def _find_result(home: str, away: str, fixtures: list[dict]) -> str | None:
    """
    Fuzzy-match drużyn w liście fixtures API-Football.
    Zwraca wynik '2-1' lub None gdy brak dopasowania (próg similarności >= 0.6).
    """
    best_score = 0.0
    best_result: str | None = None
    for fix in fixtures:
        parsed = _wynik_z_fixture(fix)
        if not parsed:
            continue
        fh, fa, wynik = parsed
        score = (_similar(home, fh) + _similar(away, fa)) / 2
        if score > best_score and score >= 0.6:
            best_score = score
            best_result = wynik
    return best_result


def _status_kuponu(nogi_statusy: list[str]) -> str:
    """
    Oblicza finalny status kuponu z listy statusów nóg.
    Wejście: lista 'WIN' | 'LOSS' | 'PENDING' | 'VOID'
    """
    if not nogi_statusy:
        return "VOID"
    if "PENDING" in nogi_statusy:
        return STATUS_ACTIVE  # "ACTIVE" — czekamy na resztę meczów
    if all(s == "WIN" for s in nogi_statusy):
        return "WON"
    if any(s == "LOSS" for s in nogi_statusy):
        return "LOST"
    if all(s == "VOID" for s in nogi_statusy):
        return "VOID"
    return "PARTIAL"


# ── API ───────────────────────────────────────────────────────────────────────

def _fetch_results_today(api_key: str, date_str: str) -> list[dict]:
    """Pobiera zakończone mecze z API-Football dla daty YYYY-MM-DD."""
    try:
        r = requests.get(
            f"{API_BASE}/fixtures",
            headers={"x-apisports-key": api_key},
            params={"date": date_str, "status": "FT"},
            timeout=15,
        )
        if r.status_code != 200:
            console.print(f"[yellow]API-Football HTTP {r.status_code}[/yellow]")
            return []
        return r.json().get("response", [])
    except Exception as e:
        console.print(f"[yellow]API-Football błąd sieci: {e}[/yellow]")
        return []


# ── Telegram ──────────────────────────────────────────────────────────────────

def _send_telegram_summary(summary: dict, date_str: str) -> None:
    try:
        from footstats.utils.telegram_notify import send_message
        msg = (
            f"* Evening Report {date_str}*\n"
            f"Sprawdzono: {summary.get('checked', 0)} kuponów\n"
            f"Wygranych: {summary.get('won', 0)}\n"
            f"Przegranych: {summary.get('lost', 0)}\n"
            f"Oczekujących: {summary.get('active', 0)}"
        )
        send_message(msg)
    except Exception:
        pass  # Telegram opcjonalny


# ── Główna funkcja ────────────────────────────────────────────────────────────

def run_evening_agent(date_str: str | None = None) -> dict:
    """
    Weryfikuje wyniki kuponów dla danej daty.
    Zwraca dict: {checked, won, lost, partial, active}.
    Uruchamiany o 23:00 przez Task Scheduler — automatyczne rozliczanie kuponu.
    """
    load_dotenv()
    api_key = os.getenv("APISPORTS_KEY", "").strip()
    if not api_key:
        console.print("[red]Brak APISPORTS_KEY w .env — evening agent zatrzymany[/red]")
        return {}

    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    from datetime import datetime as dt
    now = dt.now().strftime("%Y-%m-%d %H:%M:%S")
    console.rule(f"[bold cyan]Evening Agent START — {date_str} ({now})[/bold cyan]")
    console.print(f"[dim]Proces: Automatyczne rozliczanie kuponów (scheduled @ 23:00)[/dim]")

    init_coupon_tables()
    init_db()

    fixtures = _fetch_results_today(api_key, date_str)
    console.print(f"[dim]API-Football: {len(fixtures)} zakończonych meczów[/dim]")

    active_coupons = get_active_coupons()
    console.print(f"[dim]Aktywne kupony do weryfikacji: {len(active_coupons)}[/dim]")

    summary: dict = {"checked": 0, "won": 0, "lost": 0, "partial": 0, "active": 0}
    nowe_wyniki = 0

    for kupon in active_coupons:
        legs = get_coupon_legs(kupon["id"])
        nogi_statusy: list[str] = []

        for leg in legs:
            home    = leg.get("gospodarz") or leg.get("home", "")
            away    = leg.get("goscie")    or leg.get("away", "")
            ai_tip  = leg.get("typ")       or leg.get("ai_tip", "")

            wynik = _find_result(home, away, fixtures)
            if wynik is None:
                nogi_statusy.append("PENDING")
                continue

            correct = _oblicz_tip_correct(ai_tip, wynik)
            nogi_statusy.append("WIN" if correct == 1 else ("LOSS" if correct == 0 else "VOID"))
            nowe_wyniki += 1

            # Aktualizuj predictions jeśli mamy prediction_id
            pred_id = leg.get("prediction_id")
            if pred_id:
                try:
                    update_result(pred_id, wynik)
                except (ValueError, KeyError) as e:
                    console.print(f"[yellow]Warning: Could not update prediction {pred_id}: {e}[/yellow]")

        nowy_status = _status_kuponu(nogi_statusy)

        if nowy_status != STATUS_ACTIVE:
            payout = None
            if nowy_status == "WON":
                stake = kupon["stake_pln"] or 10.0
                odds  = kupon["total_odds"] or 1.0
                payout = round(stake * odds * 0.88, 2)  # podatek 12%
            # Zintegrowane dodawanie do bankrolla
            if nowy_status == "WON" and payout:
                process_win(payout, f"Wygrana kuponu ID={kupon['id']}")
                
            update_coupon_status(kupon["id"], nowy_status, payout_pln=payout)
            key = nowy_status.lower()
            summary[key] = summary.get(key, 0) + 1
        else:
            summary["active"] += 1

        summary["checked"] += 1

    # Wyświetl tabelę
    _print_summary_table(summary)

    # Auto-trainer po 20+ nowych wynikach
    if nowe_wyniki >= 20:
        console.print(f"[green]{nowe_wyniki} nowych wyników → uruchamiam auto-trainer...[/green]")
        import subprocess
        subprocess.Popen(
            [sys.executable, "-m", "footstats.ai.trainer"],
            cwd=Path(__file__).parents[2],
        )

    _send_telegram_summary(summary, date_str)
    return summary


def _print_summary_table(summary: dict) -> None:
    t = Table(title="Evening Agent — Podsumowanie")
    t.add_column("Status", style="cyan")
    t.add_column("Liczba", justify="right")
    t.add_row("Sprawdzonych", str(summary.get("checked", 0)))
    t.add_row("Wygranych",  str(summary.get("won", 0)))
    t.add_row("Przegranych", str(summary.get("lost", 0)))
    t.add_row("Oczekujących", str(summary.get("active", 0)))
    console.print(t)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FootStats Evening Agent")
    parser.add_argument("--date", default=None, help="Data YYYY-MM-DD (default: dziś)")
    args = parser.parse_args()
    run_evening_agent(args.date)
