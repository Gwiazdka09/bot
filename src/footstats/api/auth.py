"""JWT authentication for FootStats API."""
import os
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel

_ALGORITHM = "HS256"
_EXPIRE_HOURS = 24
_bearer = HTTPBearer(auto_error=False)

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


def _secret() -> str:
    s = os.environ.get("JWT_SECRET", "")
    if not s:
        raise RuntimeError("JWT_SECRET env var not set")
    return s


def _make_token(username: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=_EXPIRE_HOURS)
    return jwt.encode({"sub": username, "exp": exp}, _secret(), algorithm=_ALGORITHM)


@router.post("/auth/login", response_model=TokenResponse)
def login(req: LoginRequest) -> TokenResponse:
    expected_user = os.environ.get("FOOTSTATS_USER", "")
    expected_hash = os.environ.get("FOOTSTATS_PASSWORD_HASH", "")
    valid = (
        req.username == expected_user
        and bool(expected_hash)
        and bcrypt.checkpw(req.password.encode(), expected_hash.encode())
    )
    if not valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return TokenResponse(access_token=_make_token(req.username))


def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    try:
        payload = jwt.decode(credentials.credentials, _secret(), algorithms=[_ALGORITHM])
        username: str = payload.get("sub", "")
        if not username:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return username
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
