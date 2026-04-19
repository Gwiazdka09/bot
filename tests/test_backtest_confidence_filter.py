"""Test confidence filter in backtest engine."""

import pytest
from src.footstats.core.backtest_engine import _evaluate_tip, _extract_tips_from_analysis


def test_evaluate_tip_with_low_confidence():
    """Predictions with confidence < 75 should be marked for skipping."""
    tip = {
        "typ": "1",
        "pewnosc": 60,  # Below 75% threshold
        "kurs": 1.80,
        "source": "groq",
    }
    fixture = {
        "fixture_id": 12345,
        "home": "Bayern",
        "away": "Dortmund",
        "league": "Bundesliga",
        "date": "2025-01-15",
        "score_str": "2-1",
    }

    result = _evaluate_tip(tip, fixture)

    # Should still evaluate, but mark for skipping
    assert result["pewnosc"] == 60
    assert result["skip_low_confidence"] is True


def test_evaluate_tip_with_high_confidence():
    """Predictions with confidence >= 75 should be included."""
    tip = {
        "typ": "1",
        "pewnosc": 80,  # Above 75% threshold
        "kurs": 1.80,
        "source": "groq",
    }
    fixture = {
        "fixture_id": 12345,
        "home": "Bayern",
        "away": "Dortmund",
        "league": "Bundesliga",
        "date": "2025-01-15",
        "score_str": "2-1",
    }

    result = _evaluate_tip(tip, fixture)

    # Should be included (no skip flag)
    assert result["pewnosc"] == 80
    assert result.get("skip_low_confidence") is not True


def test_evaluate_tip_with_boundary_75_confidence():
    """Predictions with exactly 75 confidence should be included."""
    tip = {
        "typ": "1",
        "pewnosc": 75,  # Exactly at threshold
        "kurs": 1.80,
        "source": "groq",
    }
    fixture = {
        "fixture_id": 12345,
        "home": "Bayern",
        "away": "Dortmund",
        "league": "Bundesliga",
        "date": "2025-01-15",
        "score_str": "2-1",
    }

    result = _evaluate_tip(tip, fixture)

    # Should be included (boundary condition)
    assert result["pewnosc"] == 75
    assert result.get("skip_low_confidence") is not True
