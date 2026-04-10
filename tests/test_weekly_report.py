import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


def _seed_db(db_path: Path):
    """Seed kupony do testowej bazy."""
    import footstats.core.coupon_tracker as ct
    ct.DB_PATH = db_path
    ct.init_coupon_tables()
    cid1 = ct.save_coupon("draft", "A", [{"tip": "Over 2.5"}], 3.20, 10.0, "test", 60, "2026-04-08")
    ct.update_coupon_status(cid1, "WON", payout_pln=28.16)
    cid2 = ct.save_coupon("final", "A", [{"tip": "1X2 Home"}], 2.10, 10.0, "test", 55, "2026-04-09")
    ct.update_coupon_status(cid2, "LOST", payout_pln=None)


def test_get_stats_7_dni_returns_dict(tmp_path):
    db = tmp_path / "test.db"
    _seed_db(db)

    from footstats.weekly_report import get_stats_7_dni
    stats = get_stats_7_dni(db_path=db)
    assert isinstance(stats, dict)
    assert "total" in stats
    assert "won" in stats
    assert "lost" in stats


def test_get_stats_7_dni_counts_correctly(tmp_path):
    db = tmp_path / "test.db"
    _seed_db(db)

    from footstats.weekly_report import get_stats_7_dni
    stats = get_stats_7_dni(db_path=db)
    assert stats["total"] >= 2
    assert stats["won"] >= 1
    assert stats["lost"] >= 1


def test_build_raport_prompt_contains_stats():
    from footstats.weekly_report import build_raport_prompt
    stats = {"total": 5, "won": 3, "lost": 2, "accuracy_pct": 60.0, "roi_pct": 12.5,
             "total_stake": 50.0, "total_payout": 56.25}
    prompt = build_raport_prompt(stats)
    assert "60" in prompt or "accuracy" in prompt.lower()
    assert isinstance(prompt, str)
    assert len(prompt) > 50


def test_run_weekly_report_without_groq(tmp_path):
    db = tmp_path / "test.db"
    _seed_db(db)

    from footstats.weekly_report import run_weekly_report
    result = run_weekly_report(api_key_groq=None, send_telegram=False)
    assert isinstance(result, dict)
    assert "total" in result
