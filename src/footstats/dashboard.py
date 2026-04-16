"""
dashboard.py – FootStats Streamlit Dashboard MVP

Uruchomienie:
    streamlit run src/footstats/dashboard.py

Wyświetla:
  - KPI kafelki: Bankroll / Hit Rate / Zysk-Strata
  - Tabela 10 ostatnich kuponów (WIN/LOSE z kolorowaniem)
  - Tabela 5 najnowszych wniosków z ai_feedback ("Mózg Bota")
"""

import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

# ── Konfiguracja ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="FootStats Dashboard",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="collapsed",
)

DB_PATH = Path(__file__).parents[2] / "data" / "footstats_backtest.db"

# ── Helpers ────────────────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


@st.cache_data(ttl=60)
def load_bankroll() -> float:
    """Aktualny stan bankrolla z bankroll_state."""
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT balance FROM bankroll_state WHERE id = 1"
            ).fetchone()
        return float(row["balance"]) if row else 0.0
    except Exception:
        return 0.0


@st.cache_data(ttl=60)
def load_coupon_stats() -> dict:
    """Hit rate i zysk/strata z ostatnich 30 dni."""
    try:
        with _connect() as conn:
            rows = conn.execute(
                """
                SELECT status, stake_pln, payout_pln
                FROM coupons
                WHERE status IN ('WON', 'LOST')
                  AND created_at >= datetime('now', '-30 days')
                ORDER BY created_at DESC
                """
            ).fetchall()
    except Exception:
        return {"hit_rate": None, "profit": 0.0, "n": 0, "won": 0}

    if not rows:
        return {"hit_rate": None, "profit": 0.0, "n": 0, "won": 0}

    won    = sum(1 for r in rows if r["status"] == "WON")
    n      = len(rows)
    profit = sum(
        (r["payout_pln"] or 0) - (r["stake_pln"] or 0)
        for r in rows
    )
    return {
        "hit_rate": round(won / n * 100, 1),
        "profit":   round(profit, 2),
        "n":        n,
        "won":      won,
    }


@st.cache_data(ttl=60)
def load_last_coupons(n: int = 10) -> pd.DataFrame:
    """Ostatnie n kuponów z DB."""
    try:
        with _connect() as conn:
            rows = conn.execute(
                """
                SELECT id, created_at, status, stake_pln, payout_pln,
                       roi_pct, legs_count, description
                FROM coupons
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (n,),
            ).fetchall()
    except Exception:
        return pd.DataFrame()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame([dict(r) for r in rows])
    df["created_at"] = pd.to_datetime(df["created_at"]).dt.strftime("%d.%m %H:%M")
    df["roi_pct"] = df["roi_pct"].map(
        lambda x: f"{x:+.1f}%" if x is not None else "—"
    )
    df["stake_pln"] = df["stake_pln"].map(
        lambda x: f"{x:.0f} PLN" if x is not None else "—"
    )
    df["payout_pln"] = df["payout_pln"].map(
        lambda x: f"{x:.0f} PLN" if x is not None else "—"
    )
    df = df.rename(columns={
        "id":          "ID",
        "created_at":  "Data",
        "status":      "Status",
        "stake_pln":   "Stawka",
        "payout_pln":  "Wypłata",
        "roi_pct":     "ROI",
        "legs_count":  "Nogi",
        "description": "Opis",
    })
    return df


@st.cache_data(ttl=60)
def load_ai_feedback(n: int = 5) -> pd.DataFrame:
    """Ostatnie n wpisów z tabeli ai_feedback."""
    try:
        with _connect() as conn:
            rows = conn.execute(
                """
                SELECT f.id, f.created_at, f.match_id,
                       p.team_home || ' vs ' || p.team_away AS mecz,
                       p.ai_tip AS typ_ai,
                       p.actual_result AS wynik,
                       f.reason_for_failure AS powod
                FROM ai_feedback f
                JOIN predictions p ON p.id = f.match_id
                ORDER BY f.created_at DESC
                LIMIT ?
                """,
                (n,),
            ).fetchall()
    except Exception:
        return pd.DataFrame()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame([dict(r) for r in rows])
    df["created_at"] = pd.to_datetime(df["created_at"]).dt.strftime("%d.%m %H:%M")
    return df.rename(columns={
        "id":         "ID",
        "created_at": "Data",
        "match_id":   "ID meczu",
        "mecz":       "Mecz",
        "typ_ai":     "Typ AI",
        "wynik":      "Wynik",
        "powod":      "Powód porażki",
    })


# ── Kolorowanie statusów ───────────────────────────────────────────────────────

def _koloruj_status(val: str) -> str:
    if val == "WON":
        return "background-color: #d4edda; color: #155724; font-weight: bold"
    if val == "LOST":
        return "background-color: #f8d7da; color: #721c24; font-weight: bold"
    if val == "ACTIVE":
        return "background-color: #fff3cd; color: #856404; font-weight: bold"
    return ""


# ── Layout ─────────────────────────────────────────────────────────────────────

st.title("⚽ FootStats — Dashboard")
st.caption("Dane odświeżają się co 60 sekund. Kliknij [Rerun] aby zaktualizować.")

# ── KPI kafelki ────────────────────────────────────────────────────────────────

bankroll = load_bankroll()
stats    = load_coupon_stats()

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(
        label="💰 Bankroll",
        value=f"{bankroll:.2f} PLN",
    )

with col2:
    hr = stats["hit_rate"]
    st.metric(
        label="🎯 Hit Rate (30 dni)",
        value=f"{hr:.1f}%" if hr is not None else "Brak danych",
        help=f"Trafione: {stats['won']} / {stats['n']} kuponów",
    )

with col3:
    profit = stats["profit"]
    delta_color = "normal" if profit >= 0 else "inverse"
    st.metric(
        label="📈 Zysk/Strata (30 dni)",
        value=f"{profit:+.2f} PLN",
        delta=f"{profit:+.2f} PLN",
        delta_color=delta_color,
    )

with col4:
    n = stats["n"]
    st.metric(
        label="📊 Rozliczone kupony (30 dni)",
        value=str(n),
    )

st.divider()

# ── Tabela ostatnich kuponów ───────────────────────────────────────────────────

st.subheader("📋 Ostatnie 10 kuponów")

df_kupony = load_last_coupons(10)
if df_kupony.empty:
    st.info("Brak kuponów w bazie. Bot nie rozliczył jeszcze żadnego kuponu.")
else:
    styled = df_kupony.style.map(_koloruj_status, subset=["Status"])
    st.dataframe(styled, use_container_width=True, hide_index=True)

st.divider()

# ── Mózg Bota — ai_feedback ───────────────────────────────────────────────────

st.subheader("🧠 Mózg Bota — ostatnie wnioski z porażek (ai_feedback)")
st.caption(
    "Bot analizuje swoje błędy przez Groq i zapamiętuje powody. "
    "Te wnioski trafiają do kontekstu każdego nowego typowania."
)

df_feedback = load_ai_feedback(5)
if df_feedback.empty:
    st.info(
        "Brak wniosków w tabeli ai_feedback. "
        "Wnioski pojawią się po rozliczeniu pierwszych kuponów "
        "i uruchomieniu `post_match_analyzer`."
    )
else:
    st.dataframe(
        df_feedback[["Data", "Mecz", "Typ AI", "Wynik", "Powód porażki"]],
        use_container_width=True,
        hide_index=True,
    )

st.divider()

# ── Footer ─────────────────────────────────────────────────────────────────────

st.caption(
    f"FootStats v3.0 · DB: `{DB_PATH}` · "
    "Uruchom agenta: `python -m footstats.daily_agent`"
)
