import os
import bcrypt as _bcrypt

# Set test credentials before importing main (which calls load_dotenv).
# setdefault ensures real .env values are not overridden when running standalone,
# but guarantees a known hash is present before load_dotenv can set one.
os.environ["JWT_SECRET"] = os.environ.get("JWT_SECRET", "testsecret1234567890abcdef12345678")
os.environ["FOOTSTATS_USER"] = os.environ.get("FOOTSTATS_USER", "admin")
os.environ["ALLOWED_ORIGINS"] = os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173")
if "FOOTSTATS_PASSWORD_HASH" not in os.environ:
    os.environ["FOOTSTATS_PASSWORD_HASH"] = _bcrypt.hashpw(b"testpass", _bcrypt.gensalt()).decode()

import pytest
from fastapi.testclient import TestClient
from footstats.api.main import app

client = TestClient(app, raise_server_exceptions=False)


def test_spa_root_returns_html():
    """GET / serves index.html from dist/."""
    resp = client.get("/", follow_redirects=True)
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_spa_assets_served():
    """Static JS asset from dist/assets/ is accessible."""
    dist = "src/footstats/gui/dist/assets"
    if not os.path.exists(dist):
        pytest.skip("dist/ not built yet")
    asset = next((f for f in os.listdir(dist) if f.endswith(".js")), None)
    if asset is None:
        pytest.skip("no JS assets in dist/")
    resp = client.get(f"/assets/{asset}")
    assert resp.status_code == 200


def test_mcp_endpoint_exists():
    """/mcp endpoint present — not 404 (SSE route, checked via route registry)."""
    from footstats.api.main import app as _app

    mcp_paths = [r.path for r in _app.routes if "mcp" in getattr(r, "path", "")]
    assert "/mcp" in mcp_paths, f"No /mcp route found. Routes: {mcp_paths}"


def test_mcp_post_tools_list():
    """MCP tools/list POST endpoint exists and is reachable."""
    resp = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        headers={"Content-Type": "application/json"},
    )
    # 200, 400, or 422 means the endpoint exists; 404 means it doesn't
    assert resp.status_code != 404
