"""Tests for JWT auth module."""
import os
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "testsecret1234567890abcdef12345678")
os.environ.setdefault("FOOTSTATS_USER", "admin")

import bcrypt as _bcrypt_lib
_hash = _bcrypt_lib.hashpw(b"testpass", _bcrypt_lib.gensalt()).decode()
os.environ.setdefault("FOOTSTATS_PASSWORD_HASH", _hash)


def _make_app():
    from footstats.api.auth import router as auth_router, require_auth
    from fastapi import Depends
    app = FastAPI()
    app.include_router(auth_router)

    @app.get("/protected")
    def protected(user: str = Depends(require_auth)):
        return {"user": user}

    return app


@pytest.fixture
def client():
    return TestClient(_make_app())


def test_login_success(client):
    resp = client.post("/auth/login", json={"username": "admin", "password": "testpass"})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_wrong_password(client):
    resp = client.post("/auth/login", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401


def test_login_wrong_user(client):
    resp = client.post("/auth/login", json={"username": "hacker", "password": "testpass"})
    assert resp.status_code == 401


def test_protected_no_token(client):
    resp = client.get("/protected")
    assert resp.status_code == 401


def test_protected_valid_token(client):
    login = client.post("/auth/login", json={"username": "admin", "password": "testpass"})
    token = login.json()["access_token"]
    resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["user"] == "admin"


def test_protected_invalid_token(client):
    resp = client.get("/protected", headers={"Authorization": "Bearer badtoken"})
    assert resp.status_code == 401


def test_protected_expired_token(client):
    from datetime import datetime, timedelta, timezone
    from jose import jwt
    secret = os.environ["JWT_SECRET"]
    expired = jwt.encode(
        {"sub": "admin", "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
        secret, algorithm="HS256"
    )
    resp = client.get("/protected", headers={"Authorization": f"Bearer {expired}"})
    assert resp.status_code == 401
