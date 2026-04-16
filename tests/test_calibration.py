"""Testy jednostkowe modułu calibration (Etap 6)."""
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from footstats.core.calibration import (
    HIGH_THRESHOLD, LOW_THRESHOLD,
    MULTIPLIER_HIGH, MULTIPLIER_LOW, MULTIPLIER_NEUTRAL,
    FORMA_WIN_MULTIPLIER, FORMA_LOSE_MULTIPLIER,
    calibration_summary, get_stake_multiplier, get_forma_multiplier,
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

# Dane zaprojektowane tak, żeby ostatnie 3 (wg id DESC) były MIESZANE
# → Forma Bota = neutral, testujemy tylko hit-rate long-term

def test_multiplier_high_form():
    """9 wygranych z 10 → multiplier 1.2 (last-3 = W,L,W → Forma neutral)."""
    # id: 1-7=WON, 8=WON, 9=LOST, 10=WON → last-3 by id DESC: WON,LOST,WON → mix
    rows = [("WON", 10, 80)] * 8 + [("LOST", 10, -100)] + [("WON", 10, 80)]
    db = _make_db(rows)
    import footstats.core.calibration as cal_mod
    with patch.object(cal_mod, "DB_PATH", db):
        assert get_stake_multiplier() == MULTIPLIER_HIGH
    db.unlink(missing_ok=True)


def test_multiplier_low_form():
    """4 wygrane z 10 → multiplier 0.5 (last-3 mieszane → Forma neutral)."""
    # id: 1-3=WON, 4-8=LOST, 9=WON, 10=LOST → last-3: LOST,WON,LOST → mix
    rows = [("WON", 10, 80)] * 3 + [("LOST", 10, -100)] * 5 + [("WON", 10, 80), ("LOST", 10, -100)]
    db = _make_db(rows)
    import footstats.core.calibration as cal_mod
    with patch.object(cal_mod, "DB_PATH", db):
        assert get_stake_multiplier() == MULTIPLIER_LOW
    db.unlink(missing_ok=True)


def test_multiplier_neutral_form():
    """6 wygranych z 10 → multiplier 1.0 (last-3 mieszane → Forma neutral)."""
    # id: 1-3=LOST, 4-9=WON, 10=LOST → last-3: LOST,WON,WON → mix
    rows = [("LOST", 10, -100)] * 3 + [("WON", 10, 80)] * 6 + [("LOST", 10, -100)]
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
    """Dokładnie 80% → jeszcze neutral (próg > 0.80, nie >=), last-3 mieszane."""
    # id: 1-8=WON, 9=LOST, 10=LOST → last-3: LOST,LOST,WON → mix
    rows = [("WON", 10, 80)] * 8 + [("LOST", 10, -100)] * 2
    db = _make_db(rows)
    import footstats.core.calibration as cal_mod
    with patch.object(cal_mod, "DB_PATH", db):
        assert get_stake_multiplier() == MULTIPLIER_NEUTRAL
    db.unlink(missing_ok=True)


# ── get_forma_multiplier ───────────────────────────────────────────────────────

def test_forma_3x_win():
    """Ostatnie 3 = WON,WON,WON → Forma multiplier 1.1."""
    rows = [("LOST", 10, -100)] * 5 + [("WON", 10, 80)] * 3
    db = _make_db(rows)
    import footstats.core.calibration as cal_mod
    with patch.object(cal_mod, "DB_PATH", db):
        assert get_forma_multiplier() == FORMA_WIN_MULTIPLIER
    db.unlink(missing_ok=True)


def test_forma_3x_lose():
    """Ostatnie 3 = LOST,LOST,LOST → Forma multiplier 0.7."""
    rows = [("WON", 10, 80)] * 5 + [("LOST", 10, -100)] * 3
    db = _make_db(rows)
    import footstats.core.calibration as cal_mod
    with patch.object(cal_mod, "DB_PATH", db):
        assert get_forma_multiplier() == FORMA_LOSE_MULTIPLIER
    db.unlink(missing_ok=True)


def test_forma_mixed():
    """Mieszane ostatnie 3 → neutral 1.0."""
    rows = [("WON", 10, 80), ("LOST", 10, -100), ("WON", 10, 80)]
    db = _make_db(rows)
    import footstats.core.calibration as cal_mod
    with patch.object(cal_mod, "DB_PATH", db):
        assert get_forma_multiplier() == MULTIPLIER_NEUTRAL
    db.unlink(missing_ok=True)


def test_forma_takes_priority_over_hitrate():
    """Forma Bota (3xWIN) → 1.1, mimo że hit-rate dałby 1.2."""
    rows = [("WON", 10, 80)] * 10
    db = _make_db(rows)
    import footstats.core.calibration as cal_mod
    with patch.object(cal_mod, "DB_PATH", db):
        # Forma Bota = 1.1 (bierze priorytet nad hit-rate 1.2)
        assert get_stake_multiplier() == FORMA_WIN_MULTIPLIER
    db.unlink(missing_ok=True)


def test_forma_lose_takes_priority_over_hitrate():
    """Forma Bota (3xLOSE) → 0.7, mimo że hit-rate dałby 0.5."""
    rows = [("LOST", 10, -100)] * 10
    db = _make_db(rows)
    import footstats.core.calibration as cal_mod
    with patch.object(cal_mod, "DB_PATH", db):
        # Forma Bota = 0.7 (bierze priorytet nad hit-rate 0.5)
        assert get_stake_multiplier() == FORMA_LOSE_MULTIPLIER
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
