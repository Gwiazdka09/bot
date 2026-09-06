"""
player_db.py — Faza 1 bazy graczy: persystencja statystyk zawodników w SQLite
(`data/footstats_backtest.db`) + wyliczanie goal_share (udziału w golach drużyny).

goal_share zasila Kontuzje v2 (`injury_lambda_factors`): utrata strzelca o share 0.4
karze λ mocniej niż rezerwowy 0.02. Denominator = suma goli zapisanych graczy zespołu
(topscorers ≈ większość goli), więc share jest miarą względną, spójną per drużyna.

Zero prod Neon — świadomie lokalny SQLite (reference/cache), testowalny na tmp db.
"""
from __future__ import annotations

import functools
import json
import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from footstats.config import DB_PATH

log = logging.getLogger(__name__)
from footstats.utils.normalize import normalize_team_name

# Zamrozony zrzut goli, shipowany W OBRAZIE jak `team_mappings.json`.
#
# DLACZEGO ISTNIEJE: `data/footstats_backtest.db` jest wykluczony i z
# `.dockerignore`, i z `.gcloudignore`, wiec w kontenerze jobow tej bazy NIE MA.
# sqlite3 tworzy wtedy pusty plik, a pierwszy odczyt konczy sie `no such table:
# player_stats`. Zmierzone na produkcji 07.09.2026: 105 takich wpisow na stderr
# w jednym przebiegu. Skutek siegal dalej niz sama korekta lambda za kontuzje —
# `daily_phases._policz_edge_absencji` wychodzil wtedy na `continue`, wiec
# `p_over_abs`, `edge_absencje` i `rynek_p_over` nie powstawaly NIGDY i caly
# kanal team-news byl martwy.
#
# Zrzut jest TYLKO DO ODCZYTU i swiadomie zamrozony: joby do bazy pisza, ale
# zapis w kontenerze i tak przepada, wiec wrzucenie calej bazy zamaskowaloby te
# ulotnosc zamiast ja pokazac. Odswiezanie: `scripts/eksport_player_stats.py`.
SCIEZKA_ZRZUTU = Path(DB_PATH).parent / "player_stats.json"


