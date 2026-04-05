"""Testy core/backtest.py — SQLite backtest tracking."""
import pytest
import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from footstats.core.backtest import (
    _oblicz_tip_correct,
    save_prediction,
    update_result,
    get_stats,
    init_db,
    _connect,
)


# ── Fixture: izolowana baza w pamięci ─────────────────────────────────────

@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    """Każdy test dostaje własną, pustą bazę SQLite w tmp_path."""
    db = tmp_path / "test_backtest.db"
    monkeypatch.setattr("footstats.core.backtest.DB_PATH", db)
    init_db()
    yield db


# ── _oblicz_tip_correct ───────────────────────────────────────────────────

class TestObliczTipCorrect:
    @pytest.mark.parametrize("tip,result,expected", [
        ("1",       "2-1",  1),
        ("1",       "1-2",  0),
        ("X",       "1-1",  1),
        ("X",       "2-0",  0),
        ("2",       "0-1",  1),
        ("2",       "0-0",  0),
        ("1X",      "2-1",  1),
        ("1X",      "1-1",  1),
        ("1X",      "0-2",  0),
        ("X2",      "1-1",  1),
        ("X2",      "0-1",  1),
        ("X2",      "2-0",  0),
        ("12",      "3-1",  1),
        ("12",      "1-3",  1),
        ("12",      "0-0",  0),
        ("BTTS",    "1-1",  1),
        ("BTTS",    "1-0",  0),
        ("BTTS NO", "1-0",  1),
        ("BTTS NO", "2-1",  0),
        ("OVER 2.5","2-1",  1),
        ("OVER 2.5","1-1",  0),
        ("UNDER 2.5","1-0", 1),
        ("UNDER 2.5","2-1", 0),
        ("OVER 1.5","1-1",  1),
        ("OVER 1.5","1-0",  0),
    ])
    def test_oblicz(self, tip, result, expected):
        assert _oblicz_tip_correct(tip, result) == expected

    def test_pusty_wynik_zwraca_none(self):
        assert _oblicz_tip_correct("1", "") is None

    def test_nieznany_typ_zwraca_none(self):
        assert _oblicz_tip_correct("CORNER 5+", "2-1") is None

    def test_bezposredni_1x2(self):
        assert _oblicz_tip_correct("1", "1") == 1
        assert _oblicz_tip_correct("2", "1") == 0

    def test_wynik_z_dogrywka(self):
        # "2-1 (AET)" powinien parsować się do 2-1
        assert _oblicz_tip_correct("1", "2-1 (AET)") == 1


# ── save_prediction ───────────────────────────────────────────────────────

class TestSavePrediction:
    def test_zwraca_int_id(self):
        pid = save_prediction(
            match_date="2026-04-10",
            team_home="Bayern",
            team_away="Dortmund",
            ai_tip="1",
            ai_confidence=78,
        )
        assert isinstance(pid, int)
        assert pid > 0

    def test_zapis_do_db(self):
        save_prediction(
            match_date="2026-04-10",
            team_home="Bayern",
            team_away="Dortmund",
            ai_tip="1",
            ai_confidence=78,
            league="GER-Bundesliga",
            odds=1.55,
        )
        from footstats.core.backtest import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT * FROM predictions WHERE team_home='Bayern'"
        ).fetchone()
        conn.close()
        assert row is not None

    def test_confidence_boundary_0(self):
        pid = save_prediction("2026-04-10", "A", "B", "1", 0)
        assert pid > 0

    def test_confidence_boundary_100(self):
        pid = save_prediction("2026-04-10", "A", "B", "1", 100)
        assert pid > 0

    def test_confidence_out_of_range_raises(self):
        with pytest.raises(Exception):
            save_prediction("2026-04-10", "A", "B", "1", 101)

    def test_factors_zapisane_jako_json(self):
        save_prediction(
            match_date="2026-04-10",
            team_home="PSG",
            team_away="Lyon",
            ai_tip="1",
            ai_confidence=75,
            factors=["PATENT", "TWIERDZA"],
        )
        from footstats.core.backtest import DB_PATH
        import json
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT factors FROM predictions WHERE team_home='PSG'"
        ).fetchone()
        conn.close()
        faktory = json.loads(row[0])
        assert "PATENT" in faktory


# ── update_result ─────────────────────────────────────────────────────────

class TestUpdateResult:
    def _save(self, tip="1", conf=75) -> int:
        return save_prediction(
            match_date="2026-04-10",
            team_home="Ajax",
            team_away="Feyenoord",
            ai_tip=tip,
            ai_confidence=conf,
        )

    def test_update_correct_1x2(self):
        pid = self._save(tip="1")
        update_result(pid, "2-1")  # wynik: home win
        from footstats.core.backtest import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT tip_correct FROM predictions WHERE id=?", (pid,)
        ).fetchone()
        conn.close()
        assert row[0] == 1

    def test_update_incorrect(self):
        pid = self._save(tip="2")
        update_result(pid, "2-1")  # wynik: home win, ale typowaliśmy 2
        from footstats.core.backtest import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT tip_correct FROM predictions WHERE id=?", (pid,)
        ).fetchone()
        conn.close()
        assert row[0] == 0

    def test_update_over25(self):
        pid = self._save(tip="Over 2.5")
        update_result(pid, "2-1")  # 3 gole > 2.5
        from footstats.core.backtest import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT tip_correct FROM predictions WHERE id=?", (pid,)
        ).fetchone()
        conn.close()
        assert row[0] == 1


# ── get_stats ─────────────────────────────────────────────────────────────

class TestGetStats:
    def test_pusta_baza_zwraca_none_accuracy(self):
        stats = get_stats(days=30)
        assert stats.get("accuracy_pct") is None
        assert stats.get("total_tips", 0) == 0

    def test_stats_po_wpisaniu_wynikow(self):
        today = datetime.now().strftime("%Y-%m-%d")
        # Wpisz 2 trafione i 1 pudło
        for tip, result in [("1", "2-1"), ("1", "1-0"), ("2", "2-0")]:
            pid = save_prediction(today, "A", "B", tip, 70)
            update_result(pid, result)

        stats = get_stats(days=30)
        assert stats["evaluated"] == 3
        assert abs(stats["accuracy_pct"] - round(2/3*100, 1)) < 0.5
