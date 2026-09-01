"""CORS behaviour driven by the CORS_ORIGINS / CORS_ORIGIN_REGEX env vars.

main.py reads these once at import time into the CORSMiddleware config, so
exercising a specific value means rebuilding the app (see the `cors_app`
fixture in conftest.py), not just calling os.environ.setdefault.
"""
from fastapi.testclient import TestClient


def test_allowed_origin_gets_cors_header(cors_app):
    app = cors_app(cors_origins="https://allowed.example.com")
    with TestClient(app) as c:
        resp = c.get("/", headers={"Origin": "https://allowed.example.com"})
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "https://allowed.example.com"


def test_foreign_origin_gets_no_cors_header(cors_app):
    app = cors_app(cors_origins="https://allowed.example.com")
    with TestClient(app) as c:
        resp = c.get("/", headers={"Origin": "https://evil.example.com"})
    # Starlette doesn't reject the request outright (there's no way to for a
    # simple GET) -- it just omits the header, which is what stops the
    # browser from letting the calling page read the response.
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers


def test_default_origins_cover_localhost_dev(cors_app):
    # No CORS_ORIGINS set -> main.py's documented default.
    app = cors_app(cors_origins=None)
    with TestClient(app) as c:
        r1 = c.get("/", headers={"Origin": "http://localhost:3000"})
        r2 = c.get("/", headers={"Origin": "http://127.0.0.1:3000"})
        r3 = c.get("/", headers={"Origin": "https://an-unrelated-origin.example.com"})
    assert r1.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert r2.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"
    assert "access-control-allow-origin" not in r3.headers


def test_multiple_comma_separated_origins_all_allowed(cors_app):
    app = cors_app(cors_origins="https://a.example.com,https://b.example.com")
    with TestClient(app) as c:
        ra = c.get("/", headers={"Origin": "https://a.example.com"})
        rb = c.get("/", headers={"Origin": "https://b.example.com"})
        rc = c.get("/", headers={"Origin": "https://c.example.com"})
    assert ra.headers["access-control-allow-origin"] == "https://a.example.com"
    assert rb.headers["access-control-allow-origin"] == "https://b.example.com"
    assert "access-control-allow-origin" not in rc.headers


def test_cors_origin_regex_covers_preview_deploys(cors_app):
    app = cors_app(
        cors_origins="https://main.example.pages.dev",
        cors_origin_regex=r"https://.*\.example\.pages\.dev",
    )
    with TestClient(app) as c:
        preview = c.get("/", headers={"Origin": "https://a1b2c3d4.example.pages.dev"})
        unrelated = c.get("/", headers={"Origin": "https://evil-example.pages.dev.attacker.net"})
    assert preview.headers["access-control-allow-origin"] == "https://a1b2c3d4.example.pages.dev"
    assert "access-control-allow-origin" not in unrelated.headers


def test_preflight_request_for_match_endpoint(cors_app):
    app = cors_app(cors_origins="https://allowed.example.com")
    with TestClient(app) as c:
        resp = c.options(
            "/match",
            headers={
                "Origin": "https://allowed.example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "https://allowed.example.com"
    assert "POST" in resp.headers["access-control-allow-methods"]
