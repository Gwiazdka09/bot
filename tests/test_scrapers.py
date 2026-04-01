"""Testy scrapers/ – mockowane połączenia HTTP."""
import pytest
import requests
from unittest.mock import patch, MagicMock

import footstats.scrapers.base as base_mod
from footstats.scrapers.base import _http_get


class TestHttpGet:
    def test_sukces_zwraca_json(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"competitions": []}
        with patch.object(base_mod.requests, "get", return_value=mock_resp):
            wynik = _http_get("/competitions", headers={"X-Auth-Token": "test"})
            assert wynik == {"competitions": []}

    def test_status_403_zwraca_none(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        with patch.object(base_mod.requests, "get", return_value=mock_resp):
            wynik = _http_get("/competitions", headers={"X-Auth-Token": "bad"})
            assert wynik is None

    def test_status_404_zwraca_none(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with patch.object(base_mod.requests, "get", return_value=mock_resp):
            wynik = _http_get("/nieistniejacy", headers={})
            assert wynik is None

    def test_connection_error_zwraca_none(self):
        with patch.object(base_mod.requests, "get",
                          side_effect=requests.ConnectionError("no network")):
            wynik = _http_get("/competitions", headers={})
            assert wynik is None

    def test_timeout_zwraca_none(self):
        with patch.object(base_mod.requests, "get",
                          side_effect=requests.Timeout("timeout")):
            wynik = _http_get("/competitions", headers={})
            assert wynik is None
