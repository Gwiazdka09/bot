# Phase 3: CI/CD + Monitoring + Backups — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship FootStats API to Cloud Run automatically on every push to main, with Sentry error tracking, structured logging, and daily SQLite backups to GCS.

**Architecture:** GitHub Actions builds a dedicated FastAPI Docker image, pushes to GHCR, deploys to Cloud Run. Sentry SDK wraps FastAPI for automatic error capture. A second GH Actions cron job (or Cloud Scheduler) syncs the SQLite DB to GCS daily.

**Tech Stack:** Docker, GitHub Actions, Google Cloud Run, GHCR, Sentry Python SDK, gcloud CLI, SQLite + GCS.

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `src/footstats/api/main.py` | Modify | Add `/health` endpoint, Sentry init |
| `Dockerfile.api` | Create | FastAPI-only image (no Playwright) |
| `.github/workflows/ci.yml` | Modify | Add Docker build step to existing CI |
| `.github/workflows/cd.yml` | Create | CD: build→push GHCR→deploy Cloud Run |
| `.github/workflows/backup.yml` | Create | Daily SQLite→GCS backup cron |
| `scripts/backup_db.sh` | Create | GCS sync script called by workflow |
| `tests/test_health.py` | Create | Health endpoint test |
| `pyproject.toml` | Modify | Add `sentry-sdk[fastapi]` to deps |

---

## Task 1: Health Check Endpoint

**Files:**
- Modify: `src/footstats/api/main.py`
- Create: `tests/test_health.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_health.py
import os
os.environ.setdefault("SECRET_KEY", "test-secret-key-32-chars-long!!")
os.environ.setdefault("FOOTBALL_API_KEY", "test")
os.environ.setdefault("APISPORTS_KEY", "test")
os.environ.setdefault("BZZOIRO_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")

from fastapi.testclient import TestClient
from footstats.api.main import app

client = TestClient(app)


def test_health_returns_200():
    response = client.get("/health")
    assert response.status_code == 200


def test_health_body():
    response = client.get("/health")
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data
```

- [ ] **Step 2: Run to verify FAIL**

```bash
cd F:/bot
python -m pytest tests/test_health.py -v
```
Expected: `FAILED — 404 Not Found`

- [ ] **Step 3: Add `/health` to main.py**

Add after `app.include_router(coupons_router)` and before the MCP block:

```python
from footstats import __version__ as _VERSION  # add to imports at top

@app.get("/health", tags=["ops"])
def health():
    return {"status": "ok", "version": _VERSION}
```

If `__version__` doesn't exist in `src/footstats/__init__.py`, add it:
```python
__version__ = "3.0"
```

- [ ] **Step 4: Run to verify PASS**

```bash
python -m pytest tests/test_health.py -v
```
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add tests/test_health.py src/footstats/api/main.py src/footstats/__init__.py
git commit -m "feat: add /health endpoint for load balancer + CI verification"
```

---

## Task 2: Sentry Error Tracking

**Files:**
- Modify: `pyproject.toml` (add sentry-sdk)
- Modify: `src/footstats/api/main.py` (init Sentry)
- Modify: `tests/test_health.py` (verify Sentry no-crash when DSN absent)

- [ ] **Step 1: Add sentry-sdk to pyproject.toml**

In `[project.dependencies]` (or create `api` extra), add:
```toml
[project.optional-dependencies]
api = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "python-jose[cryptography]>=3.3",
    "passlib[bcrypt]>=1.7",
    "slowapi>=0.1",
    "fastapi-mcp>=0.1",
    "sentry-sdk[fastapi]>=2.0",
]
```

Check what's currently in `[project.dependencies]` first — move FastAPI deps if already inline, don't duplicate.

- [ ] **Step 2: Install**

```bash
pip install "sentry-sdk[fastapi]>=2.0"
```

- [ ] **Step 3: Write test that Sentry init is skipped when DSN absent**

Add to `tests/test_health.py`:
```python
def test_health_no_crash_without_sentry_dsn():
    """Sentry DSN is optional — app must boot without it."""
    response = client.get("/health")
    assert response.status_code == 200
