"""
coupon_tracker.py – SQLite CRUD dla kuponów FootStats.

Tabela coupons: śledzi kupony od DRAFT do WON/LOST/VOID.
Migracja: dodaje coupon_id FK do istniejącej tabeli predictions.

Użycie:
    from footstats.core.coupon_tracker import save_coupon, update_coupon_status
    cid = save_coupon("draft", "A", legs, total_odds=12.5, stake_pln=10.0)
    update_coupon_status(cid, "WON", payout_pln=110.0)
"""

import json
import sqlite3
from footstats.config import DB_PATH
from footstats.utils.db import connect as _connect

# Statusy kuponu
STATUS_DRAFT   = "DRAFT"
STATUS_ACTIVE  = "ACTIVE"
STATUS_WON     = "WON"
STATUS_LOST    = "LOST"
STATUS_PARTIAL = "PARTIAL"
STATUS_VOID    = "VOID"

ACTIVE_STATUSES = (STATUS_DRAFT, STATUS_ACTIVE)
VALID_STATUSES = {STATUS_DRAFT, STATUS_ACTIVE, STATUS_WON, STATUS_LOST, STATUS_PARTIAL, STATUS_VOID}


# _connect imported from footstats.utils.db


def _exec(fn):
    """
    Otwiera połączenie, wykonuje fn(conn), commituje i zamyka.
    Gwarantuje conn.close() na Windows (WAL nie blokuje pliku po close).
    """
    conn = _connect()
    try:
        result = fn(conn)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_coupon_tables() -> None:
    """Tworzy tabele coupons i migruje predictions. Bezpieczne wielokrotne wywołanie."""
    def _fn(conn):
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS coupons (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at       TEXT NOT NULL DEFAULT (datetime('now')),
                phase            TEXT NOT NULL,
                status           TEXT NOT NULL DEFAULT 'DRAFT',
                kupon_type       TEXT NOT NULL,
                legs_json        TEXT NOT NULL DEFAULT '[]',
                total_odds       REAL,
                stake_pln        REAL,
                payout_pln       REAL,
                roi_pct          REAL,
                groq_reasoning   TEXT,
                decision_score   INTEGER,
                match_date_first TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_coupon_status  ON coupons(status);
            CREATE INDEX IF NOT EXISTS idx_coupon_created ON coupons(created_at);
        """)
        # Migration: coupon_id do predictions (bezpieczne jeśli już istnieje)
        try:
            conn.execute(
                "ALTER TABLE predictions ADD COLUMN coupon_id INTEGER REFERENCES coupons(id)"
            )
        except sqlite3.OperationalError:
            pass  # kolumna już istnieje
    _exec(_fn)


def save_coupon(
    phase: str,
    kupon_type: str,
    legs: list[dict],
    total_odds: float | None = None,
    stake_pln: float | None = None,
    groq_reasoning: str = "",
    decision_score: int | None = None,
    match_date_first: str | None = None,
) -> int:
    """
    Zapisuje nowy kupon (status=DRAFT). Zwraca id.

    phase:      'draft' | 'final'
    kupon_type: 'A' | 'B' | 'single'
    legs:       lista dict z kluczami: gospodarz, goscie, typ, kurs,
                opcjonalnie: pewnosc, liga, prediction_id
    """
    init_coupon_tables()
    legs_json = json.dumps(legs, ensure_ascii=False)

    def _fn(conn):
        cur = conn.execute(
            """
            INSERT INTO coupons
                (phase, status, kupon_type, legs_json, total_odds, stake_pln,
                 groq_reasoning, decision_score, match_date_first)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (phase, STATUS_DRAFT, kupon_type, legs_json,
             total_odds, stake_pln, groq_reasoning, decision_score, match_date_first),
        )
        return cur.lastrowid
    return _exec(_fn)


def update_coupon_status(
    coupon_id: int,
    status: str,
    payout_pln: float | None = None,
) -> None:
    """
    Aktualizuje status kuponu. Jeśli payout_pln podany — oblicza roi_pct.

    status: 'DRAFT' | 'ACTIVE' | 'WON' | 'LOST' | 'PARTIAL' | 'VOID'
    """
    init_coupon_tables()
    if status not in VALID_STATUSES:
        raise ValueError(f"Nieprawidłowy status kuponu: {status!r}")

    def _fn(conn):
        roi_pct = None
        if payout_pln is not None:
            row = conn.execute(
                "SELECT stake_pln FROM coupons WHERE id=?", (coupon_id,)
            ).fetchone()
            if row and row["stake_pln"]:
                roi_pct = round(
                    (payout_pln - row["stake_pln"]) / row["stake_pln"] * 100, 1
                )
        conn.execute(
            "UPDATE coupons SET status=?, payout_pln=?, roi_pct=? WHERE id=?",
            (status, payout_pln, roi_pct, coupon_id),
        )
    _exec(_fn)


def get_active_coupons() -> list[sqlite3.Row]:
    """Zwraca kupony ze statusem DRAFT lub ACTIVE, od najnowszych."""
    init_coupon_tables()

    def _fn(conn):
        return conn.execute(
            "SELECT * FROM coupons WHERE status IN (?, ?) ORDER BY created_at DESC",
            ACTIVE_STATUSES,
        ).fetchall()
    return _exec(_fn)


def get_draft_today() -> "sqlite3.Row | None":
    """Zwraca dzisiejszy kupon DRAFT (pierwszy znaleziony) lub None."""
    init_coupon_tables()
    from datetime import datetime, timezone
    # SQLite datetime('now') zwraca UTC — porównujemy z datą UTC, nie lokalną
    dzis = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _fn(conn):
        return conn.execute(
            """
            SELECT * FROM coupons
            WHERE status = 'DRAFT'
              AND date(created_at) = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (dzis,),
        ).fetchone()
    return _exec(_fn)


def promote_to_active(
    coupon_id: int,
    legs: list[dict] | None = None,
    groq_reasoning: str = "",
    decision_score: int | None = None,
    total_odds: float | None = None,
) -> None:
    """
    Promuje kupon DRAFT → ACTIVE (faza final).
    Opcjonalnie aktualizuje nogi, reasoning i score z analizy finalnej.
    """
    init_coupon_tables()
    legs_json = json.dumps(legs, ensure_ascii=False) if legs is not None else None

    def _fn(conn):
        if legs_json is not None:
            conn.execute(
                """
                UPDATE coupons
                SET status        = 'ACTIVE',
                    phase         = 'final',
                    legs_json     = ?,
                    groq_reasoning = ?,
                    decision_score = COALESCE(?, decision_score),
                    total_odds    = COALESCE(?, total_odds)
                WHERE id = ?
                """,
                (legs_json, groq_reasoning, decision_score, total_odds, coupon_id),
            )
        else:
            conn.execute(
                "UPDATE coupons SET status='ACTIVE', phase='final' WHERE id=?",
                (coupon_id,),
            )
    _exec(_fn)


def get_coupon_legs(coupon_id: int) -> list[dict]:
    """Zwraca listę nóg kuponu jako list[dict]. Pusty list jeśli kupon nie istnieje."""
    init_coupon_tables()

    def _fn(conn):
        row = conn.execute(
            "SELECT legs_json FROM coupons WHERE id=?", (coupon_id,)
        ).fetchone()
        if not row:
            return []
        return json.loads(row["legs_json"])
    return _exec(_fn)
