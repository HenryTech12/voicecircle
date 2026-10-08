"""CORS: the preflight for POST /auth/dev-login must pass for the configured frontend."""
import httpx
import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.cors import normalize_origin, parse_origins

VERCEL = "https://voicecircle.vercel.app"


@pytest.mark.parametrize(
    "raw",
    [
        "https://voicecircle.vercel.app",
        "https://voicecircle.vercel.app/",  # trailing slash (the usual cause of the 400)
        " https://VoiceCircle.vercel.app/login ",  # spaces, caps, path
        "voicecircle.vercel.app",  # no scheme
        '"https://voicecircle.vercel.app"',  # pasted with quotes
        "https://other.example.com, https://voicecircle.vercel.app/",
        "https://*.vercel.app",
        "https://voicecircle-*.vercel.app,https://voicecircle.vercel.app",
    ],
)
async def test_preflight_allowed(raw):
    app = _app(raw)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api") as c:
        r = await c.options("/api/v1/auth/dev-login", headers=_preflight(VERCEL))
        assert r.status_code == 200, (raw, r.text)
        assert r.headers["access-control-allow-origin"] == VERCEL
        r = await c.options("/api/v1/auth/dev-login", headers=_preflight("https://evil.example.com"))
        assert r.status_code == 400


async def test_wildcard_matches_preview_deploys_only():
    app = _app("https://voicecircle-*.vercel.app")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api") as c:
        ok = await c.options("/x", headers=_preflight("https://voicecircle-git-main-henrys-projects.vercel.app"))
        assert ok.status_code == 200
        bad = await c.options("/x", headers=_preflight("https://voicecircle-x.vercel.app.evil.com"))
        assert bad.status_code == 400


def test_parse_and_normalize():
    assert normalize_origin("localhost:5173") == "http://localhost:5173"
    assert parse_origins("*") == (["*"], None)
    assert parse_origins("") == ([], None)
    assert parse_origins("https://a.com/ https://a.com") == (["https://a.com"], None)


async def test_real_app_preflight(client):
    """The real app (FRONTEND_ORIGIN=http://localhost:5173 in tests) answers the dev-login preflight."""
    r = await client.options("/api/v1/auth/dev-login", headers=_preflight("http://localhost:5173"))
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == "http://localhost:5173"


def _preflight(origin):
    return {"Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}


def _app(raw):
    origins, regex = parse_origins(raw)
    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=origins or ([] if regex else ["*"]), allow_origin_regex=regex,
                       allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

    @app.post("/api/v1/auth/dev-login")
    def login():
        return {}

    @app.post("/x")
    def x():
        return {}

    return app
