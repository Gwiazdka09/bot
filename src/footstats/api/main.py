"""FootStats API — app factory with auth, CORS, and rate limiting."""
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

load_dotenv()

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
