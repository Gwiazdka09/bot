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
from fastapi.responses import FileResponse, RedirectResponse
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

@app.get("/")
def root():
    """Przekierowanie z / na /preview."""
    return RedirectResponse(url="/preview")

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

# ============================================================
# KREATOR KUPONU
# ============================================================

import os

_MATCHES_CACHE: list = []  # prosty cache w pamięci (reset przy restarcie)


def _fetch_predictions() -> list:
    """Pobiera predykcje z Bzzoiro lub zwraca dane mock."""
    try:
        from footstats.scrapers.bzzoiro import BzzoiroClient
        from footstats.config import ENV_BZZOIRO
        key = os.getenv(ENV_BZZOIRO, "").strip()
        if not key:
            return _mock_predictions()
        client = BzzoiroClient(key)
        preds = client.predykcje_tygodnia()
        return preds if preds else _mock_predictions()
    except Exception:
        return _mock_predictions()


def _mock_predictions() -> list:
    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    return [
        {"id": "m001", "gosp": "Legia Warszawa",   "gosc": "Lech Poznań",       "liga": "PKO BP Ekstraklasa", "data": today,    "godzina": "18:00",
         "pred_ml": {"prob_home_win": 0.52, "prob_draw": 0.28, "prob_away_win": 0.20, "prob_over_25": 0.61, "prob_btts_yes": 0.48},
         "odds": {"home": 1.85, "draw": 3.40, "away": 4.10, "over_2_5": 1.72, "under_2_5": 2.05, "btts": 1.90}},
        {"id": "m002", "gosp": "Ajax Amsterdam",   "gosc": "PSV Eindhoven",      "liga": "Eredivisie",         "data": today,    "godzina": "20:45",
         "pred_ml": {"prob_home_win": 0.45, "prob_draw": 0.25, "prob_away_win": 0.30, "prob_over_25": 0.72, "prob_btts_yes": 0.58},
         "odds": {"home": 2.10, "draw": 3.30, "away": 3.50, "over_2_5": 1.58, "under_2_5": 2.40, "btts": 1.75}},
        {"id": "m003", "gosp": "Roma",             "gosc": "Lazio",              "liga": "Serie A",            "data": today,    "godzina": "20:45",
         "pred_ml": {"prob_home_win": 0.40, "prob_draw": 0.30, "prob_away_win": 0.30, "prob_over_25": 0.58, "prob_btts_yes": 0.52},
         "odds": {"home": 2.30, "draw": 3.20, "away": 3.10, "over_2_5": 1.80, "under_2_5": 1.98, "btts": 1.85}},
        {"id": "m004", "gosp": "RB Leipzig",       "gosc": "Borussia Dortmund",  "liga": "Bundesliga",         "data": today,    "godzina": "18:30",
         "pred_ml": {"prob_home_win": 0.38, "prob_draw": 0.27, "prob_away_win": 0.35, "prob_over_25": 0.68, "prob_btts_yes": 0.55},
         "odds": {"home": 2.45, "draw": 3.25, "away": 2.80, "over_2_5": 1.65, "under_2_5": 2.20, "btts": 1.80}},
        {"id": "m005", "gosp": "Atlético Madrid",  "gosc": "Villarreal",         "liga": "La Liga",            "data": today,    "godzina": "21:00",
         "pred_ml": {"prob_home_win": 0.55, "prob_draw": 0.24, "prob_away_win": 0.21, "prob_over_25": 0.55, "prob_btts_yes": 0.44},
         "odds": {"home": 1.75, "draw": 3.60, "away": 4.50, "over_2_5": 1.85, "under_2_5": 1.93, "btts": 2.00}},
        {"id": "m006", "gosp": "Sporting CP",      "gosc": "Benfica",            "liga": "Primeira Liga",      "data": today,    "godzina": "21:30",
         "pred_ml": {"prob_home_win": 0.44, "prob_draw": 0.26, "prob_away_win": 0.30, "prob_over_25": 0.63, "prob_btts_yes": 0.50},
         "odds": {"home": 2.20, "draw": 3.40, "away": 3.20, "over_2_5": 1.72, "under_2_5": 2.10, "btts": 1.88}},
        {"id": "m007", "gosp": "Djurgårdens IF",   "gosc": "Malmö FF",           "liga": "Allsvenskan",        "data": tomorrow, "godzina": "17:00",
         "pred_ml": {"prob_home_win": 0.35, "prob_draw": 0.28, "prob_away_win": 0.37, "prob_over_25": 0.60, "prob_btts_yes": 0.49},
         "odds": {"home": 2.60, "draw": 3.15, "away": 2.70, "over_2_5": 1.78, "under_2_5": 2.00, "btts": 1.88}},
        {"id": "m008", "gosp": "Feyenoord",        "gosc": "AZ Alkmaar",         "liga": "Eredivisie",         "data": tomorrow, "godzina": "18:45",
         "pred_ml": {"prob_home_win": 0.50, "prob_draw": 0.25, "prob_away_win": 0.25, "prob_over_25": 0.70, "prob_btts_yes": 0.55},
         "odds": {"home": 1.95, "draw": 3.50, "away": 3.80, "over_2_5": 1.62, "under_2_5": 2.25, "btts": 1.80}},
    ]


