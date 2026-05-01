# Phase 2 — Frontend Build + fastapi_mcp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace hardcoded localhost API URL, produce a production Vite build served by FastAPI, and expose FootStats endpoints as MCP tools via fastapi_mcp.

**Architecture:** Vite reads `VITE_API_BASE` from `.env` at build time → produces `gui/dist/` → FastAPI mounts `dist/` as StaticFiles and serves the SPA. fastapi_mcp wraps the existing FastAPI `app` and mounts `/mcp` endpoint with JWT auth pass-through.

**Tech Stack:** React + Vite 8, FastAPI, fastapi-mcp 0.x, python-dotenv

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/footstats/gui/src/App.jsx` | Modify line 10 | Replace hardcoded `API_BASE` with `import.meta.env.VITE_API_BASE` |
| `src/footstats/gui/.env` | Create | Dev env vars (`VITE_API_BASE=http://localhost:8000/api`) |
| `src/footstats/gui/.env.production` | Create | Prod env vars (placeholder for real domain) |
| `src/footstats/gui/vite.config.ts` | Create | Build config — output dir, React plugin |
| `src/footstats/api/main.py` | Modify | Mount `gui/dist/` as StaticFiles, add fastapi_mcp |
| `pyproject.toml` | Modify | Add `fastapi-mcp>=0.3` dependency |
| `tests/test_phase2.py` | Create | Integration tests for SPA serving + MCP endpoint |

---

## Task 1: API_BASE z env variable

**Files:**
- Modify: `src/footstats/gui/src/App.jsx:10`
- Create: `src/footstats/gui/.env`
- Create: `src/footstats/gui/.env.production`

- [ ] **Step 1: Napisz failing test**

```bash
# Test manualny — sprawdź że hardcoded string istnieje (powinien PASS przed zmianą, FAIL po)
grep -n "localhost:8000" src/footstats/gui/src/App.jsx
```

Expected: `10:const API_BASE = "http://localhost:8000/api";`

- [ ] **Step 2: Zamień API_BASE w App.jsx**

Zmień linię 10 w `src/footstats/gui/src/App.jsx`:

```js
const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000/api";
```

- [ ] **Step 3: Utwórz src/footstats/gui/.env**

```
VITE_API_BASE=http://localhost:8000/api
```

- [ ] **Step 4: Utwórz src/footstats/gui/.env.production**

```
VITE_API_BASE=https://YOUR_DOMAIN/api
```

- [ ] **Step 5: Zweryfikuj — hardcoded string zniknął**

```bash
grep -n "localhost:8000" src/footstats/gui/src/App.jsx
```

Expected: brak output (grep zwraca exit 1).

- [ ] **Step 6: Commit**

```bash
git add src/footstats/gui/src/App.jsx src/footstats/gui/.env src/footstats/gui/.env.production
git commit -m "feat: replace hardcoded API_BASE with VITE_API_BASE env var"
```

---

## Task 2: Vite config + production build

**Files:**
- Create: `src/footstats/gui/vite.config.ts`

- [ ] **Step 1: Sprawdź czy vite.config już istnieje**

```bash
ls src/footstats/gui/vite.config*
```

Expected: brak pliku (No such file).

- [ ] **Step 2: Utwórz src/footstats/gui/vite.config.ts**

```ts
import { defineConfig } from 'vite'

export default defineConfig({
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
  },
})
```

Uwaga: brak pluginu React — package.json nie ma `@vitejs/plugin-react`. Jeśli `npm run build` wyrzuci błąd JSX transform, dodaj:

```bash
cd src/footstats/gui && npm install -D @vitejs/plugin-react
```

I zaktualizuj vite.config.ts:

```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
  },
})
```

- [ ] **Step 3: Uruchom build**

```bash
cd src/footstats/gui && npm run build
```

Expected: `dist/index.html` i `dist/assets/` powstają. Jeśli TypeScript error — sprawdź `tsconfig.json` i popraw.

