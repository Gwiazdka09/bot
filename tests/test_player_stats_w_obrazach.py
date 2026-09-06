"""Zrzut goli musi jechac do repo i do OBU obrazow — inaczej goal_share to zero.

PO CO: `data/footstats_backtest.db` jest wykluczony i z `.dockerignore`, i z
`.gcloudignore`, wiec w kontenerze tej bazy NIE MA. sqlite3 tworzy pusty plik,
a pierwszy odczyt konczy sie `no such table: player_stats`. Zmierzone na
produkcji 07.09.2026 — jeden przebieg jobu zostawil 105 takich wpisow na stderr:

    player_db: nie moge odczytac goli AZ Alkmaar/2026
    (OperationalError: no such table: player_stats) — goal_share = 0

Skutek siega dalej niz korekta lambda za kontuzje: `_policz_edge_absencji`
wychodzi wtedy na `continue`, wiec `p_over_abs`, `edge_absencje` i `rynek_p_over`
nie powstaja NIGDY. `model_log` mial 1078 wierszy i ZERO z niepustym p_over_abs.

Ta sama klasa co brakujace aliasy druzyn (`test_aliasy_w_obrazach.py`): lokalnie
zielono, w kontenerze cicho zerowa wartosc.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLIK = "data/player_stats.json"


def test_zrzut_jest_sledzony_przez_git() -> None:
    wynik = subprocess.run(
        ["git", "check-ignore", PLIK],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert wynik.returncode != 0, (
        f"{PLIK} jest ignorowany przez gita — zrzut nie trafi do repo ani do obrazu")


def test_zrzut_kopiowany_do_obu_obrazow() -> None:
    """Oba licza kandydatow: joby faza final/evening, API `/cron/draft`."""
    for dockerfile in ("Dockerfile.api", "Dockerfile.jobs"):
        tresc = (ROOT / dockerfile).read_text(encoding="utf-8")
        assert PLIK in tresc, f"{dockerfile} nie kopiuje {PLIK}"


def test_ignore_y_nie_wycinaja_zrzutu_z_kontekstu() -> None:
    """`COPY` nie pomoze, jesli plik wypadnie z kontekstu budowania."""
    for nazwa, wzor in ((".dockerignore", "!data/player_stats.json"),
                        (".gcloudignore", "!/data/player_stats.json")):
        linie = [w.strip() for w in (ROOT / nazwa).read_text(encoding="utf-8").splitlines()
                 if w.strip() and not w.strip().startswith("#")]
        assert wzor in linie, f"{nazwa} nie ma negacji {wzor}"


def test_zrzut_ma_sensowna_tresc() -> None:
    """Plik z zerem strzelcow przechodzilby wszystkie testy struktury."""
    dane = json.loads((ROOT / PLIK).read_text(encoding="utf-8"))
    assert len(dane) > 500, f"tylko {len(dane)} graczy — odpal eksport_player_stats.py"
    wymagane = {"name", "team_norm", "season", "goals"}
    assert wymagane <= set(dane[0]), f"brak kolumn: {wymagane - set(dane[0])}"
    assert all(int(w["goals"]) > 0 for w in dane[:200]), \
        "gracze bez goli tylko powiekszaja plik — eksport ma ich odsiewac"
