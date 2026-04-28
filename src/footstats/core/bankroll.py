"""
bankroll.py – Zarządzanie kapitałem (Bankroll Management) dla FootStats.
Obsługuje trwałość salda w SQLite oraz logikę reinvestmentu.
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from footstats.config import AGENT_BANKROLL, AGENT_KELLY_FRACTION, DB_PATH
from footstats.utils.db import connect as _db_connect


def _connect() -> sqlite3.Connection:
    return _db_connect(wal=False, foreign_keys=False)

def init_bankroll_tables() -> None:
    """Tworzy tabele do śledzenia stanu i historii bankrolla."""
    conn = _connect()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS bankroll_state (
                id           INTEGER PRIMARY KEY CHECK (id = 1),
                balance      REAL NOT NULL,
                updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
            );
            
            CREATE TABLE IF NOT EXISTS bankroll_history (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp    TEXT NOT NULL DEFAULT (datetime('now')),
                change_pln   REAL NOT NULL,
                new_balance  REAL NOT NULL,
                type         TEXT NOT NULL,
                description  TEXT
            );
        """)
        # Inicjalizacja balansu startowego jeśli nie istnieje
        check = conn.execute("SELECT balance FROM bankroll_state WHERE id = 1").fetchone()
        if not check:
            conn.execute("INSERT INTO bankroll_state (id, balance) VALUES (1, ?)", (AGENT_BANKROLL,))
        conn.commit()
    finally:
        conn.close()

def get_current_bankroll() -> float:
    """Zwraca aktualny dostępny balans z bazy danych."""
    init_bankroll_tables()
    conn = _connect()
    try:
        row = conn.execute("SELECT balance FROM bankroll_state WHERE id = 1").fetchone()
        return row["balance"] if row else AGENT_BANKROLL
    finally:
        conn.close()

def update_bankroll(change: float, tx_type: str, description: str = "") -> float:
    """
    Aktualizuje balans o 'change' (może być ujemny).
    tx_type: 'BET', 'WIN', 'REFUND', 'MANUAL'
    """
    init_bankroll_tables()
    conn = _connect()
    try:
        current = get_current_bankroll()
        new_balance = current + change
        
        # Zapobiegaj ujemnemu balansowi przy zakładach (opcjonalnie)
        if new_balance < 0 and tx_type == 'BET':
            new_balance = 0
            
        conn.execute("UPDATE bankroll_state SET balance = ?, updated_at = datetime('now') WHERE id = 1", (new_balance,))
        conn.execute("""
            INSERT INTO bankroll_history (change_pln, new_balance, type, description)
            VALUES (?, ?, ?, ?)
        """, (change, new_balance, tx_type, description))
        
        conn.commit()
        return new_balance
    finally:
        conn.close()

def process_bet(stake: float, description: str = "") -> float:
    """Odejmuje dawkę od bankrolla."""
    return update_bankroll(-stake, "BET", description)

def process_win(payout: float, description: str = "") -> float:
    """
    Dodaje wygraną do bankrolla zgodnie z logiką 50% reinvestmentu.
    User: '50% z wygranych kuponów'.
    Aplikujemy: reinvest = payout * 0.5
    """
    reinvest_amount = round(payout * 0.5, 2)
    return update_bankroll(reinvest_amount, "WIN", f"Wypłata {payout} PLN (50% reinwestycji): {description}")

if __name__ == "__main__":
    init_bankroll_tables()
    print(f"Aktualny bankroll: {get_current_bankroll()} PLN")
