import pytest
from pathlib import Path
from footstats.scrapers.referee_db import init_referee_table, upsert_referee, get_referee, referee_signal


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test_referees.db"
    init_referee_table(db_path)
    return db_path


def test_init_creates_table(db):
    import sqlite3
    conn = sqlite3.connect(db)
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    conn.close()
    assert any("referees" in t[0] for t in tables)


def test_upsert_and_get_referee(db):
    upsert_referee("Szymon Marciniak", {
        "country": "Poland", "avg_yellow": 3.2, "avg_red": 0.1,
        "avg_goals": 2.8, "home_win_pct": 0.45, "n_matches": 120
    }, db_path=db)
    result = get_referee("Szymon Marciniak", db_path=db)
    assert result is not None
    assert abs(result["avg_yellow"] - 3.2) < 0.01
    assert result["country"] == "Poland"


def test_get_referee_returns_none_when_unknown(db):
    result = get_referee("Nieznany Sędzia", db_path=db)
    assert result is None


def test_upsert_updates_existing(db):
    upsert_referee("Test Ref", {"avg_yellow": 2.0, "avg_red": 0.0, "avg_goals": 2.5,
                                 "home_win_pct": 0.40, "n_matches": 10}, db_path=db)
    upsert_referee("Test Ref", {"avg_yellow": 6.0, "avg_red": 0.2, "avg_goals": 2.5,
                                 "home_win_pct": 0.40, "n_matches": 20}, db_path=db)
    result = get_referee("Test Ref", db_path=db)
    assert abs(result["avg_yellow"] - 6.0) < 0.01
    assert result["n_matches"] == 20


def test_referee_signal_kartkowy(db):
    upsert_referee("Kartkowy", {"avg_yellow": 6.0, "avg_red": 0.3, "avg_goals": 2.5,
                                  "home_win_pct": 0.45, "n_matches": 50}, db_path=db)
    assert referee_signal("Kartkowy", db_path=db) == "KARTKOWY"


def test_referee_signal_bramkowy(db):
    upsert_referee("Bramkowy", {"avg_yellow": 2.0, "avg_red": 0.0, "avg_goals": 3.5,
                                  "home_win_pct": 0.48, "n_matches": 30}, db_path=db)
    assert referee_signal("Bramkowy", db_path=db) == "BRAMKOWY"


def test_referee_signal_neutralny(db):
    upsert_referee("Neutralny", {"avg_yellow": 3.0, "avg_red": 0.1, "avg_goals": 2.4,
                                   "home_win_pct": 0.45, "n_matches": 40}, db_path=db)
    assert referee_signal("Neutralny", db_path=db) == "NEUTRALNY"


def test_referee_signal_nieznany(db):
    assert referee_signal("Nieznany XYZ", db_path=db) == "NIEZNANY"
