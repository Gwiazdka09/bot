import pytest
from footstats.core.ensemble import ensemble_probs, get_roznica


_P_POISSON = {"win": 0.55, "draw": 0.25, "loss": 0.20, "over25": 0.65}
_P_BZZ     = {"win": 0.50, "draw": 0.28, "loss": 0.22, "over25": 0.70}


def test_ensemble_default_weights_sum_to_one():
    result = ensemble_probs(_P_POISSON, _P_BZZ)
    assert abs(result["win"] + result["draw"] + result["loss"] - 1.0) < 0.01


def test_ensemble_with_default_weights_between_models():
    result = ensemble_probs(_P_POISSON, _P_BZZ)
    assert _P_POISSON["win"] <= result["win"] <= _P_BZZ["win"] or \
           _P_BZZ["win"] <= result["win"] <= _P_POISSON["win"]


def test_ensemble_custom_weights():
    wagi = {"poisson": 1.0, "bzzoiro": 0.0}
    result = ensemble_probs(_P_POISSON, _P_BZZ, wagi=wagi)
    assert abs(result["win"] - _P_POISSON["win"]) < 0.001


def test_ensemble_bzzoiro_only():
    wagi = {"poisson": 0.0, "bzzoiro": 1.0}
    result = ensemble_probs(_P_POISSON, _P_BZZ, wagi=wagi)
    assert abs(result["win"] - _P_BZZ["win"]) < 0.001


def test_ensemble_missing_key_in_bzzoiro():
    p_bzz_partial = {"win": 0.50, "draw": 0.28, "loss": 0.22}
    result = ensemble_probs(_P_POISSON, p_bzz_partial)
    assert "over25" in result
    assert abs(result["over25"] - _P_POISSON["over25"]) < 0.001


def test_ensemble_both_empty_returns_empty():
    result = ensemble_probs({}, {})
    assert result == {}


def test_get_roznica_detects_disagreement():
    p_e = {"win": 0.52, "draw": 0.26, "loss": 0.22}
    rozn = get_roznica(p_e, _P_POISSON, _P_BZZ)
    assert isinstance(rozn, float)
    assert rozn >= 0


def test_get_roznica_identical_models_is_zero():
    rozn = get_roznica(_P_POISSON, _P_POISSON, _P_POISSON)
    assert rozn < 0.01