```

- [ ] **Step 4: Add Sentry init to main.py**

Add at the top of `src/footstats/api/main.py`, after `load_dotenv()`:

```python
import sentry_sdk

_sentry_dsn = os.environ.get("SENTRY_DSN", "")
if _sentry_dsn:
    sentry_sdk.init(
        dsn=_sentry_dsn,
        traces_sample_rate=0.1,
        environment=os.environ.get("ENV", "production"),
    )
```

- [ ] **Step 5: Run all Phase 1+2+3 tests**

```bash
python -m pytest tests/test_health.py tests/test_phase1.py tests/test_phase2.py -v
```
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/footstats/api/main.py tests/test_health.py
git commit -m "feat: add Sentry error tracking (no-op when SENTRY_DSN unset)"
```

---

## Task 3: FastAPI Dockerfile (API-only, no Playwright)

**Files:**
- Create: `Dockerfile.api`

The existing `Dockerfile` is for the Cloud Run daily agent (needs Playwright). The API server needs a slim image.

- [ ] **Step 1: Create Dockerfile.api**

```dockerfile
# Dockerfile.api — FastAPI server image (no Playwright)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY pyproject.toml ./
RUN uv pip install --system ".[api]"

COPY src ./src

EXPOSE 8000

CMD ["uvicorn", "footstats.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Build locally to verify**

```bash
cd F:/bot
docker build -f Dockerfile.api -t footstats-api:local .
```
Expected: image built, no errors

- [ ] **Step 3: Smoke test container**

```bash
docker run --rm -p 8000:8000 \
  -e SECRET_KEY="test-secret-key-32-chars-long!!" \
  -e ALLOWED_ORIGINS="http://localhost:5173" \
  footstats-api:local &
sleep 3
curl -f http://localhost:8000/health
docker stop $(docker ps -q --filter ancestor=footstats-api:local)
```
Expected: `{"status":"ok","version":"3.0"}`

- [ ] **Step 4: Commit**

```bash
git add Dockerfile.api
git commit -m "feat: add Dockerfile.api for slim FastAPI server image"
```

---

## Task 4: CI — Add Docker Build Verification

**Files:**
- Modify: `.github/workflows/ci.yml`

Add a Docker build step to existing CI so PRs catch broken images.

- [ ] **Step 1: Add Docker build job to ci.yml**

Append to `.github/workflows/ci.yml` after the `test` job:

```yaml
  docker-build:
    runs-on: ubuntu-latest
    needs: test
    steps:
      - uses: actions/checkout@v4

      - name: Build API Docker image
        run: docker build -f Dockerfile.api -t footstats-api:ci .

      - name: Verify health endpoint in container
        run: |
          docker run --rm -d -p 8000:8000 \
            -e SECRET_KEY="test-secret-key-32-chars-long!!" \
            -e ALLOWED_ORIGINS="http://localhost:3000" \
            --name footstats-ci footstats-api:ci
          sleep 5
          curl -f http://localhost:8000/health
          docker stop footstats-ci
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add Docker build + health smoke test to CI pipeline"
```

---

## Task 5: CD — Build + Push to GHCR + Deploy to Cloud Run

**Files:**
- Create: `.github/workflows/cd.yml`

**Prerequisites (manual, one-time, not in this plan):**
- GCP project with Cloud Run enabled
- `GCP_SA_KEY` (Service Account JSON) → GitHub repo secret
- `GHCR` is free with GitHub — no secret needed (uses `GITHUB_TOKEN`)
- `CLOUD_RUN_SERVICE` → GitHub repo secret (e.g. `footstats-api`)
- `GCP_REGION` → GitHub repo secret (e.g. `europe-west1`)
- `GCP_PROJECT` → GitHub repo secret
- `SECRET_KEY`, `SENTRY_DSN`, `ALLOWED_ORIGINS` → GitHub repo secrets (used as Cloud Run env vars)

- [ ] **Step 1: Create .github/workflows/cd.yml**

```yaml
name: CD — Deploy to Cloud Run

