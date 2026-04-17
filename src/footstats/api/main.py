"""
api/main.py – Serwer API dla Dashboardu FootStats.
Udostępnia dane z SQLite do frontendu w formacie JSON.
"""

import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="FootStats API", version="1.0")

# Obsługa CORS dla deweloperki (Vite)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # W produkcji ogranicz do konkretnych domen
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = Path(__file__).parents[3] / "data" / "footstats_backtest.db"

def _get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

# --- Modele Danych ---

class BankrollStatus(BaseModel):
    balance: float
    updated_at: str

class CouponLeg(BaseModel):
    home: str
    away: str
    tip: str
    odds: float
    decision_score: Optional[int] = 0

class Coupon(BaseModel):
    id: int
    created_at: str
    phase: str
    status: str
    kupon_type: str
    legs: List[Dict]
    total_odds: float
    stake_pln: float
    payout_pln: Optional[float]
    roi_pct: Optional[float]
    match_date_first: Optional[str] = None

class BankrollUpdate(BaseModel):
    balance: float

class SettingsUpdate(BaseModel):
    version: Optional[str] = None
    pewniaczek_prog: Optional[float] = None
    kandydat_prog: Optional[float] = None
    kelly_fraction: Optional[int] = None
    kelly_w1_multipliers: Optional[str] = None  # np. "0.7/1.0/1.1"

# --- Endpointy ---

@app.get("/preview")
def serve_preview():
    """Serwuje podgląd dashboardu jako standalone HTML."""
    html_path = Path(__file__).parent / "preview.html"
    return FileResponse(html_path, media_type="text/html")

@app.get("/api/status")
def get_status():
    """Zwraca ogólny stan bota i bankrolla."""
    try:
        conn = _get_conn()
        bankroll = conn.execute("SELECT balance, updated_at FROM bankroll_state WHERE id = 1").fetchone()
        cutoff_30d = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        stats = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status IN ('WON','WIN') THEN 1 ELSE 0 END) as wins,
                SUM(payout_pln) as total_payout,
                SUM(stake_pln) as total_stake
            FROM coupons WHERE status IN ('WON','WIN','LOSE','LOST')
        """).fetchone()
        wins_30d = conn.execute("""
            SELECT COUNT(*) as n FROM coupons
            WHERE status IN ('WON','WIN') AND created_at >= ?
        """, (cutoff_30d,)).fetchone()

        roi = 0
        if stats and stats["total_stake"]:
            roi = round(((stats["total_payout"] or 0) - stats["total_stake"]) / stats["total_stake"] * 100, 1)

        return {
            "bankroll": bankroll["balance"] if bankroll else 0,
            "last_update": bankroll["updated_at"] if bankroll else None,
            "stats": {
                "total_finished": stats["total"] if stats else 0,
                "wins": stats["wins"] if stats else 0,
                "wins_last_30d": wins_30d["n"] if wins_30d else 0,
                "roi_pct": roi
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.post("/api/bankroll")
def update_bankroll(data: BankrollUpdate):
    """Aktualizuje stan bankrolla."""
    if data.balance < 0:
        raise HTTPException(status_code=400, detail="Saldo nie może być ujemne")
    conn = _get_conn()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT OR REPLACE INTO bankroll_state (id, balance, updated_at) VALUES (1, ?, ?)",
            (data.balance, now)
        )
        conn.commit()
        return {"ok": True, "balance": data.balance, "updated_at": now}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.get("/api/coupons/active")
def get_active_coupons():
    """Zwraca kupony niezakończone (ACTIVE, PENDING)."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM coupons WHERE status IN ('ACTIVE','PENDING') ORDER BY created_at DESC"
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["legs"] = json.loads(d["legs_json"])
            result.append(d)
        return result
    finally:
        conn.close()

@app.get("/api/coupons", response_model=List[Coupon])
def get_coupons(limit: int = 50):
    """Zwraca historię kuponów."""
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT * FROM coupons ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["legs"] = json.loads(d["legs_json"])
            result.append(d)
        return result
    finally:
        conn.close()

