import pytest
from unittest.mock import patch, MagicMock
from footstats.scrapers.lineup_scraper import get_lineup, lineup_confidence_penalty


_MOCK_RESPONSE = {
    "response": [
        {
            "team": {"id": 85, "name": "Paris Saint-Germain"},
            "formation": "4-3-3",
            "startXI": [
                {"player": {"name": "Donnarumma"}},
                {"player": {"name": "Hakimi"}},
                {"player": {"name": "Marquinhos"}},
                {"player": {"name": "Pacho"}},
                {"player": {"name": "Nuno Mendes"}},
                {"player": {"name": "Vitinha"}},
                {"player": {"name": "Joao Neves"}},
                {"player": {"name": "Fabian Ruiz"}},
                {"player": {"name": "Dembele"}},
                {"player": {"name": "Barcola"}},
                {"player": {"name": "Ramos"}},
            ],
        },
        {
            "team": {"id": 80, "name": "Lyon"},
            "formation": "4-2-3-1",
            "startXI": [
                {"player": {"name": "Perri"}},
                {"player": {"name": "Maitland-Niles"}},
                {"player": {"name": "Caleta-Car"}},
                {"player": {"name": "Niakhate"}},
                {"player": {"name": "Tagliafico"}},
                {"player": {"name": "Matic"}},
                {"player": {"name": "Tolisso"}},
                {"player": {"name": "Cherki"}},
                {"player": {"name": "Nuamah"}},
                {"player": {"name": "Lacazette"}},
                {"player": {"name": "Mikautadze"}},
            ],
        },
    ]
}


def test_get_lineup_returns_dict_with_home_away():
    with patch("footstats.scrapers.lineup_scraper.requests.get") as mock_get:
        resp = MagicMock()
        resp.json.return_value = _MOCK_RESPONSE
        resp.raise_for_status = MagicMock()
        mock_get.return_value = resp
        result = get_lineup(12345, "fake_key")
        assert result is not None
        assert "home" in result
        assert "away" in result


def test_get_lineup_home_has_11_players():
    with patch("footstats.scrapers.lineup_scraper.requests.get") as mock_get:
        resp = MagicMock()
        resp.json.return_value = _MOCK_RESPONSE
        resp.raise_for_status = MagicMock()
        mock_get.return_value = resp
        result = get_lineup(12345, "fake_key")
        assert len(result["home"]["startXI"]) == 11


def test_get_lineup_returns_none_on_empty_response():
    with patch("footstats.scrapers.lineup_scraper.requests.get") as mock_get:
        resp = MagicMock()
        resp.json.return_value = {"response": []}
        resp.raise_for_status = MagicMock()
        mock_get.return_value = resp
        result = get_lineup(12345, "fake_key")
        assert result is None


def test_get_lineup_returns_none_on_request_error():
    import requests as req
    with patch("footstats.scrapers.lineup_scraper.requests.get") as mock_get:
        mock_get.side_effect = req.RequestException("timeout")
        result = get_lineup(12345, "fake_key")
        assert result is None


def test_lineup_confidence_penalty_no_penalty_when_full_squad():
    lineup = {
        "home": {"missing_key_players": False},
        "away": {"missing_key_players": False},
    }
    assert lineup_confidence_penalty(lineup) == 0


def test_lineup_confidence_penalty_minus_15_when_home_missing():
    lineup = {
        "home": {"missing_key_players": True},
        "away": {"missing_key_players": False},
    }
    assert lineup_confidence_penalty(lineup) == -15


def test_lineup_confidence_penalty_minus_30_when_both_missing():
    lineup = {
        "home": {"missing_key_players": True},
        "away": {"missing_key_players": True},
    }
    assert lineup_confidence_penalty(lineup) == -30


def test_lineup_confidence_penalty_none_returns_zero():
    assert lineup_confidence_penalty(None) == 0
