import pytest
from src.footstats.ai.analyzer import _analizuj_forme


def test_analizuj_forme_returns_correct_stats():
    """Form analysis should calculate wins, losses, goals avg, trend."""
    forma = _analizuj_forme([
        {"result": "1", "scored": 2, "conceded": 0},  # Win
        {"result": "1", "scored": 1, "conceded": 0},  # Win
        {"result": "0", "scored": 1, "conceded": 2},  # Loss
        {"result": "1", "scored": 3, "conceded": 1},  # Win
        {"result": "1", "scored": 2, "conceded": 0},  # Win
    ])

    assert forma["wins"] == 4
    assert forma["losses"] == 1
    assert forma["draws"] == 0
    assert forma["gf_avg"] == 1.8  # (2+1+1+3+2)/5
    assert forma["ga_avg"] == 0.6  # (0+0+2+1+0)/5
    assert forma["trend"] in ["strong_up", "up", "stable", "down", "strong_down"]


def test_analizuj_forme_empty_list():
    """Should handle empty match list gracefully."""
    forma = _analizuj_forme([])
    assert forma["wins"] == 0
    assert forma["gf_avg"] == 0
    assert forma["trend"] == "unknown"
