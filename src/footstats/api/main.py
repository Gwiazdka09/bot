"""FootStats API — app factory with auth, CORS, and rate limiting."""
import json
import logging
import os
from pathlib import Path

import sentry_sdk
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

load_dotenv()

_sentry_dsn = os.environ.get("SENTRY_DSN", "")
if _sentry_dsn and _sentry_dsn.startswith("https://"):
    sentry_sdk.init(
        dsn=_sentry_dsn,
        traces_sample_rate=0.1,
        environment=os.environ.get("ENV", "production"),
    )


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

from footstats.api.auth import router as auth_router
from footstats.api.routes.bankroll import router as bankroll_router
from footstats.api.routes.coupons import router as coupons_router
from footstats.api.routes.settings import router as settings_router
from footstats.api.routes.status import router as status_router

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])

app = FastAPI(title="FootStats API", version="2.0")

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

_raw_origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000")
_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(status_router)
app.include_router(bankroll_router)
app.include_router(settings_router)
app.include_router(coupons_router)


@app.get("/health", tags=["ops"])
def health() -> dict:
    from footstats import __version__
    return {"status": "ok", "version": __version__}


from fastapi_mcp import FastApiMCP as _FastApiMCP

_mcp = _FastApiMCP(app)
_mcp.mount_http()

_dist = Path(__file__).parent.parent / "gui" / "dist"

if _dist.exists():
    app.mount("/assets", StaticFiles(directory=str(_dist / "assets")), name="assets")

    @app.get("/")
    def root():
        return FileResponse(str(_dist / "index.html"), media_type="text/html")

    @app.get("/app")
    def serve_app():
        return FileResponse(str(_dist / "index.html"), media_type="text/html")
else:
    @app.get("/")
    def root():
        return RedirectResponse(url="/preview")

    @app.get("/preview")
    def serve_preview():
        html_path = Path(__file__).parent / "preview.html"
        return FileResponse(html_path, media_type="text/html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
