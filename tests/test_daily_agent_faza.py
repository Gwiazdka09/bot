import pytest
from unittest.mock import patch


def test_decision_score_kandydat_wrapper_returns_tuple():
    from footstats.daily_agent import _decision_score_kandydat
    k = {"ev_netto": 5.0, "pewnosc": 0.75, "czynniki": [], "roznica_modeli": 0.1, "accuracy": 0.70}
    sc, reasons = _decision_score_kandydat(k, phase="draft")
    assert isinstance(sc, int)
    assert isinstance(reasons, list)
    assert sc >= 0


def test_filtruj_przez_decision_score_removes_weak():
    from footstats.daily_agent import _filtruj_przez_decision_score
    kandydaci = [
        {"ev_netto": -5.0, "pewnosc": 0.3, "czynniki": ["ROTACJA"], "roznica_modeli": 0.3, "accuracy": 0.4},
        {"ev_netto": 10.0, "pewnosc": 0.80, "czynniki": [], "roznica_modeli": 0.05, "accuracy": 0.75},
    ]
    result = _filtruj_przez_decision_score(kandydaci, phase="draft")
    assert len(result) == 1
    assert result[0]["decision_score"] >= 40  # PROG_DRAFT


def test_filtruj_przez_decision_score_adds_score_field():
    from footstats.daily_agent import _filtruj_przez_decision_score
    kandydaci = [
        {"ev_netto": 5.0, "pewnosc": 0.75, "czynniki": [], "roznica_modeli": 0.05, "accuracy": 0.70},
    ]
    result = _filtruj_przez_decision_score(kandydaci, phase="draft", prog=0)
    assert "decision_score" in result[0]
    assert "decision_reasons" in result[0]


def test_zapisz_kupon_do_db_returns_id_or_none(tmp_path):
    import footstats.core.coupon_tracker as ct
    ct.DB_PATH = tmp_path / "test.db"
    ct.init_coupon_tables()

    from footstats.daily_agent import _zapisz_kupon_do_db
    kandydaci = [{"gospodarz": "PSG", "goscie": "Lyon", "tip": "Over 2.5",
                  "kurs": 1.85, "decision_score": 65}]
    result = _zapisz_kupon_do_db(kandydaci, phase="draft", groq_resp="Test", stake=10.0, total_odds=1.85)
    assert result is None or isinstance(result, int)
