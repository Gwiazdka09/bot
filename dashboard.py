"""
FootStats Dashboard — Streamlit
Uruchom: streamlit run dashboard.py
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

# ── Ścieżki do baz ────────────────────────────────────────────────────────
BACKTEST_DB   = Path(__file__).parent / "data" / "footstats_backtest.db"
WALKFORWARD_DB = Path(__file__).parent / "data" / "footstats_backtest.db"  # ta sama baza

st.set_page_config(
    page_title="FootStats Dashboard",
    page_icon="⚽",
    layout="wide",
)

# ── Pomocnicze ────────────────────────────────────────────────────────────

def _conn(db: Path) -> sqlite3.Connection:
    if not db.exists():
        return None
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    return conn


def _load_predictions(days: int = 90) -> pd.DataFrame:
    conn = _conn(BACKTEST_DB)
    if conn is None:
        return pd.DataFrame()
    date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        df = pd.read_sql_query(
            "SELECT * FROM predictions WHERE match_date >= ? ORDER BY match_date ASC",
            conn, params=(date_from,),
        )
    except Exception:
        df = pd.DataFrame()
    finally:
        conn.close()
    return df


def _load_wf_results(league_filter: str | None = None) -> pd.DataFrame:
    conn = _conn(WALKFORWARD_DB)
    if conn is None:
        return pd.DataFrame()
    try:
        sql = "SELECT * FROM wf_results ORDER BY match_date ASC"
        df = pd.read_sql_query(sql, conn)
        if league_filter:
            df = df[df["league"] == league_filter]
    except Exception:
        df = pd.DataFrame()
    finally:
        conn.close()
    return df


def _load_pending() -> pd.DataFrame:
    conn = _conn(BACKTEST_DB)
    if conn is None:
        return pd.DataFrame()
    try:
        df = pd.read_sql_query(
            "SELECT id, match_date, team_home, team_away, league, ai_tip, ai_confidence, odds, kupon_type "
            "FROM predictions WHERE actual_result IS NULL ORDER BY match_date DESC",
            conn,
        )
    except Exception:
        df = pd.DataFrame()
    finally:
        conn.close()
    return df


def _color_accuracy(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    if val >= 60:
        return "color: green; font-weight: bold"
    if val >= 45:
        return "color: orange"
    return "color: red"


# ── Sidebar ───────────────────────────────────────────────────────────────

st.sidebar.title("⚽ FootStats")
st.sidebar.markdown("---")
zakres = st.sidebar.selectbox("Zakres danych", [30, 60, 90, 180, 365], index=2)
st.sidebar.markdown("---")
sekcja = st.sidebar.radio("Sekcja", [
    "Przegląd",
    "Bankroll & ROI",
    "Accuracy per rynek",
    "Accuracy per liga",
    "Pasma pewności",
    "Oczekujące mecze",
    "Walk-Forward Backtest",
])


# ── Dane ──────────────────────────────────────────────────────────────────

df_all = _load_predictions(days=zakres)
df_eval = df_all[df_all["tip_correct"].notna()].copy() if not df_all.empty else pd.DataFrame()
df_pending = _load_pending()

n_total   = len(df_all)
n_eval    = len(df_eval)
n_correct = int(df_eval["tip_correct"].sum()) if n_eval else 0
acc       = round(n_correct / n_eval * 100, 1) if n_eval else None

if not df_eval.empty and "odds" in df_eval.columns:
    df_ev = df_eval.dropna(subset=["odds"])
    roi_num = sum(
        (r["odds"] - 1) if r["tip_correct"] == 1 else -1
        for _, r in df_ev.iterrows()
    )
    roi = round(roi_num / len(df_ev) * 100, 1) if len(df_ev) else None
else:
    roi = None


# ════════════════════════════════════════════════════════════════════════════
#  SEKCJA 1: PRZEGLĄD
# ════════════════════════════════════════════════════════════════════════════

if sekcja == "Przegląd":
    st.title("Przegląd — FootStats")
    st.caption(f"Dane z ostatnich {zakres} dni | Dzisiaj: {datetime.now().strftime('%Y-%m-%d')}")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Wszystkich typów", n_total)
    c2.metric("Ocenionych", n_eval)
    c3.metric("Trafionych", n_correct)
    c4.metric("Accuracy", f"{acc}%" if acc is not None else "—")
    c5.metric("ROI (brutto)", f"{roi}%" if roi is not None else "—",
              delta_color="normal" if roi and roi >= 0 else "inverse")

    if df_eval.empty:
        st.info("Brak ocenionych typów w wybranym zakresie. Wpisz wyniki przez:\n"
                "`python -m footstats.core.backtest update <id> \"2-1\"`")
    else:
        st.markdown("### Ostatnie ocenione typy")
        cols_show = [c for c in ["match_date","team_home","team_away","league",
                                  "ai_tip","ai_confidence","odds","actual_result","tip_correct"]
                     if c in df_eval.columns]
        df_show = df_eval[cols_show].tail(15).iloc[::-1].copy()
        if "tip_correct" in df_show.columns:
            df_show["tip_correct"] = df_show["tip_correct"].map({1: "✓", 0: "✗"})
        st.dataframe(df_show, use_container_width=True)

    if not df_pending.empty:
        st.markdown(f"### Oczekuje na wyniki: {len(df_pending)} mecz(ów)")
        st.dataframe(df_pending.head(5), use_container_width=True)


# ════════════════════════════════════════════════════════════════════════════
#  SEKCJA 2: BANKROLL & ROI
# ════════════════════════════════════════════════════════════════════════════

elif sekcja == "Bankroll & ROI":
    st.title("Bankroll & ROI w czasie")

    if df_eval.empty:
        st.info("Brak danych.")
    else:
        df_curve = df_eval.sort_values("match_date").copy()

        # Stawka 10 PLN flat betting lub z odds
        STAWKA = 10.0
        if "odds" in df_curve.columns:
            df_curve["pnl"] = df_curve.apply(
                lambda r: (r["odds"] - 1) * STAWKA if r["tip_correct"] == 1 else -STAWKA,
                axis=1,
            )
        else:
            df_curve["pnl"] = df_curve["tip_correct"].map({1: STAWKA, 0: -STAWKA})

        df_curve["bankroll"] = 200 + df_curve["pnl"].cumsum()
        df_curve["roi_cum"]  = df_curve["pnl"].cumsum() / (df_curve.index + 1) / STAWKA * 100

        st.markdown(f"#### Bankroll (start 200 PLN, stawka {STAWKA} PLN flat)")
        st.line_chart(df_curve.set_index("match_date")["bankroll"])

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### ROI kumulatywny (%)")
            st.line_chart(df_curve.set_index("match_date")["roi_cum"])
        with col2:
            st.markdown("#### P&L na zakład (PLN)")
            st.bar_chart(df_curve.set_index("match_date")["pnl"])

        net_pnl = df_curve["pnl"].sum()
        st.metric("Łączny P&L (brutto)", f"{net_pnl:+.1f} PLN",
                  delta=f"{net_pnl * 0.88:+.1f} PLN po podatku 12%")


# ════════════════════════════════════════════════════════════════════════════
#  SEKCJA 3: ACCURACY PER RYNEK
# ════════════════════════════════════════════════════════════════════════════

elif sekcja == "Accuracy per rynek":
    st.title("Accuracy per rynek")

    if df_eval.empty:
        st.info("Brak danych.")
    else:
        grp = (
            df_eval.groupby("ai_tip")["tip_correct"]
            .agg(total="count", correct="sum")
            .reset_index()
        )
        grp["accuracy_pct"] = (grp["correct"] / grp["total"] * 100).round(1)
        grp = grp[grp["total"] >= 2].sort_values("accuracy_pct", ascending=False)

        st.dataframe(
            grp.rename(columns={
                "ai_tip": "Rynek", "total": "Łącznie", "correct": "Trafionych",
                "accuracy_pct": "Accuracy %"
            }).style.applymap(_color_accuracy, subset=["Accuracy %"]),
            use_container_width=True,
        )
        st.bar_chart(grp.set_index("ai_tip")["accuracy_pct"])


# ════════════════════════════════════════════════════════════════════════════
#  SEKCJA 4: ACCURACY PER LIGA
# ════════════════════════════════════════════════════════════════════════════

elif sekcja == "Accuracy per liga":
    st.title("Accuracy per liga")

    if df_eval.empty:
        st.info("Brak danych.")
    else:
        df_lval = df_eval.copy()
        df_lval["league"] = df_lval["league"].fillna("Nieznana").replace("", "Nieznana")
        grp = (
            df_lval.groupby("league")["tip_correct"]
            .agg(total="count", correct="sum")
            .reset_index()
        )
        grp["accuracy_pct"] = (grp["correct"] / grp["total"] * 100).round(1)
        grp = grp[grp["total"] >= 2].sort_values("accuracy_pct", ascending=False)

        st.dataframe(
            grp.rename(columns={
                "league": "Liga", "total": "Łącznie", "correct": "Trafionych",
                "accuracy_pct": "Accuracy %"
            }).style.applymap(_color_accuracy, subset=["Accuracy %"]),
            use_container_width=True,
        )

        col1, col2 = st.columns(2)
        with col1:
            if not grp.empty:
                st.markdown("**Najlepsza liga**")
                best = grp.iloc[0]
                st.success(f"{best['league']}: {best['accuracy_pct']}% (n={best['total']})")
        with col2:
            if len(grp) >= 2:
                st.markdown("**Najsłabsza liga**")
                worst = grp.iloc[-1]
                st.error(f"{worst['league']}: {worst['accuracy_pct']}% (n={worst['total']})")


# ════════════════════════════════════════════════════════════════════════════
#  SEKCJA 5: PASMA PEWNOŚCI
# ════════════════════════════════════════════════════════════════════════════

elif sekcja == "Pasma pewności":
    st.title("Accuracy vs pewność modelu (1X2)")

    if df_eval.empty:
        st.info("Brak danych.")
    else:
        bins   = [0, 50, 65, 80, 101]
        labels = ["0–49%", "50–64%", "65–79%", "80–100%"]
        df_c = df_eval.copy()
        df_c["pasmo"] = pd.cut(df_c["ai_confidence"], bins=bins, labels=labels, right=False)

        grp = (
            df_c.groupby("pasmo", observed=True)["tip_correct"]
            .agg(total="count", correct="sum")
            .reset_index()
        )
        grp["accuracy_pct"] = (grp["correct"] / grp["total"] * 100).round(1)

        st.dataframe(
            grp.rename(columns={
                "pasmo": "Pasmo pewności", "total": "Łącznie",
                "correct": "Trafionych", "accuracy_pct": "Accuracy %"
            }).style.applymap(_color_accuracy, subset=["Accuracy %"]),
            use_container_width=True,
        )

        st.markdown("**Im wyższe pasmo pewności, tym accuracy powinno rosnąć (kalibracja modelu)**")
        chart_data = grp.set_index("pasmo")[["accuracy_pct"]].dropna()
        if not chart_data.empty:
            st.bar_chart(chart_data)

        # Accuracy per kurs
        if "odds" in df_eval.columns:
            st.markdown("---")
            st.markdown("### Accuracy per pasmo kursów")
            df_o = df_eval.dropna(subset=["odds"]).copy()
            odds_bins   = [1.0, 1.5, 2.0, 2.5, 3.5, 100]
            odds_labels = ["1.01–1.49", "1.50–1.99", "2.00–2.49", "2.50–3.49", "3.50+"]
            df_o["pasmo_kurs"] = pd.cut(df_o["odds"], bins=odds_bins, labels=odds_labels, right=False)
            grp_o = (
                df_o.groupby("pasmo_kurs", observed=True)["tip_correct"]
                .agg(total="count", correct="sum")
                .reset_index()
            )
            grp_o["accuracy_pct"] = (grp_o["correct"] / grp_o["total"] * 100).round(1)
            grp_o = grp_o[grp_o["total"] >= 2]
            st.dataframe(
                grp_o.rename(columns={
                    "pasmo_kurs": "Pasmo kursów", "total": "Łącznie",
                    "correct": "Trafionych", "accuracy_pct": "Accuracy %"
                }),
                use_container_width=True,
            )


# ════════════════════════════════════════════════════════════════════════════
#  SEKCJA 6: OCZEKUJĄCE MECZE
# ════════════════════════════════════════════════════════════════════════════

elif sekcja == "Oczekujące mecze":
    st.title("Oczekujące mecze (bez wyniku)")

    if df_pending.empty:
        st.success("Brak oczekujących meczów — wszystkie wyniki wpisane!")
    else:
        st.info(f"**{len(df_pending)}** mecz(ów) czeka na wynik.\n\n"
                "Wpisz wynik: `python -m footstats.core.backtest update <id> \"2-1\"`")

        cols_show = [c for c in ["id", "match_date", "team_home", "team_away",
                                  "league", "ai_tip", "ai_confidence", "odds", "kupon_type"]
                     if c in df_pending.columns]
        st.dataframe(df_pending[cols_show], use_container_width=True)

        # Najstarsze oczekujące
        if "match_date" in df_pending.columns:
            najstarsze = df_pending.sort_values("match_date").head(5)
            st.markdown("### Najstarsze (wpisz wyniki!)")
            st.dataframe(najstarsze[cols_show], use_container_width=True)


# ════════════════════════════════════════════════════════════════════════════
#  SEKCJA 7: WALK-FORWARD BACKTEST
# ════════════════════════════════════════════════════════════════════════════

elif sekcja == "Walk-Forward Backtest":
    st.title("Walk-Forward Backtest — model Poisson")
    st.caption("Walidacja modelu bez lookahead na danych historycznych (xgabora/football-data.co.uk)")

    df_wf = _load_wf_results()

    if df_wf.empty:
        st.warning(
            "Brak danych walk-forward.\n\n"
            "Uruchom najpierw:\n"
            "```\npython -m footstats.core.walkforward --all\n```"
        )
    else:
        ligi = sorted(df_wf["league"].dropna().unique().tolist())
        liga_filter = st.selectbox("Liga", ["— wszystkie —"] + ligi)
        if liga_filter != "— wszystkie —":
            df_wf = df_wf[df_wf["league"] == liga_filter]

        n_wf = len(df_wf)
        df_wf_eval = df_wf.dropna(subset=["correct"])

        acc_1x2 = (
            round(df_wf_eval["correct"].mean() * 100, 1)
            if not df_wf_eval.empty else None
        )

        c1, c2, c3 = st.columns(3)
        c1.metric("Meczów przeanalizowanych", n_wf)
        c2.metric("Accuracy 1X2", f"{acc_1x2}%" if acc_1x2 else "—")

        if "correct_o25" in df_wf.columns:
            df_o = df_wf.dropna(subset=["correct_o25"])
            acc_o25 = round(df_o["correct_o25"].mean() * 100, 1) if not df_o.empty else None
            c3.metric("Accuracy Over2.5", f"{acc_o25}%" if acc_o25 else "—")

        # Accuracy per liga
        if not df_wf_eval.empty:
            st.markdown("### Accuracy 1X2 per liga")
            grp = (
                df_wf_eval.groupby("league")["correct"]
                .agg(n="count", acc_mean="mean")
                .reset_index()
            )
            grp["acc_pct"] = (grp["acc_mean"] * 100).round(1)
            grp = grp[grp["n"] >= 20].sort_values("acc_pct", ascending=False)
            st.dataframe(
                grp.rename(columns={"league": "Liga", "n": "Meczów", "acc_pct": "Accuracy %"})[
                    ["Liga", "Meczów", "acc_pct"]
                ].style.applymap(_color_accuracy, subset=["acc_pct"]),
                use_container_width=True,
            )

        # Accuracy per pasmo pewności
        if "pred_conf" in df_wf_eval.columns:
            st.markdown("### Accuracy per pasmo pewności (walk-forward)")
            df_conf = df_wf_eval.copy()
            bins   = [0, 0.40, 0.50, 0.60, 0.70, 1.01]
            labels = ["<40%", "40–49%", "50–59%", "60–69%", "70%+"]
            df_conf["pasmo"] = pd.cut(df_conf["pred_conf"], bins=bins, labels=labels)
            grp_c = (
                df_conf.groupby("pasmo", observed=True)["correct"]
                .agg(n="count", acc="mean")
                .reset_index()
            )
            grp_c["acc_pct"] = (grp_c["acc"] * 100).round(1)
            grp_c = grp_c[grp_c["n"] >= 5]
            st.dataframe(
                grp_c[["pasmo", "n", "acc_pct"]].rename(
                    columns={"pasmo": "Pasmo pewności", "n": "Meczów", "acc_pct": "Accuracy %"}
                ),
                use_container_width=True,
            )
            st.bar_chart(grp_c.set_index("pasmo")["acc_pct"])

        # Ostatnie mecze
        st.markdown("### Ostatnie predykcje walk-forward")
        cols_wf = [c for c in ["league", "match_date", "home", "away",
                                "actual_res", "pred_res", "pred_conf", "correct"]
                   if c in df_wf.columns]
        st.dataframe(df_wf[cols_wf].tail(20).iloc[::-1], use_container_width=True)


# ── Stopka ────────────────────────────────────────────────────────────────
st.sidebar.markdown("---")
st.sidebar.caption(f"FootStats v3.0 | {datetime.now().strftime('%H:%M:%S')}")
if st.sidebar.button("Odswierz"):
    st.rerun()
