#!/usr/bin/env python
"""eksport_player_stats.py — zrzut `player_stats` do pliku shipowanego w obrazie.

DLACZEGO TO ISTNIEJE. `data/footstats_backtest.db` jest wykluczony i z
`.dockerignore` (linia 11), i z `.gcloudignore` (`/data/*`), więc w kontenerze
jobów tej bazy NIE MA. `sqlite3` tworzy wtedy pusty plik, a pierwszy odczyt
kończy się `no such table: player_stats`. Zmierzone na produkcji 2026-09-07:
105 takich wpisów w logach jednego przebiegu, na `stderr`:

    player_db: nie moge odczytac goli AZ Alkmaar/2026
    (OperationalError: no such table: player_stats) — goal_share = 0,
    korekta lambda za kontuzje NIE zadziala

Skutek: `_policz_edge_absencji` wychodzi na `continue`, więc `p_over_abs`,
`edge_absencje` i `rynek_p_over` nie powstają NIGDY. Cały kanał team-news jest
przez to martwy niezależnie od tego, czy FotMob odpowiada.

DLACZEGO NIE WRZUCAMY CAŁEJ BAZY. `backtest.db` waży 1.7 MB, więc rozmiar nie
jest problemem — ale joby do tej bazy PISZĄ (rozliczanie wyników), a zapis do
pliku w obrazie i tak przepada po zakończeniu zadania. Wrzucenie bazy zamroziłoby
snapshot i sprawiło, że ta ulotność stałaby się mniej widoczna, nie bardziej.
Osobny plik tylko do odczytu mówi wprost, czym jest: zamrożonym zrzutem.

ODŚWIEŻANIE. Zrzut się starzeje — `team_goal_shares_recent` sięga maksymalnie
`lookback` sezonów wstecz, więc plik z jednym sezonem przestanie działać po
zmianie kampanii. Przepuścić ten skrypt przed budową obrazu, kiedy `player_stats`
było niedawno odświeżone.

    python scripts/eksport_player_stats.py
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

_KORZEN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_KORZEN / "src"))

# Wyłącznie kolumny potrzebne do `team_goal_shares`. Reszta (`rating`, `xg`,
# `minutes`) nie jest czytana przez tor kontuzji, a każda dołożona kolumna to
# kolejna rzecz, która może się rozjechać między bazą a zrzutem.
KOLUMNY = ("name", "team_norm", "season", "goals")


def zrzut(db: Path) -> list[dict]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        con.row_factory = sqlite3.Row
        wiersze = con.execute(
            f"SELECT {', '.join(KOLUMNY)} FROM player_stats"  # nosec B608 — stala modulu
            " WHERE goals IS NOT NULL AND goals > 0"
        ).fetchall()
    finally:
        con.close()
    return [{k: w[k] for k in KOLUMNY} for w in wiersze]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--baza", default=str(_KORZEN / "data" / "footstats_backtest.db"))
    ap.add_argument("--wyjscie", default=str(_KORZEN / "data" / "player_stats.json"))
    args = ap.parse_args()

    baza = Path(args.baza)
    if not baza.exists():
        raise SystemExit(f"Brak bazy: {baza}")

    dane = zrzut(baza)
    if not dane:
        raise SystemExit("player_stats puste — zrzut bylby gorszy niz jego brak.")

    sezony = sorted({int(w["season"]) for w in dane})
    druzyny = len({w["team_norm"] for w in dane})
    Path(args.wyjscie).write_text(
        json.dumps(dane, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    rozmiar = Path(args.wyjscie).stat().st_size / 1024
    print(f"Zapisane: {args.wyjscie}")
    print(f"  {len(dane)} graczy z golami, {druzyny} druzyn, sezony {sezony}")
    print(f"  rozmiar {rozmiar:.0f} KB")


if __name__ == "__main__":
    main()