on:
  push:
    branches: [main]

env:
  IMAGE: ghcr.io/${{ github.repository_owner }}/footstats-api

jobs:
  deploy:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write

    steps:
      - uses: actions/checkout@v4

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push image
        uses: docker/build-push-action@v5
        with:
          context: .
          file: Dockerfile.api
          push: true
          tags: |
            ${{ env.IMAGE }}:latest
            ${{ env.IMAGE }}:${{ github.sha }}

      - name: Authenticate to GCP
        uses: google-github-actions/auth@v2
        with:
          credentials_json: ${{ secrets.GCP_SA_KEY }}

      - name: Deploy to Cloud Run
        uses: google-github-actions/deploy-cloudrun@v2
        with:
          service: ${{ secrets.CLOUD_RUN_SERVICE }}
          region: ${{ secrets.GCP_REGION }}
          image: ${{ env.IMAGE }}:${{ github.sha }}
          env_vars: |
            SECRET_KEY=${{ secrets.SECRET_KEY }}
            ALLOWED_ORIGINS=${{ secrets.ALLOWED_ORIGINS }}
            SENTRY_DSN=${{ secrets.SENTRY_DSN }}
            ENV=production

      - name: Verify deployment health
        run: |
          URL=$(gcloud run services describe ${{ secrets.CLOUD_RUN_SERVICE }} \
            --region ${{ secrets.GCP_REGION }} \
            --format 'value(status.url)')
          curl -f "$URL/health"
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/cd.yml
git commit -m "ci: add CD workflow — GHCR push + Cloud Run deploy on main"
```

> **Note:** CD will fail until GitHub repo secrets are configured. That's expected — the workflow is ready, secrets are the operator's task.

---

## Task 6: SQLite Backups to GCS

**Files:**
- Create: `scripts/backup_db.sh`
- Create: `.github/workflows/backup.yml`

- [ ] **Step 1: Create backup script**

```bash
# scripts/backup_db.sh
#!/usr/bin/env bash
set -euo pipefail

DB_PATH="${DB_PATH:-data/footstats_backtest.db}"
BUCKET="${BUCKET_NAME:?BUCKET_NAME env var required}"
TIMESTAMP=$(date -u +%Y%m%d_%H%M%S)
DEST="gs://${BUCKET}/backups/footstats_backtest_${TIMESTAMP}.db"
LATEST="gs://${BUCKET}/backups/footstats_backtest_latest.db"

echo "Backing up $DB_PATH → $DEST"
gcloud storage cp "$DB_PATH" "$DEST"
gcloud storage cp "$DB_PATH" "$LATEST"
echo "Backup complete: $DEST"
```

```bash
chmod +x scripts/backup_db.sh
```

- [ ] **Step 2: Create backup workflow**

```yaml
# .github/workflows/backup.yml
name: Daily DB Backup

on:
  schedule:
    - cron: '0 5 * * *'   # 05:00 UTC daily (07:00 Warsaw)
  workflow_dispatch:        # allow manual trigger

jobs:
  backup:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Authenticate to GCP
        uses: google-github-actions/auth@v2
        with:
          credentials_json: ${{ secrets.GCP_SA_KEY }}

      - name: Setup gcloud
        uses: google-github-actions/setup-gcloud@v2

      - name: Download current DB from Cloud Run volume / GCS
        run: |
          gcloud storage cp \
            gs://${{ secrets.BUCKET_NAME }}/data/footstats_backtest.db \
            data/footstats_backtest.db || echo "No existing DB in GCS, skipping download"

      - name: Run backup
        env:
          BUCKET_NAME: ${{ secrets.BUCKET_NAME }}
        run: bash scripts/backup_db.sh

      - name: Prune backups older than 30 days
        run: |
          CUTOFF=$(date -u -d '30 days ago' +%Y%m%d)
          gcloud storage ls gs://${{ secrets.BUCKET_NAME }}/backups/ \
            | grep "footstats_backtest_[0-9]" \
            | while read f; do
                FDATE=$(echo "$f" | grep -oP '\d{8}')
                if [[ "$FDATE" < "$CUTOFF" ]]; then
                  gcloud storage rm "$f"
                fi
              done