def _to_pct(v, default: float = 33.0) -> float:
    """Konwertuje ułamek 0-1 lub procent na procenty 0-100."""
    if v is None:
        return default
    f = float(v)
    return round(f * 100 if 0 < f < 1.0 else f, 1)


class AnalyzeRequest(BaseModel):
    match_ids: List[str]


class SelectionItem(BaseModel):
    match_id: str
    home: str
    away: str
    tip: str
    odds: float
    win_prob: float  # 0–100


class KellyRequest(BaseModel):
    selections: List[SelectionItem]


class PlaceCouponRequest(BaseModel):
    selections: List[SelectionItem]
    total_odds: float
    stake_pln: float
    match_date: Optional[str] = None


class SettleRequest(BaseModel):
    days_back: Optional[int] = 3
    dry_run: Optional[bool] = False


@app.get("/api/matches/today")
def get_matches_today():
    """Zwraca mecze na dziś/jutro z predykcjami ML (Bzzoiro lub mock)."""
    global _MATCHES_CACHE
    preds = _fetch_predictions()
    today    = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    filtered = [m for m in preds if m.get("data", "") in (today, tomorrow)]
    if not filtered:
        filtered = preds[:15]
    # Sortuj: preferuj wyraźnych faworytów (prob daleko od 33%)
    def _interest(m):
        ml = m.get("pred_ml") or {}
        ph = _to_pct(ml.get("prob_home_win"), 33.0)
        return -abs(ph - 33.0)
    filtered.sort(key=_interest)
    _MATCHES_CACHE = filtered[:15]
    return _MATCHES_CACHE


@app.post("/api/matches/analyze")
def analyze_matches(req: AnalyzeRequest):
    """Zwraca szczegółową analizę (probs + typy z kursami) dla wybranych meczów."""
    global _MATCHES_CACHE
    if not _MATCHES_CACHE:
        _MATCHES_CACHE = _fetch_predictions()

    id_set  = {str(i) for i in req.match_ids}
    results = []
    for m in _MATCHES_CACHE:
        if str(m.get("id")) not in id_set:
            continue
        ml   = m.get("pred_ml") or {}
        odds = m.get("odds") or {}

        ph  = _to_pct(ml.get("prob_home_win"), 40.0)
        pr  = _to_pct(ml.get("prob_draw"),     25.0)
        pp  = _to_pct(ml.get("prob_away_win"), 35.0)
        po  = _to_pct(ml.get("prob_over_25"),  55.0)
        pbt = _to_pct(ml.get("prob_btts_yes"), 45.0)

        # Normalizuj 1X2 do 100%
        s12 = ph + pr + pp or 100.0
        ph  = round(ph / s12 * 100, 1)
        pr  = round(pr / s12 * 100, 1)
        pp  = round(100.0 - ph - pr, 1)

        # Podwójne szanse (implied odds)
        def _dc_odds(a, b):
            if not a or not b:
                return None
            return round(1 / (1/a + 1/b), 2)

        tips = []
        if odds.get("home"):
            tips.append({"tip": "1",        "label": "1 – Gosp.",     "odds": odds["home"],              "prob": ph,        "color": "indigo"})
        if odds.get("draw"):
            tips.append({"tip": "X",        "label": "X – Remis",     "odds": odds["draw"],              "prob": pr,        "color": "slate"})
        if odds.get("away"):
            tips.append({"tip": "2",        "label": "2 – Gość",      "odds": odds["away"],              "prob": pp,        "color": "violet"})
        dc1x = _dc_odds(odds.get("home"), odds.get("draw"))
        if dc1x:
            tips.append({"tip": "1X",       "label": "1X – Gosp./Rem.","odds": dc1x,                    "prob": round(ph + pr, 1), "color": "blue"})
        dcx2 = _dc_odds(odds.get("draw"), odds.get("away"))
        if dcx2:
            tips.append({"tip": "X2",       "label": "X2 – Rem./Gość","odds": dcx2,                    "prob": round(pr + pp, 1), "color": "purple"})
        if odds.get("over_2_5"):
            tips.append({"tip": "Over 2.5", "label": "Over 2.5",      "odds": odds["over_2_5"],          "prob": po,        "color": "emerald"})
        if odds.get("btts"):
            tips.append({"tip": "BTTS",     "label": "Obie strzelą",  "odds": odds["btts"],              "prob": pbt,       "color": "amber"})

        results.append({
            "id": m["id"], "home": m["gosp"], "away": m["gosc"],
            "liga": m.get("liga", ""), "data": m.get("data", ""), "godzina": m.get("godzina", ""),
            "prob_home": ph, "prob_draw": pr, "prob_away": pp,
            "prob_over": po, "prob_btts": pbt,
            "tips": tips,
        })
    return results


