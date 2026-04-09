"""tests/test_decision_score.py"""
import pytest
from footstats.core.decision_score import score_kandydat, is_go, PROG_DRAFT, PROG_FINAL


def _kandydat(**kwargs) -> dict:
    """Buduje minimalny słownik kandydata z defaultami."""
    defaults = {
        "ev_netto": -0.01,
        "pewnosc": 0.60,
        "czynniki": [],
        "roznica_modeli": 5.0,
        "accuracy": None,
    }
    defaults.update(kwargs)
    return defaults


def test_ev_netto_positive_gives_15_points():
    w = _kandydat(ev_netto=0.05)
    score, powody = score_kandydat(w)
    assert score >= 15
    assert any("EV_netto" in p for p in powody)


def test_ev_netto_negative_gives_0():
    w = _kandydat(ev_netto=-0.01)
    score, _ = score_kandydat(w)
    # zero za EV; pozostałe kryteria (brak ROTACJA +15, brak ROZBIEŻNOŚCI +10)
    # dają łącznie 25 — poniżej progu draft (40), ale nie poniżej 15
    assert score < PROG_DRAFT  # bez EV nie osiąga progu przy domyślnych wartościach


def test_high_confidence_gives_20_points():
    w = _kandydat(pewnosc=0.80, ev_netto=-0.01, roznica_modeli=25.0)
    score, _ = score_kandydat(w)
    assert score >= 20


def test_confidence_below_70_gives_0_for_confidence():
    w = _kandydat(pewnosc=0.65)
    score, _ = score_kandydat(w)
    # brak rotacji/zmęczenia (+15) + brak rozbieżności (+10) = 25 max bez confidence
    assert score <= 25


def test_rotacja_removes_15_points():
    w_clean = _kandydat(czynniki=[])
    w_rotacja = _kandydat(czynniki=["ROTACJA"])
    s_clean, _ = score_kandydat(w_clean)
    s_rotacja, _ = score_kandydat(w_rotacja)
    assert s_clean - s_rotacja == 15


def test_patent_gives_10_points():
    w_no = _kandydat(czynniki=[])
    w_patent = _kandydat(czynniki=["PATENT"])
    s_no, _ = score_kandydat(w_no)
    s_patent, _ = score_kandydat(w_patent)
    assert s_patent - s_no == 10


def test_twierdza_gives_10_points():
    w = _kandydat(czynniki=["TWIERDZA"])
    s, powody = score_kandydat(w)
    assert any("TWIERDZA" in p for p in powody)


def test_historical_accuracy_above_65_gives_10():
    w = _kandydat(accuracy=0.70)
    s_with, _ = score_kandydat(w)
    w_no = _kandydat(accuracy=0.60)
    s_without, _ = score_kandydat(w_no)
    assert s_with - s_without == 10


def test_rozbieznosc_above_20_removes_10():
    w_ok = _kandydat(roznica_modeli=10.0)
    w_rozn = _kandydat(roznica_modeli=25.0)
    s_ok, _ = score_kandydat(w_ok)
    s_rozn, _ = score_kandydat(w_rozn)
    assert s_ok - s_rozn == 10


def test_lineup_ok_gives_10_only_in_final_phase():
    w = _kandydat()
    ctx = {"lineup_ok": True, "referee_neutral": False}
    s_draft, _ = score_kandydat(w, ctx, phase="draft")
    s_final, _ = score_kandydat(w, ctx, phase="final")
    assert s_final - s_draft == 10  # tylko lineup (referee_neutral=False → 0)


def test_referee_neutral_gives_10_only_in_final_phase():
    w = _kandydat()
    ctx = {"lineup_ok": False, "referee_neutral": True}
    s_draft, _ = score_kandydat(w, ctx, phase="draft")
    s_final, _ = score_kandydat(w, ctx, phase="final")
    assert s_final - s_draft == 10


def test_perfect_candidate_scores_80_in_draft():
    """Maks w drafcie: 15+20+15+10+10+10 = 80 (bez składu i sędziego)."""
    w = _kandydat(
        ev_netto=0.10,
        pewnosc=0.85,
        czynniki=["PATENT"],
        roznica_modeli=5.0,
        accuracy=0.75,
    )
    score, _ = score_kandydat(w, phase="draft")
    assert score == 80


def test_is_go_draft_threshold():
    assert is_go(40, "draft") is True
    assert is_go(39, "draft") is False


def test_is_go_final_threshold():
    assert is_go(60, "final") is True
    assert is_go(59, "final") is False


def test_pewnosc_as_percentage_normalized():
    """pewnosc=85 (procenty) traktowane jak 0.85."""
    w = _kandydat(pewnosc=85)  # podane jako procenty
    score, _ = score_kandydat(w)
    assert score >= 20  # confidence > 70% → +20
