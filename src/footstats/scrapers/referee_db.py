from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

_DEFAULT_DB = Path(__file__).parents[3] / "data" / "footstats_backtest.db"

_DDL = """
CREATE TABLE IF NOT EXISTS referees (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL UNIQUE,
    country      TEXT,
    avg_yellow   REAL,
    avg_red      REAL,
    avg_goals    REAL,
    home_win_pct REAL,
    n_matches    INTEGER,
    updated_at   TEXT
);
"""

_KARTKOWY_THRESHOLD = 4.3
_BRAMKOWY_THRESHOLD = 3.0


def _db(db_path: Path | None) -> Path:
    return db_path or _DEFAULT_DB


def init_referee_table(db_path: Path = None) -> None:
    path = _db(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute(_DDL)
        conn.commit()
    finally:
        conn.close()


def upsert_referee(name: str, stats: dict, db_path: Path = None) -> None:
    init_referee_table(db_path)
    path = _db(db_path)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            INSERT INTO referees (name, country, avg_yellow, avg_red, avg_goals,
                                  home_win_pct, n_matches, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                country      = excluded.country,
                avg_yellow   = excluded.avg_yellow,
                avg_red      = excluded.avg_red,
                avg_goals    = excluded.avg_goals,
                home_win_pct = excluded.home_win_pct,
                n_matches    = excluded.n_matches,
                updated_at   = excluded.updated_at
            """,
            (
                name,
                stats.get("country"),
                stats.get("avg_yellow"),
                stats.get("avg_red"),
                stats.get("avg_goals"),
                stats.get("home_win_pct"),
                stats.get("n_matches"),
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_referee(name: str, db_path: Path = None) -> dict | None:
    init_referee_table(db_path)
    path = _db(db_path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM referees WHERE name = ?", (name,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return dict(row)


def referee_signal(name: str, db_path: Path = None) -> str:
    """Return one of: KARTKOWY | BRAMKOWY | NEUTRALNY | NIEZNANY"""
    ref = get_referee(name, db_path=db_path)
    if ref is None:
        return "NIEZNANY"
    avg_y = ref.get("avg_yellow") or 0.0
    avg_g = ref.get("avg_goals") or 0.0
    if avg_y > _KARTKOWY_THRESHOLD:
        return "KARTKOWY"
    if avg_g > _BRAMKOWY_THRESHOLD:
        return "BRAMKOWY"
    return "NEUTRALNY"
