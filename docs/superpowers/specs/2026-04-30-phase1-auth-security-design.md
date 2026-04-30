# Phase 1 – Auth + Security Design
**Date:** 2026-04-30  
**Scope:** FastAPI `src/footstats/api/` — JWT auth, CORS fix, rate limiting

---

## Architecture

Refactor monolithic `main.py` into routers. Add `auth.py` module. All endpoints protected via `Depends(require_auth)`. No DB users table — credentials from env vars (single-user, expandable to multi-user in Phase 4).

```
src/footstats/api/
├── main.py           # app factory, middleware, router registration
├── auth.py           # JWT logic, /auth/login, require_auth dependency
├── routes/
│   ├── status.py     # GET /api/status, /api/config
│   ├── coupons.py    # /api/coupons/*, /api/matches/*
│   ├── bankroll.py   # /api/bankroll, /api/bankroll/history
│   └── settings.py   # /api/settings
└── preview.html      # public (no data exposed)
```

## Components

### auth.py
- `POST /auth/login` — accepts `{username, password}`, returns `{access_token, token_type}`
- `require_auth` — FastAPI `Depends`, validates `Bearer` JWT, raises 401 on failure
- JWT: HS256, 24h expiry, secret from `JWT_SECRET` env var
- Password: bcrypt hash stored in `FOOTSTATS_PASSWORD_HASH` env var
- Libraries: `python-jose[cryptography]`, `passlib[bcrypt]`

### main.py changes
- `CORSMiddleware`: `allow_origins` from `ALLOWED_ORIGINS` env var (comma-separated), no wildcard
- `SlowAPIMiddleware`: 60 req/min per IP; `/auth/login` limited to 5 req/min
- `/preview` stays public (static HTML, no data)
- All `/api/*` routers include `Depends(require_auth)` at router level

### Environment variables (`.env`)
```
JWT_SECRET=<secrets.token_hex(32)>
FOOTSTATS_USER=admin
FOOTSTATS_PASSWORD_HASH=<bcrypt hash>
ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000
```

## Data Flow

```
Client → POST /auth/login → validate bcrypt → issue JWT
Client → GET /api/* [Bearer JWT] → require_auth validates → handler
Client → GET /preview → public, no auth
```

## Error Handling
- Invalid token → 401 `{"detail": "Invalid credentials"}`
- Expired token → 401 `{"detail": "Token expired"}`
- Rate limit exceeded → 429
- CORS violation blocked at middleware level (no response)

## Testing
- Unit: `test_auth.py` — login success, wrong password, expired token, missing header
- Integration: each router with valid/invalid token
- Security: verify wildcard CORS gone, rate limit triggers at 6th login attempt

## Out of Scope (Phase 2+)
- HTTPS/SSL (Phase 2)
- PostgreSQL migration (Phase 2)
- Multi-user / registration (Phase 4)
- Refresh tokens (Phase 4)
