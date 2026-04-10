"""tests/test_evening_agent.py"""
import pytest
from unittest.mock import patch


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def patch_db(tmp_path, monkeypatch):
    """Przekieruj obie bazy na tmp."""
    import footstats.core.coupon_tracker as ct
    import footstats.core.backtest as bt
    db = tmp_path / "test.db"
    monkeypatch.setattr(ct, "DB_PATH", db)
    monkeypatch.setattr(bt, "DB_PATH", db)
    yield db


@pytest.fixture
def sample_fixture_psg_lyon():
    """Fixture API-Football: PSG 2-1 Lyon (zakończony)."""
    return {
        "fixture": {"status": {"short": "FT"}},
        "teams": {
            "home": {"name": "Paris Saint-Germain"},
            "away": {"name": "Olympique Lyonnais"},
        },
        "goals": {"home": 2, "away": 1},
    }


@pytest.fixture
def sample_fixture_inprogress():
    """Fixture API-Football: mecz w trakcie."""
    return {
        "fixture": {"status": {"short": "1H"}},
        "teams": {
            "home": {"name": "Bayern Munich"},
            "away": {"name": "Borussia Dortmund"},
        },
        "goals": {"home": 1, "away": 0},
    }


# ── Testy pomocników ────────────────────────────────────────────────────────

from footstats.evening_agent import (
    _wynik_z_fixture,
    _find_result,
    _status_kuponu,
)


def test_wynik_z_fixture_finished(sample_fixture_psg_lyon):
    result = _wynik_z_fixture(sample_fixture_psg_lyon)
    assert result == ("Paris Saint-Germain", "Olympique Lyonnais", "2-1")


def test_wynik_z_fixture_inprogress_returns_none(sample_fixture_inprogress):
    assert _wynik_z_fixture(sample_fixture_inprogress) is None


def test_find_result_fuzzy_match(sample_fixture_psg_lyon):
    wynik = _find_result("PSG", "Lyon", [sample_fixture_psg_lyon])
    assert wynik == "2-1"


def test_find_result_no_match():
    fixture = {
        "fixture": {"status": {"short": "FT"}},
        "teams": {"home": {"name": "Juventus"}, "away": {"name": "Inter"}},
        "goals": {"home": 1, "away": 1},
    }
    wynik = _find_result("Arsenal", "Chelsea", [fixture])
    assert wynik is None


def test_status_kuponu_all_win():
    assert _status_kuponu(["WIN", "WIN", "WIN"]) == "WON"


def test_status_kuponu_any_loss():
    assert _status_kuponu(["WIN", "LOSS", "WIN"]) == "LOST"


def test_status_kuponu_pending_stays_active():
    assert _status_kuponu(["WIN", "PENDING"]) == "ACTIVE"


def test_status_kuponu_all_void():
    assert _status_kuponu(["VOID", "VOID"]) == "VOID"


def test_status_kuponu_empty():
    assert _status_kuponu([]) == "VOID"


# ── Test integracyjny run_evening_agent ─────────────────────────────────────

def test_run_evening_agent_marks_coupon_won(sample_fixture_psg_lyon):
    """Kupon z nogą PSG-1 wygrywa gdy PSG wygrywa 2-1."""
    from footstats.core.coupon_tracker import save_coupon, get_active_coupons, init_coupon_tables
    from footstats.evening_agent import run_evening_agent

    init_coupon_tables()
    legs = [{"gospodarz": "PSG", "goscie": "Lyon", "typ": "1", "kurs": 1.45}]
    save_coupon("final", "A", legs, total_odds=1.45, stake_pln=10.0)

    with patch("footstats.evening_agent._fetch_results_today",
               return_value=[sample_fixture_psg_lyon]), \
         patch("footstats.evening_agent._send_telegram_summary"), \
         patch.dict("os.environ", {"APISPORTS_KEY": "test_key"}):
        summary = run_evening_agent("2026-04-09")

    assert summary["won"] == 1
    active = get_active_coupons()
    assert len(active) == 0  # kupon przeniesiony do WON


def test_run_evening_agent_marks_coupon_lost(sample_fixture_psg_lyon):
    """Kupon z nogą Lyon-1 przegrywa gdy Lyon przegrywa 1-2."""
    from footstats.core.coupon_tracker import save_coupon, get_active_coupons, init_coupon_tables
    from footstats.evening_agent import run_evening_agent

    init_coupon_tables()
    legs = [{"gospodarz": "PSG", "goscie": "Lyon", "typ": "2", "kurs": 3.20}]
    save_coupon("final", "A", legs, total_odds=3.20, stake_pln=10.0)

    with patch("footstats.evening_agent._fetch_results_today",
               return_value=[sample_fixture_psg_lyon]), \
         patch("footstats.evening_agent._send_telegram_summary"), \
         patch.dict("os.environ", {"APISPORTS_KEY": "test_key"}):
        summary = run_evening_agent("2026-04-09")

    assert summary["lost"] == 1


def test_run_evening_agent_pending_when_no_result():
    """Kupon zostaje ACTIVE gdy mecz jeszcze nie zakończony."""
    from footstats.core.coupon_tracker import save_coupon, get_active_coupons, init_coupon_tables
    from footstats.evening_agent import run_evening_agent

    init_coupon_tables()
    legs = [{"gospodarz": "Bayern", "goscie": "Dortmund", "typ": "1", "kurs": 1.60}]
    save_coupon("final", "A", legs, total_odds=1.60, stake_pln=10.0)

    with patch("footstats.evening_agent._fetch_results_today", return_value=[]), \
         patch("footstats.evening_agent._send_telegram_summary"), \
         patch.dict("os.environ", {"APISPORTS_KEY": "test_key"}):
        summary = run_evening_agent("2026-04-09")

    assert summary["active"] == 1
    active = get_active_coupons()
    assert len(active) == 1  # nadal aktywny


def test_run_evening_agent_triggers_auto_trainer():
    """Gdy >= 20 nóg dostaje wyniki → auto-trainer jest uruchamiany."""
    from footstats.core.coupon_tracker import save_coupon, init_coupon_tables, promote_to_active
    from footstats.evening_agent import run_evening_agent

    init_coupon_tables()

    # Tworzymy 20 kuponów jednonożnych — każdy z inną drużyną
    fixtures = []
    for i in range(20):
        home = f"HomeTeam{i}"
        away = f"AwayTeam{i}"
        legs = [{"home": home, "away": away, "typ": "1"}]
        cid = save_coupon("draft", "A", legs, stake_pln=10.0, total_odds=1.5)
        promote_to_active(cid)
        fixtures.append({
            "fixture": {"status": {"short": "FT"}},
            "teams": {"home": {"name": home}, "away": {"name": away}},
            "goals": {"home": 1, "away": 0},
        })

    with patch("footstats.evening_agent._fetch_results_today", return_value=fixtures), \
         patch("footstats.evening_agent._send_telegram_summary"), \
         patch("subprocess.Popen") as mock_popen, \
         patch.dict("os.environ", {"APISPORTS_KEY": "test_key"}):
        run_evening_agent("2026-04-09")

    mock_popen.assert_called_once()
    call_args = mock_popen.call_args[0][0]
    assert "footstats.ai.trainer" in call_args