```

- [ ] **Step 3: Commit**

```bash
git add scripts/backup_db.sh .github/workflows/backup.yml
git commit -m "feat: daily SQLite→GCS backup workflow with 30-day retention"
```

---

## Task 7: Structured Logging

**Files:**
- Modify: `src/footstats/api/main.py`

Replace bare `logging` calls with structured JSON logging (for Cloud Run log sink + Sentry breadcrumbs).

- [ ] **Step 1: Add structured logging config**

Add to `src/footstats/api/main.py` after imports, before `app = FastAPI(...)`:

```python
import logging
import json

class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({
            "level": record.levelname,
            "msg": record.getMessage(),
            "logger": record.name,
            "time": self.formatTime(record),
        })

_handler = logging.StreamHandler()
_handler.setFormatter(_JsonFormatter())
logging.basicConfig(level=logging.INFO, handlers=[_handler], force=True)
```

- [ ] **Step 2: Verify health still passes**

```bash
python -m pytest tests/test_health.py tests/test_phase1.py tests/test_phase2.py -v
```
Expected: all pass

- [ ] **Step 3: Commit**

```bash
git add src/footstats/api/main.py
git commit -m "feat: structured JSON logging for Cloud Run + Sentry"
```

---

## Task 8: Final Integration Smoke Test

- [ ] **Step 1: Run full test suite for Phase 1+2+3**

```bash
python -m pytest tests/test_health.py tests/test_phase1.py tests/test_phase2.py -v --tb=short
```
Expected: all 31+ tests pass

- [ ] **Step 2: Build and smoke test Docker image**

```bash
docker build -f Dockerfile.api -t footstats-api:phase3 .
docker run --rm -p 8000:8000 \
  -e SECRET_KEY="test-secret-key-32-chars-long!!" \
  -e ALLOWED_ORIGINS="http://localhost:5173" \
  footstats-api:phase3 &
sleep 4
curl -sf http://localhost:8000/health | python -m json.tool
curl -sf http://localhost:8000/docs | grep -q "FootStats API"
docker stop $(docker ps -q --filter ancestor=footstats-api:phase3)
```
Expected: JSON health response, Swagger docs accessible

- [ ] **Step 3: Push to main**

```bash
git push origin main
```
Expected: CI passes (tests + Docker build). CD fails gracefully (secrets not configured yet — that's operator work).

---

## Operator Checklist (manual, after plan complete)

These are NOT automated by this plan — do once per environment:

1. Create GCS bucket: `gs://footstats-backups/`
2. Create GCP Service Account with roles: `Cloud Run Developer`, `Storage Object Admin`
3. Download SA key JSON
4. Add GitHub secrets: `GCP_SA_KEY`, `GCP_PROJECT`, `GCP_REGION`, `CLOUD_RUN_SERVICE`, `BUCKET_NAME`, `SECRET_KEY`, `ALLOWED_ORIGINS`, `SENTRY_DSN`
5. Create Sentry project → copy DSN → set `SENTRY_DSN` secret
6. Enable Cloud Run API in GCP console
7. First deploy may need manual `gcloud run deploy` once to create the service

---

## Self-Review

**Spec coverage:**
- ✅ CI/CD: Task 4 (CI Docker) + Task 5 (CD deploy)
- ✅ Monitoring: Task 2 (Sentry) + Task 7 (structured logging)
- ✅ Backups: Task 6 (GCS cron)
- ✅ Health endpoint: Task 1 (was missing from Phase 2)

**Gaps / notes:**
- PostgreSQL migration deferred to Phase 4 (major schema change, own plan needed)
- Sentry DSN setup is operator task — SDK integrates gracefully without it
- CD workflow won't fire successfully until secrets configured — this is by design