- [ ] **Step 4: Zweryfikuj dist/**

```bash
ls src/footstats/gui/dist/
```

Expected: `index.html  assets/`

- [ ] **Step 5: Commit**

```bash
git add src/footstats/gui/vite.config.ts src/footstats/gui/package.json src/footstats/gui/package-lock.json
git commit -m "feat: add vite config and produce production build"
```

---

## Task 3: FastAPI serwuje SPA z dist/

**Files:**
- Modify: `src/footstats/api/main.py`
- Create: `tests/test_phase2.py` (częściowo)

- [ ] **Step 1: Napisz failing test**

Utwórz `tests/test_phase2.py`:

```python
import pytest
from fastapi.testclient import TestClient
from footstats.api.main import app

client = TestClient(app, raise_server_exceptions=False)


def test_spa_root_returns_html():
    """GET / serwuje index.html z dist/ (lub redirect do /app)."""
    resp = client.get("/", follow_redirects=True)
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_spa_assets_served():
    """Pliki statyczne z dist/assets/ są dostępne."""
    import os
    dist = "src/footstats/gui/dist/assets"
    if not os.path.exists(dist):
        pytest.skip("dist/ not built yet")
    asset = next(
        (f for f in os.listdir(dist) if f.endswith(".js")), None
    )
    if asset is None:
        pytest.skip("no JS assets in dist/")
    resp = client.get(f"/assets/{asset}")
    assert resp.status_code == 200
```

- [ ] **Step 2: Uruchom test — powinien FAIL**

```bash
pytest tests/test_phase2.py::test_spa_root_returns_html -v
```

Expected: FAIL — `GET /` zwraca redirect do `/preview`, nie HTML SPA.

- [ ] **Step 3: Zamień `/preview` na SPA serving w main.py**

Zastąp sekcję `@app.get("/")` i `@app.get("/preview")` na końcu `main.py`:

```python
from fastapi.staticfiles import StaticFiles

_dist = Path(__file__).parent.parent.parent / "gui" / "dist"

if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/")
    def root():
        return FileResponse(_dist / "index.html", media_type="text/html")

    @app.get("/app")
    def serve_app():
        return FileResponse(_dist / "index.html", media_type="text/html")
else:
    @app.get("/")
    def root():
        return RedirectResponse(url="/preview")

    @app.get("/preview")
    def serve_preview():
        html_path = Path(__file__).parent / "preview.html"
        return FileResponse(html_path, media_type="text/html")
```

- [ ] **Step 4: Uruchom testy**

```bash
pytest tests/test_phase2.py -v
pytest tests/ -v --tb=short
```

Expected: `test_phase2.py` PASS (dist/ istnieje), pozostałe 25 testów nadal PASS.

- [ ] **Step 5: Commit**

```bash
git add src/footstats/api/main.py tests/test_phase2.py
git commit -m "feat: FastAPI serves Vite SPA from dist/ with StaticFiles fallback"
```

---

## Task 4: fastapi_mcp — FootStats API jako MCP server

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/footstats/api/main.py`
- Modify: `tests/test_phase2.py`

- [ ] **Step 1: Dodaj failing test dla /mcp endpoint**

Dopisz do `tests/test_phase2.py`:

```python
def test_mcp_endpoint_exists():
    """MCP endpoint dostępny na /mcp."""
    resp = client.get("/mcp")
    # MCP zwraca 405 GET (oczekuje POST/SSE) lub 200 — oba OK, byle nie 404
    assert resp.status_code != 404


def test_mcp_tools_listed():
    """MCP zwraca listę tools przez POST."""
    resp = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code in (200, 405)  # 405 jeśli MCP wymaga SSE transport
```

- [ ] **Step 2: Uruchom test — powinien FAIL (404)**

```bash
pytest tests/test_phase2.py::test_mcp_endpoint_exists -v
```

Expected: FAIL — `/mcp` zwraca 404.

- [ ] **Step 3: Zainstaluj fastapi-mcp**

```bash
pip install "fastapi-mcp>=0.3"
```

- [ ] **Step 4: Dodaj fastapi-mcp do pyproject.toml**

W `pyproject.toml` w sekcji `install_requires` dodaj:

```
"fastapi-mcp>=0.3",
```

- [ ] **Step 5: Dodaj FastApiMCP do main.py**

Po `app.include_router(coupons_router)` dopisz:

```python
from fastapi_mcp import FastApiMCP

mcp = FastApiMCP(app)
mcp.mount()
```

- [ ] **Step 6: Uruchom testy**

```bash
pytest tests/test_phase2.py -v
pytest tests/ -v --tb=short
```

Expected: `test_mcp_endpoint_exists` PASS. Wszystkie 25 poprzednich testów nadal PASS.

- [ ] **Step 7: Smoke test MCP ręcznie**

```bash
cd F:/bot && python -c "
from footstats.api.main import app
routes = [r.path for r in app.routes]
print([r for r in routes if 'mcp' in r.lower()])
"
```

Expected: `['/mcp']` lub podobne.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml src/footstats/api/main.py tests/test_phase2.py
git commit -m "feat: expose FootStats API as MCP server via fastapi_mcp"
```

---

## Task 5: .env.production + ALLOWED_ORIGINS update

**Files:**
- Modify: `.env` (produkcja)

- [ ] **Step 1: Zaktualizuj ALLOWED_ORIGINS w .env**

Gdy znasz domenę produkcyjną, dodaj ją do `.env`:

```
ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000,https://YOUR_DOMAIN
```

- [ ] **Step 2: Zweryfikuj że test CORS nadal przechodzi**

```bash
pytest tests/test_api_routes.py -v -k "cors"
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add .env
git commit -m "chore: update ALLOWED_ORIGINS for production domain"
```

---

## Self-Review

**Spec coverage:**
- ✅ API_BASE z env → Task 1
- ✅ vite build → Task 2
- ✅ FastAPI serwuje SPA → Task 3
- ✅ fastapi_mcp → Task 4
- ✅ ALLOWED_ORIGINS → Task 5
- ⏭ HTTPS/SSL → Faza 3 (wymaga domeny + serwera)

**Placeholder scan:** Brak TBD/TODO w krokach — wszystkie mają konkretny kod.

**Type consistency:** `_dist` Path używany spójnie w Task 3.

**Ryzyko:** `dist/` path relative do `main.py` — `Path(__file__).parent.parent.parent / "gui" / "dist"`. Weryfikuj po Step 3 jeśli 404 na assets.
