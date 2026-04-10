from __future__ import annotations

import pandas as pd

_MIN_LAMBDA = 0.1
_RECENT_DAYS = 14
_RECENT_WEIGHT = 2.0


def _weights(df: pd.DataFrame) -> pd.Series:
    if "date" not in df.columns:
        return pd.Series(1.0, index=df.index)
    cutoff = pd.Timestamp.now() - pd.Timedelta(days=_RECENT_DAYS)
    dates = pd.to_datetime(df["date"], errors="coerce")
    return dates.apply(lambda d: _RECENT_WEIGHT if pd.notna(d) and d >= cutoff else 1.0)


def xg_lambda(
    team: str,
    df_hist: pd.DataFrame,
    ostatnie_n: int = 10,
    strona: str = "home",
) -> float:
    """Lambda Poissona z xG (fallback: bramki). strona: home|away|both"""
    if df_hist is None or df_hist.empty:
        return _MIN_LAMBDA

    df = df_hist.copy()

    if strona == "home":
        mask = df.get("home", pd.Series(dtype=str)) == team
        xg_col, g_col = "xg_home", "hg"
    elif strona == "away":
        mask = df.get("away", pd.Series(dtype=str)) == team
        xg_col, g_col = "xg_away", "ag"
    else:
        mask = (df.get("home", pd.Series(dtype=str)) == team) | \
               (df.get("away", pd.Series(dtype=str)) == team)
        xg_col, g_col = None, None

    sub = df[mask].tail(ostatnie_n)
    if sub.empty:
        return _MIN_LAMBDA

    w = _weights(sub)

    if xg_col and xg_col in sub.columns and sub[xg_col].notna().any():
        vals = pd.to_numeric(sub[xg_col], errors="coerce")
    elif g_col and g_col in sub.columns:
        vals = pd.to_numeric(sub[g_col], errors="coerce")
    elif strona == "both":
        home_mask = sub.get("home", pd.Series(dtype=str)) == team
        vals = pd.Series(index=sub.index, dtype=float)
        if "xg_home" in sub.columns:
            vals[home_mask] = pd.to_numeric(sub.loc[home_mask, "xg_home"], errors="coerce")
            vals[~home_mask] = pd.to_numeric(sub.loc[~home_mask, "xg_away"], errors="coerce")
        else:
            vals[home_mask] = pd.to_numeric(sub.loc[home_mask, "hg"], errors="coerce") if "hg" in sub.columns else 1.0
            vals[~home_mask] = pd.to_numeric(sub.loc[~home_mask, "ag"], errors="coerce") if "ag" in sub.columns else 1.0
    else:
        return _MIN_LAMBDA

    vals = vals.fillna(0.0)
    if w.sum() == 0:
        return _MIN_LAMBDA

    result = (vals * w).sum() / w.sum()
    return max(result, _MIN_LAMBDA)


def xg_lambda_pair(
    home: str,
    away: str,
    df_hist: pd.DataFrame,
    ostatnie_n: int = 10,
) -> tuple[float, float]:
    lh = xg_lambda(home, df_hist, ostatnie_n, strona="home")
    la = xg_lambda(away, df_hist, ostatnie_n, strona="away")
    return lh, la
