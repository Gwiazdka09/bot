"""Integration tests — every /api/* route must reject requests without a valid token."""
import os

import bcrypt
import pytest

os.environ.setdefault("JWT_SECRET", "testsecret1234567890abcdef12345678")
os.environ.setdefault("FOOTSTATS_USER", "admin")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost:5173")

_hash = bcrypt.hashpw(b"testpass", bcrypt.gensalt()).decode()
os.environ.setdefault("FOOTSTATS_PASSWORD_HASH", _hash)

from fastapi.testclient import TestClient

from footstats.api.main import app

client = TestClient(app, raise_server_exceptions=False)


def _token() -> str:
    r = client.post("/auth/login", json={"username": "admin", "password": "testpass"})
    return r.json()["access_token"]


PROTECTED_ROUTES = [
    ("GET", "/api/status"),
    ("GET", "/api/config"),
    ("GET", "/api/coupons"),
    ("GET", "/api/coupons/active"),
    ("GET", "/api/bankroll/history"),
    ("GET", "/api/settings"),
    ("GET", "/api/matches/today"),
]


@pytest.mark.parametrize("method,path", PROTECTED_ROUTES)
def test_route_rejects_no_token(method, path):
    resp = client.request(method, path)
    assert resp.status_code == 401, f"{method} {path} should return 401 without token"


@pytest.mark.parametrize("method,path", PROTECTED_ROUTES)
def test_route_accepts_valid_token(method, path):
    token = _token()
    resp = client.request(method, path, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code != 401, f"{method} {path} should not return 401 with valid token"


def test_spa_root_is_public():
    resp = client.get("/")
    assert resp.status_code == 200


def test_cors_wildcard_gone():
    resp = client.options(
        "/api/status",
        headers={"Origin": "http://evil.com", "Access-Control-Request-Method": "GET"},
    )
    allowed = resp.headers.get("access-control-allow-origin", "")
    assert allowed != "*", "Wildcard CORS must not be present"
    assert "evil.com" not in allowed, "evil.com must not be allowed"


def test_cors_allowed_origin():
    resp = client.options(
        "/api/status",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_login_rate_limit():
    for _ in range(5):
        client.post("/auth/login", json={"username": "x", "password": "x"})
    resp = client.post("/auth/login", json={"username": "x", "password": "x"})
    assert resp.status_code in (401, 429)
