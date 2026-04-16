"""Testy jednostkowe modułu calibration (Etap 6)."""
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from footstats.core.calibration import (
    HIGH_THRESHOLD, LOW_THRESHOLD,
    MULTIPLIER_HIGH, MULTIPLIER_LOW, MULTIPLIER_NEUTRAL,
    calibration_summary, get_stake_multiplier,
)


def _make_db(rows: list[tuple[str, float, float]]) -> Path:
    """Tworzy tymczasową DB z podanymi kuponami (status, stake_pln, roi_pct)."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.execute("""
        CREATE TABLE coupons (
            id INTEGER PRIMARY KEY,
            created_at TEXT DEFAULT (datetime('now')),
            status TEXT,
            stake_pln REAL,
            payout_pln REAL,
            roi_pct REAL
        )
    """)
    conn.executemany(
        "INSERT INTO coupons (status, stake_pln, roi_pct) VALUES (?, ?, ?)", rows
    )
    conn.commit()
    conn.close()
    return Path(tmp.name)


@pytest.fixture
def patch_db(tmp_path):
    """Patch DB_PATH na tymczasową bazę."""
    import footstats.core.calibration as cal_mod

    def _factory(rows):
        db = _make_db(rows)
        with patch.object(cal_mod, "DB_PATH", db):
            yield
        db.unlink(missing_ok=True)

    return _factory


# ── get_stake_multiplier ───────────────────────────────────────────────────────

def test_multiplier_high_form():
    """9 wygranych z 10 → multiplier 1.2."""
    rows = [("WON", 10, 80)] * 9 + [("LOST", 10, -100)]
    db = _make_db(rows)
    import footstats.core.calibration as cal_mod
    with patch.object(cal_mod, "DB_PATH", db):
        assert get_stake_multiplier() == MULTIPLIER_HIGH
    db.unlink(missing_ok=True)


def test_multiplier_low_form():
    """4 wygrane z 10 → multiplier 0.5."""
    rows = [("WON", 10, 80)] * 4 + [("LOST", 10, -100)] * 6
    db = _make_db(rows)
    import footstats.core.calibration as cal_mod
    with patch.object(cal_mod, "DB_PATH", db):
        assert get_stake_multiplier() == MULTIPLIER_LOW
    db.unlink(missing_ok=True)


def test_multiplier_neutral_form():
    """6 wygranych z 10 → multiplier 1.0."""
    rows = [("WON", 10, 80)] * 6 + [("LOST", 10, -100)] * 4
    db = _make_db(rows)
    import footstats.core.calibration as cal_mod
    with patch.object(cal_mod, "DB_PATH", db):
        assert get_stake_multiplier() == MULTIPLIER_NEUTRAL
    db.unlink(missing_ok=True)


def test_multiplier_no_history():
    """Brak rozliczonych kuponów → neutral 1.0."""
    rows = [("ACTIVE", 10, None), ("DRAFT", 10, None)]
    db = _make_db(rows)
    import footstats.core.calibration as cal_mod
    with patch.object(cal_mod, "DB_PATH", db):
        assert get_stake_multiplier() == MULTIPLIER_NEUTRAL
    db.unlink(missing_ok=True)


def test_multiplier_boundary_high():
    """Dokładnie 80% → jeszcze neutral (próg > 0.80, nie >=)."""
    rows = [("WON", 10, 80)] * 8 + [("LOST", 10, -100)] * 2
    db = _make_db(rows)
    import footstats.core.calibration as cal_mod
    with patch.object(cal_mod, "DB_PATH", db):
        assert get_stake_multiplier() == MULTIPLIER_NEUTRAL
    db.unlink(missing_ok=True)


# ── calibration_summary ────────────────────────────────────────────────────────

def test_summary_fields():
    """Summary zwraca wszystkie wymagane klucze."""
    rows = [("WON", 10, 50)] * 7 + [("LOST", 10, -100)] * 3
    db = _make_db(rows)
    import footstats.core.calibration as cal_mod
    with patch.object(cal_mod, "DB_PATH", db):
        s = calibration_summary()
    db.unlink(missing_ok=True)
    assert {"n", "won", "lost", "hit_rate", "avg_roi_pct", "multiplier", "note"} <= s.keys()
    assert s["n"] == 10
    assert s["won"] == 7
    assert s["hit_rate"] == pytest.approx(0.7, abs=0.01)