@app.post("/api/coupon/kelly")
def calculate_kelly(req: KellyRequest):
    """Oblicza stawkę Kelly Criterion dla akumulatora."""
    import footstats.config as cfg
    if not req.selections:
        raise HTTPException(status_code=400, detail="Brak typów")

    conn = _get_conn()
    try:
        row = conn.execute("SELECT balance FROM bankroll_state WHERE id=1").fetchone()
        bankroll = float(row["balance"]) if row else float(cfg.AGENT_BANKROLL)
        frac_row = conn.execute("SELECT value FROM bot_settings WHERE key='kelly_fraction'").fetchone()
        fraction = int(frac_row["value"]) if frac_row else cfg.AGENT_KELLY_FRACTION
    finally:
        conn.close()

    total_odds = 1.0
    win_prob   = 1.0
    for s in req.selections:
        total_odds *= s.odds
        p = s.win_prob / 100.0 if s.win_prob > 1.0 else s.win_prob
        win_prob   *= p

    b = total_odds - 1.0
    f_star = max((b * win_prob - (1.0 - win_prob)) / b, 0.0) if b > 0 else 0.0
    stake  = round(f_star / fraction * bankroll, 2)
    stake  = max(stake, 2.0)
    stake  = min(stake, round(bankroll * 0.20, 2))

    return {
        "total_odds":    round(total_odds, 2),
        "win_prob_pct":  round(win_prob * 100, 1),
        "f_star_pct":    round(f_star * 100, 2),
        "stake_pln":     stake,
        "bankroll":      bankroll,
        "kelly_fraction": fraction,
    }


@app.post("/api/coupon/place")
def place_coupon(req: PlaceCouponRequest):
    """Zapisuje kupon do DB i odejmuje stawkę z bankrolla."""
    if req.stake_pln < 2.0:
        raise HTTPException(status_code=400, detail="Minimalna stawka to 2.00 PLN")

    conn = _get_conn()
    try:
        row = conn.execute("SELECT balance FROM bankroll_state WHERE id=1").fetchone()
        balance = float(row["balance"]) if row else 0.0
        if req.stake_pln > balance:
            raise HTTPException(
                status_code=400,
                detail=f"Niewystarczający bankroll ({balance:.2f} PLN)"
            )
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        legs_json = json.dumps([
            {"home": s.home, "away": s.away, "tip": s.tip,
             "odds": s.odds, "decision_score": int(s.win_prob)}
            for s in req.selections
        ], ensure_ascii=False)

        conn.execute("""
            INSERT INTO coupons
                (created_at, phase, status, kupon_type, legs_json,
                 total_odds, stake_pln, payout_pln, match_date_first)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (now, "final", "ACTIVE", "accumulator", legs_json,
              req.total_odds, req.stake_pln, None,
              req.match_date or datetime.now().strftime("%Y-%m-%d")))

        new_balance = round(balance - req.stake_pln, 2)
        conn.execute(
            "UPDATE bankroll_state SET balance=?, updated_at=? WHERE id=1",
            (new_balance, now)
        )
        conn.execute("""
            INSERT INTO bankroll_history (timestamp, change_pln, new_balance, type, description)
            VALUES (?,?,?,?,?)
        """, (now, -req.stake_pln, new_balance, "BET",
              f"Kupon AI ({', '.join(s.tip for s in req.selections)})"))

        conn.commit()
        coupon_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    finally:
        conn.close()

    return {
        "ok": True, "coupon_id": coupon_id,
        "new_balance": new_balance, "stake_pln": req.stake_pln
    }


@app.post("/api/coupons/settle")
def settle_coupons(req: SettleRequest):
    """
    Rozlicza ACTIVE kupony z fallback na FlashScore.

    Parametry:
        days_back: Ile dni wstecz sprawdzać (domyślnie 3)
        dry_run: Czy to test bez faktycznej zmiany bazy (domyślnie False)

    Zwraca:
        {
            "ok": bool,
            "settled": int,      # liczba rozliczonych kuponów
            "partial": int,      # liczba kuponów czekających na wyniki
            "errors": int,       # liczba błędów
            "message": str
        }
    """
    try:
        from footstats.core.coupon_settlement import settle_active_coupons

        stats = settle_active_coupons(
            days_back=req.days_back or 3,
            dry_run=req.dry_run or False,
            verbose=True,
        )

        return {
            "ok": True,
            "settled": stats.get("settled", 0),
            "partial": stats.get("partial", 0),
            "errors": stats.get("errors", 0),
            "message": f"Rozliczono {stats.get('settled', 0)}, "
                      f"częściowych {stats.get('partial', 0)}, "
                      f"błędów {stats.get('errors', 0)}",
        }
    except Exception as e:
        import logging
        logging.error("Błąd POST /api/coupons/settle: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
