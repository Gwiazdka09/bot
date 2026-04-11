"""
api/main.py – Serwer API dla Dashboardu FootStats.
Udostępnia dane z SQLite do frontendu w formacie JSON.
"""

import sqlite3
import json
from pathlib import Path
from typing import List, Dict, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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

# --- Endpointy ---

@app.get("/api/status")
def get_status():
    """Zwraca ogólny stan bota i bankrolla."""
    try:
        conn = _get_conn()
        bankroll = conn.execute("SELECT balance, updated_at FROM bankroll_state WHERE id = 1").fetchone()
        stats = conn.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status = 'WON' THEN 1 ELSE 0 END) as wins,
                SUM(payout_pln) as total_payout,
                SUM(stake_pln) as total_stake
            FROM coupons WHERE status IN ('WON', 'LOST')
        """).fetchone()
        
        roi = 0
        if stats and stats["total_stake"]:
            roi = round(((stats["total_payout"] or 0) - stats["total_stake"]) / stats["total_stake"] * 100, 1)
            
        return {
            "bankroll": bankroll["balance"] if bankroll else 0,
            "last_update": bankroll["updated_at"] if bankroll else None,
            "stats": {
                "total_finished": stats["total"] if stats else 0,
                "wins": stats["wins"] if stats else 0,
                "roi_pct": roi
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.get("/api/coupons", response_model=List[Coupon])
def get_coupons(limit: int = 20):
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
    """Zwraca parametry konfiguracyjne bota."""
    import footstats.config as cfg
    return {
        "version": cfg.VERSION,
        "kelly_fraction": cfg.AGENT_KELLY_FRACTION,
        "bankroll_start": cfg.AGENT_BANKROLL,
        "min_confidence": cfg.AGENT_KANDYDAT_PROG,
        "pewniaczek_prog": cfg.PEWNIACZEK_PROG,
        "ostatnie_n": cfg.OSTATNIE_N,
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