@functools.lru_cache(maxsize=1)
def _zrzut_goli() -> dict:
    """`{(team_norm, sezon): {gracz: gole}}` ze zrzutu. Pusty gdy brak pliku.

    Wczytywane raz na proces — plik ma ~200 KB, ale `team_goal_shares` wola sie
    po kilkadziesiat razy na przebieg (kazda druzyna razy `lookback` sezonow).
    """
    try:
        dane = json.loads(SCIEZKA_ZRZUTU.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        # Brak pliku to stan mozliwy (dev bez eksportu) — debug. Plik, ktory JEST,
        # ale sie nie parsuje, to zepsuty artefakt w obrazie i musi krzyczec.
        poziom = log.debug if isinstance(e, FileNotFoundError) else log.warning
        poziom("player_db: zrzut %s nie do odczytania (%s: %s)",
               SCIEZKA_ZRZUTU, type(e).__name__, e)
        return {}

    tabela: dict = {}
    odrzucone = 0
    for w in dane:
        try:
            klucz = (str(w["team_norm"]), int(w["season"]))
            gole = int(w["goals"] or 0)
        except (KeyError, TypeError, ValueError) as e:
            # Zbiorczo, nie per wiersz: przy zepsutym eksporcie byloby to tysiace
            # linii, a szum niszczy alarmy tak samo skutecznie jak cisza.
            odrzucone += 1
            if odrzucone == 1:
                log.debug("player_db: wiersz zrzutu odrzucony (%s: %s)",
                          type(e).__name__, e)
            continue
        if gole > 0:
            tabela.setdefault(klucz, {})[str(w["name"])] = gole
    if odrzucone:
        log.warning("player_db: zrzut ma %d wierszy nie do odczytania z %d —"
                    " przelicz go `scripts/eksport_player_stats.py`",
                    odrzucone, len(dane))
    return tabela

_DDL = """
CREATE TABLE IF NOT EXISTS player_stats (
    name         TEXT    NOT NULL,
    team_norm    TEXT    NOT NULL,
    team_display TEXT,
    league       TEXT,
    season       INTEGER NOT NULL,
    goals        INTEGER DEFAULT 0,
    assists      INTEGER DEFAULT 0,
    minutes      INTEGER DEFAULT 0,
    rating       REAL,
    xg           REAL,
    updated_at   TEXT,
    PRIMARY KEY (name, team_norm, season)
)
"""

# Kolumny dokładane migracyjnie do istniejących tabel (ALTER ADD COLUMN)
_OPTIONAL_COLS = {"rating": "REAL", "xg": "REAL"}


_DDL_TEAM = """
CREATE TABLE IF NOT EXISTS team_stats (
    team_norm      TEXT    NOT NULL,
    team_display   TEXT,
    league         TEXT    NOT NULL,
    season         INTEGER NOT NULL,
    matches        INTEGER DEFAULT 0,
    goals_for      INTEGER DEFAULT 0,
    goals_against  INTEGER DEFAULT 0,
    avg_rating     REAL,
    possession     REAL,
    clean_sheets   INTEGER,
    big_chances    INTEGER,
    updated_at     TEXT,
    PRIMARY KEY (team_norm, league, season)
)
"""


def _connect(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    return con


# B6 — jedyne dynamicznie sklejane SQL w projekcie.
#
# `ALTER TABLE ... ADD COLUMN {col} {typ}` musi iść f-stringiem, bo SQLite nie
# pozwala parametryzować IDENTYFIKATORÓW — `?` działa dla wartości, nie dla nazw
# kolumn. Parametryzacja jest tu fizycznie niemożliwa, więc jedyną obroną jest
# walidacja.
#
# DZIŚ TO NIE JEST PODATNOŚĆ i nie udaje, że jest: `_OPTIONAL_COLS` to stała
# w module, nie dane z zewnątrz. Ten guard zamienia „bezpieczne, bo nikt tego nie
# zmienił" na „bezpieczne, bo sprawdzane" — różnica robi się istotna w dniu,
# w którym ktoś zechce wziąć listę kolumn z konfiguracji albo z odpowiedzi źródła,
# a nikt już nie będzie pamiętał, że ten f-string jest bezbronny.
_DOZWOLONE_TYPY = frozenset({"REAL", "INTEGER", "TEXT"})
_WZORZEC_KOLUMNY = re.compile(r"^[a-z_][a-z0-9_]*$")


def _sprawdz_identyfikator(kolumna: str, typ: str) -> None:
    """Przepuszcza wyłącznie prostą nazwę kolumny i typ z zamkniętej listy.

    Sprawdzamy OBA pola: walidacja samej nazwy zostawiałaby drugą połowę
    zapytania otwartą.
    """
    if not _WZORZEC_KOLUMNY.match(kolumna or ""):
        raise ValueError(f"niedozwolona nazwa kolumny: {kolumna!r}")
    if typ not in _DOZWOLONE_TYPY:
        raise ValueError(f"niedozwolony typ kolumny: {typ!r}")


def init_player_table(db_path: Path | str = DB_PATH) -> None:
    """Tworzy tabelę player_stats + dokłada brakujące kolumny (migracja rating/xg)."""
    with _connect(db_path) as con:
        con.execute(_DDL)
        existing = {r["name"] for r in con.execute("PRAGMA table_info(player_stats)")}
        for col, typ in _OPTIONAL_COLS.items():
            _sprawdz_identyfikator(col, typ)
            if col not in existing:
                con.execute(  # nosec B608 — identyfikatory sprawdzone wyżej, patrz B6
                    f"ALTER TABLE player_stats ADD COLUMN {col} {typ}"
                )


def upsert_players(rows: list[dict], db_path: Path | str = DB_PATH) -> int:
    """
    Wstawia/aktualizuje statystyki graczy. Konflikt (name, team_norm, season) →
    nadpisuje (najnowszy fetch wygrywa). Zwraca liczbę przetworzonych wierszy.

    row: {name, team, league, season, goals, assists, minutes}
    """
    init_player_table(db_path)
    now = datetime.now().isoformat()
    n = 0
    with _connect(db_path) as con:
        for r in rows:
            name = (r.get("name") or "").strip()
            team = (r.get("team") or "").strip()
            if not name or not team:
                continue
            rating = r.get("rating")
            xg = r.get("xg")
            con.execute(
                """
                INSERT INTO player_stats
                    (name, team_norm, team_display, league, season, goals, assists,
                     minutes, rating, xg, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name, team_norm, season) DO UPDATE SET
                    team_display = excluded.team_display,
                    league       = excluded.league,
                    goals        = excluded.goals,
                    assists      = excluded.assists,
                    minutes      = excluded.minutes,
                    rating       = COALESCE(excluded.rating, player_stats.rating),
                    xg           = COALESCE(excluded.xg, player_stats.xg),
                    updated_at   = excluded.updated_at
                """,
                (
                    name,
                    normalize_team_name(team),
                    team,
                    r.get("league"),
                    int(r.get("season") or 0),
                    int(r.get("goals") or 0),
                    int(r.get("assists") or 0),
                    int(r.get("minutes") or 0),
                    float(rating) if rating is not None else None,
                    float(xg) if xg is not None else None,
                    now,
                ),
            )
            n += 1
    return n


def team_goal_shares(
    team: str, season: int, db_path: Path | str = DB_PATH
) -> dict[str, float]:
    """
    Zwraca {nazwa_gracza: udział_w_golach 0-1} dla drużyny w sezonie.
    Udział = gole gracza / suma goli zapisanych graczy zespołu. Pusty dict gdy
    brak drużyny / suma goli = 0 (bezpieczny fallback → injury model używa flat).
    """
    if not team:
        return {}
    tn = normalize_team_name(team)
    try:
        with _connect(db_path) as con:
            rows = con.execute(
                "SELECT name, goals FROM player_stats WHERE team_norm = ? AND season = ?",
                (tn, int(season)),
            ).fetchall()
        gole = {r["name"]: int(r["goals"] or 0) for r in rows if r["goals"]}
    except sqlite3.Error as e:
        # Zrzut wchodzi WYLACZNIE gdy baza padla — nie gdy po prostu nie zna
        # druzyny. Inaczej zdrowa, ale swiezo zalozona baza po cichu dostawalaby
        # zamrozone liczby ze zrzutu i nikt by nie zauwazyl, ze jest pusta.
        gole = dict(_zrzut_goli().get((tn, int(season)), {}))
        if not gole:
            # Baza padla I zrzutu nie ma — dopiero TERAZ korekta lambda za
            # kontuzje naprawde przestaje dzialac, i dopiero teraz jest o czym
            # krzyczec. Do 07.09.2026 to ostrzezenie leciało przy KAZDYM
            # odczycie w kontenerze: 105 razy w jednym przebiegu, czyli szum,
            # ktory zabija alarmy tak samo skutecznie jak cisza.
            log.warning("player_db: nie moge odczytac goli %s/%s (%s: %s)"
                        " i nie ma zrzutu — goal_share = 0, korekta lambda za"
                        " kontuzje NIE zadziala", team, season, type(e).__name__, e)
            return {}
        log.debug("player_db: baza niedostepna dla %s/%s (%s) — uzywam zrzutu",
                  team, season, type(e).__name__)

    if not gole:
        return {}
    total = sum(gole.values())
    if total <= 0:
        return {}
    return {n: g / total for n, g in gole.items()}


def get_team_players(
    team: str, season: int, db_path: Path | str = DB_PATH
) -> list[dict]:
    """
    Pełne wiersze graczy drużyny w sezonie (name, goals, assists, minutes, rating, xg),
    posortowane malejąco po golach. Pusta lista gdy brak/błąd. Rating = ocena 1-10
    (Sofascore, gdy dostępna), xg = expected goals.
    """
    if not team:
        return []
    tn = normalize_team_name(team)
    try:
        with _connect(db_path) as con:
            rows = con.execute(
                "SELECT name, goals, assists, minutes, rating, xg FROM player_stats "
                "WHERE team_norm = ? AND season = ? ORDER BY goals DESC",
                (tn, int(season)),
            ).fetchall()
    except sqlite3.Error as e:
        log.warning("player_db: nie moge odczytac skladu %s/%s (%s: %s) —"
                    " oddaje PUSTA liste, nie do odroznienia od nieznanej druzyny",
                    team, season, type(e).__name__, e)
        return []
    return [dict(r) for r in rows]


def team_goal_shares_recent(
    team: str, season: int, lookback: int = 2, db_path: Path | str = DB_PATH
) -> dict[str, float]:
    """
    goal_shares dla drużyny z najświeższego dostępnego sezonu: próbuje `season`,
    potem season-1 ... season-lookback. Zwraca pierwszy niepusty (off-season /
    przerwa międzysezonowa → używa poprzedniej kampanii). {} gdy brak w oknie.
    """
    for s in range(int(season), int(season) - lookback - 1, -1):
        shares = team_goal_shares(team, s, db_path=db_path)
        if shares:
            return shares
    return {}


# ── team_stats: siła drużyn (kadr MŚ → Poisson λ, model nie ma historii kadr) ──

def init_team_table(db_path: Path | str = DB_PATH) -> None:
    """Tworzy tabelę team_stats jeśli nie istnieje."""
    with _connect(db_path) as con:
        con.execute(_DDL_TEAM)


def upsert_team_stats(rows: list[dict], db_path: Path | str = DB_PATH) -> int:
    """
    Wstawia/aktualizuje statystyki drużyn (kadr). Klucz (team_norm, league, season).
    row: {team, league, season, matches, goals_for, goals_against, avg_rating,
          possession, clean_sheets, big_chances}. Zwraca liczbę wierszy.
    """
    init_team_table(db_path)
    now = datetime.now().isoformat()
    n = 0
    with _connect(db_path) as con:
        for r in rows:
            team = (r.get("team") or "").strip()
            league = (r.get("league") or "").strip()
            if not team or not league:
                continue
            con.execute(
                """
                INSERT INTO team_stats
                    (team_norm, team_display, league, season, matches, goals_for,
                     goals_against, avg_rating, possession, clean_sheets, big_chances, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(team_norm, league, season) DO UPDATE SET
                    team_display  = excluded.team_display,
                    matches       = excluded.matches,
                    goals_for     = excluded.goals_for,
                    goals_against = excluded.goals_against,
                    avg_rating    = COALESCE(excluded.avg_rating, team_stats.avg_rating),
                    possession    = COALESCE(excluded.possession, team_stats.possession),
                    clean_sheets  = COALESCE(excluded.clean_sheets, team_stats.clean_sheets),
                    big_chances   = COALESCE(excluded.big_chances, team_stats.big_chances),
                    updated_at    = excluded.updated_at
                """,
                (
                    normalize_team_name(team), team, league, int(r.get("season") or 0),
                    int(r.get("matches") or 0), int(r.get("goals_for") or 0),
                    int(r.get("goals_against") or 0),
                    _optional_float(r.get("avg_rating")),
                    _optional_float(r.get("possession")),
                    _optional_int(r.get("clean_sheets")),
                    _optional_int(r.get("big_chances")),
                    now,
                ),
            )
            n += 1
    return n


def get_team_stats(
    team: str, season: int, db_path: Path | str = DB_PATH
) -> dict | None:
    """Statystyki drużyny (najświeższy wpis dla sezonu). None gdy brak."""
    if not team:
        return None
    tn = normalize_team_name(team)
    try:
        with _connect(db_path) as con:
            row = con.execute(
                "SELECT * FROM team_stats WHERE team_norm = ? AND season = ? "
                "ORDER BY matches DESC LIMIT 1",
                (tn, int(season)),
            ).fetchone()
    except sqlite3.Error as e:
        log.warning("player_db: nie moge odczytac statystyk %s/%s (%s: %s) —"
                    " mecz pojdzie bez nich", team, season, type(e).__name__, e)
        return None
    return dict(row) if row else None


def team_attack_defense(
    team: str, season: int, db_path: Path | str = DB_PATH
) -> tuple[float, float] | None:
    """
    (λ_atak, λ_obrona) = (gole/mecz, tracone/mecz) — wejście Poissona dla kadr.
    None gdy brak drużyny lub matches=0.
    """
    st = get_team_stats(team, season, db_path=db_path)
    if not st:
        return None
    m = int(st.get("matches") or 0)
    if m <= 0:
        return None
    return (int(st.get("goals_for") or 0) / m, int(st.get("goals_against") or 0) / m)


def _optional_float(v: object) -> float | None:
    """CISZA CELOWA (tak samo `_optional_int`): konwerter pola opcjonalnego,
    wolany dla kazdego pola kazdego zawodnika. `None` to uczciwe "nie wiadomo",
    a puste pole w danych zrodlowych jest stanem normalnym."""
    try:
        return float(v) if v is not None else None
    except (ValueError, TypeError):
        return None


def _optional_int(v: object) -> int | None:
    try:
        return int(float(v)) if v is not None else None
    except (ValueError, TypeError):
        return None