@app.get("/api/bankroll/history")
def get_bankroll_history(limit: int = 50):
    """Dane do wykresu Recharts."""
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT timestamp, new_balance 
            FROM bankroll_history 
            ORDER BY timestamp ASC 
            LIMIT ?
        """, (limit,)).fetchall()
        return [{"time": r["timestamp"][:16], "balance": r["new_balance"]} for r in rows]
    finally:
        conn.close()

@app.get("/api/config")
def get_bot_config():
    """Zwraca parametry konfiguracyjne bota (legacy)."""
    import footstats.config as cfg
    return {
        "version": cfg.VERSION,
        "kelly_fraction": cfg.AGENT_KELLY_FRACTION,
        "bankroll_start": cfg.AGENT_BANKROLL,
        "min_confidence": cfg.AGENT_KANDYDAT_PROG,
        "pewniaczek_prog": cfg.PEWNIACZEK_PROG,
        "ostatnie_n": cfg.OSTATNIE_N,
    }

def _settings_from_db() -> dict:
    """Czyta bot_settings z DB jako słownik key→value."""
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT key, value FROM bot_settings").fetchall()
        return {r["key"]: r["value"] for r in rows}
    except Exception:
        return {}
    finally:
        conn.close()

@app.get("/api/settings")
def get_settings():
    """Zwraca ustawienia z DB bot_settings (seed z config.py przy pierwszym starcie)."""
    import footstats.config as cfg
    # Upewnij się że tabela i wartości domyślne istnieją
    conn = _get_conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT
            )
        """)
        defaults = {
            "version":              cfg.VERSION,
            "pewniaczek_prog":      str(cfg.PEWNIACZEK_PROG),
            "kandydat_prog":        str(round(cfg.AGENT_KANDYDAT_PROG * 100, 1)),
            "kelly_fraction":       str(cfg.AGENT_KELLY_FRACTION),
            "kelly_w1_multipliers": "0.7 / 1.0 / 1.1",
        }
        for key, val in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO bot_settings (key, value, updated_at) VALUES (?,?,datetime('now'))",
                (key, val)
            )
        conn.commit()
        rows = conn.execute("SELECT key, value FROM bot_settings").fetchall()
        data = {r["key"]: r["value"] for r in rows}
    finally:
        conn.close()

    return {
        "version":              data.get("version",              cfg.VERSION),
        "pewniaczek_prog":      float(data.get("pewniaczek_prog", cfg.PEWNIACZEK_PROG)),
        "kandydat_prog":        float(data.get("kandydat_prog",   round(cfg.AGENT_KANDYDAT_PROG * 100, 1))),
        "kelly_fraction":       int(data.get("kelly_fraction",    cfg.AGENT_KELLY_FRACTION)),
        "kelly_w1_multipliers": data.get("kelly_w1_multipliers",  "0.7 / 1.0 / 1.1"),
        "kelly_w2_desc":        "forma bota (3× streak WIN/LOSE)",
    }

@app.post("/api/settings")
def update_settings(data: SettingsUpdate):
    """Zapisuje ustawienia do tabeli bot_settings w DB (trwałe po restarcie)."""
    updates: dict[str, str] = {}
    if data.version              is not None: updates["version"]              = data.version
    if data.pewniaczek_prog      is not None: updates["pewniaczek_prog"]      = str(data.pewniaczek_prog)
    if data.kandydat_prog        is not None: updates["kandydat_prog"]        = str(data.kandydat_prog)
    if data.kelly_fraction       is not None: updates["kelly_fraction"]       = str(data.kelly_fraction)
    if data.kelly_w1_multipliers is not None: updates["kelly_w1_multipliers"] = data.kelly_w1_multipliers

    if not updates:
        raise HTTPException(status_code=400, detail="Brak pól do aktualizacji")

    conn = _get_conn()
    try:
        for key, val in updates.items():
            conn.execute(
                "INSERT OR REPLACE INTO bot_settings (key, value, updated_at) VALUES (?,?,datetime('now'))",
                (key, val)
            )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "updated": list(updates.keys())}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
