"""tests/test_coupon_tracker.py"""
import json
import pytest


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    """Każdy test dostaje własną pustą bazę."""
    db = tmp_path / "test.db"
    import footstats.core.coupon_tracker as ct
    monkeypatch.setattr(ct, "DB_PATH", db)
    yield db


from footstats.core.coupon_tracker import (
    init_coupon_tables,
    save_coupon,
    update_coupon_status,
    get_active_coupons,
    get_coupon_legs,
)


def test_save_coupon_returns_positive_id():
    legs = [{"gospodarz": "PSG", "goscie": "Lyon", "typ": "1", "kurs": 1.45}]
    cid = save_coupon("draft", "A", legs, total_odds=1.45, stake_pln=10.0)
    assert isinstance(cid, int)
    assert cid > 0


def test_new_coupon_has_draft_status():
    cid = save_coupon("draft", "A", [])
    active = get_active_coupons()
    assert len(active) == 1
    assert active[0]["status"] == "DRAFT"


def test_lost_coupon_not_in_active():
    cid = save_coupon("final", "A", [], stake_pln=10.0)
    update_coupon_status(cid, "LOST", payout_pln=0.0)
    active = get_active_coupons()
    assert all(c["id"] != cid for c in active)


def test_won_coupon_roi_calculated():
    cid = save_coupon("final", "A", [], stake_pln=10.0)
    update_coupon_status(cid, "WON", payout_pln=110.0)
    from footstats.core.coupon_tracker import _connect
    with _connect() as conn:
        row = conn.execute("SELECT roi_pct FROM coupons WHERE id=?", (cid,)).fetchone()
    assert row["roi_pct"] == pytest.approx(1000.0, abs=1.0)


def test_get_coupon_legs_roundtrip():
    legs = [{"gospodarz": "Bayern", "goscie": "Dortmund", "typ": "1X", "kurs": 1.30}]
    cid = save_coupon("draft", "B", legs)
    assert get_coupon_legs(cid) == legs


def test_get_coupon_legs_unknown_id_returns_empty():
    assert get_coupon_legs(9999) == []


def test_init_coupon_tables_idempotent():
    """Wielokrotne wywołanie nie exploduje."""
    init_coupon_tables()
    init_coupon_tables()


def test_update_coupon_status_invalid_raises():
    cid = save_coupon("draft", "A", [])
    with pytest.raises(ValueError, match="Nieprawidłowy"):
        update_coupon_status(cid, "INVALID_STATUS")


# ── get_draft_today ────────────────────────────────────────────────────────────

def test_get_draft_today_returns_todays_draft():
    from footstats.core.coupon_tracker import get_draft_today
    cid = save_coupon("draft", "A", [])
    row = get_draft_today()
    assert row is not None
    assert row["id"] == cid


def test_get_draft_today_ignores_active_coupon():
    from footstats.core.coupon_tracker import get_draft_today
    cid = save_coupon("final", "A", [], stake_pln=10.0)
    update_coupon_status(cid, "ACTIVE")
    row = get_draft_today()
    assert row is None


def test_get_draft_today_none_when_empty():
    from footstats.core.coupon_tracker import get_draft_today
    row = get_draft_today()
    assert row is None


# ── promote_to_active ──────────────────────────────────────────────────────────

def test_promote_to_active_changes_status_to_active():
    from footstats.core.coupon_tracker import promote_to_active
    cid = save_coupon("draft", "A", [])
    promote_to_active(cid)
    active = get_active_coupons()
    rows = [c for c in active if c["id"] == cid]
    assert rows, "Kupon powinien być w active_coupons po promocji"
    assert rows[0]["status"] == "ACTIVE"
    assert rows[0]["phase"] == "final"


def test_promote_to_active_updates_legs_and_reasoning():
    from footstats.core.coupon_tracker import promote_to_active
    cid = save_coupon("draft", "A", [{"home": "A", "away": "B"}])
    new_legs = [{"home": "X", "away": "Y", "tip": "1"}]
    promote_to_active(cid, legs=new_legs, groq_reasoning="test reason", decision_score=75)
    assert get_coupon_legs(cid) == new_legs


def test_promote_to_active_no_legs_keeps_old_legs():
    from footstats.core.coupon_tracker import promote_to_active
    original_legs = [{"home": "PSG", "away": "Lyon"}]
    cid = save_coupon("draft", "A", original_legs)
    promote_to_active(cid)  # bez nowych nóg
    assert get_coupon_legs(cid) == original_legs
