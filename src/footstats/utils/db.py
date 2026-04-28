"""Shared SQLite connection factory for FootStats."""

import sqlite3
from footstats.config import DB_PATH


def connect(wal: bool = True, foreign_keys: bool = True) -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    if wal:
        conn.execute("PRAGMA journal_mode=WAL")
    if foreign_keys:
        conn.execute("PRAGMA foreign_keys=ON")
    return conn
