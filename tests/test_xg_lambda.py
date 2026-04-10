import pandas as pd
import pytest
from footstats.core.xg_lambda import xg_lambda, xg_lambda_pair


def _df(rows):
    return pd.DataFrame(rows)


def test_xg_lambda_uses_xg_home_when_available():
    df = _df([
        {"home": "PSG", "away": "Lyon", "hg": 1, "ag": 0, "xg_home": 2.5, "xg_away": 0.8, "date": "2025-01-01"},
        {"home": "PSG", "away": "Monaco", "hg": 3, "ag": 1, "xg_home": 3.0, "xg_away": 1.0, "date": "2025-01-08"},
    ])
    df["date"] = pd.to_datetime(df["date"])
    result = xg_lambda("PSG", df, ostatnie_n=10, strona="home")
    assert abs(result - 2.75) < 0.5


def test_xg_lambda_fallback_to_goals_when_no_xg():
    df = _df([
        {"home": "PSG", "away": "Lyon", "hg": 2, "ag": 1, "date": "2025-01-01"},
        {"home": "PSG", "away": "Monaco", "hg": 4, "ag": 0, "date": "2025-01-08"},
    ])
    df["date"] = pd.to_datetime(df["date"])
    result = xg_lambda("PSG", df, ostatnie_n=10, strona="home")
    assert result > 0


def test_xg_lambda_returns_minimum_when_no_matches():
    df = _df([])
    result = xg_lambda("Nieznana", df, ostatnie_n=10, strona="home")
    assert result >= 0.1


def test_xg_lambda_pair_returns_tuple():
    df = _df([
        {"home": "PSG", "away": "Lyon", "hg": 2, "ag": 1, "xg_home": 2.0, "xg_away": 0.9, "date": "2025-01-01"},
    ])
    df["date"] = pd.to_datetime(df["date"])
    lh, la = xg_lambda_pair("PSG", "Lyon", df, ostatnie_n=10)
    assert lh >= 0.1
    assert la >= 0.1


def test_xg_lambda_away_uses_ag_column():
    df = _df([
        {"home": "Lyon", "away": "PSG", "hg": 0, "ag": 3, "xg_home": 0.5, "xg_away": 2.8, "date": "2025-01-01"},
    ])
    df["date"] = pd.to_datetime(df["date"])
    result = xg_lambda("PSG", df, ostatnie_n=10, strona="away")
    assert result > 1.0


def test_xg_lambda_recent_matches_weighted_more():
    from datetime import datetime, timedelta
    today = datetime.now()
    df = _df([
        {"home": "PSG", "away": "A", "hg": 5, "ag": 0, "xg_home": 5.0, "xg_away": 0.5,
         "date": (today - timedelta(days=3)).strftime("%Y-%m-%d")},
        {"home": "PSG", "away": "B", "hg": 1, "ag": 0, "xg_home": 0.5, "xg_away": 1.0,
         "date": "2024-01-01"},
    ])
    df["date"] = pd.to_datetime(df["date"])
    result = xg_lambda("PSG", df, ostatnie_n=10, strona="home")
    assert result > 2.75
