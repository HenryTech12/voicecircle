import os
import shutil
import tempfile

# Configure the app for tests BEFORE importing it.
_TMP = tempfile.mkdtemp(prefix="vc-test-")
os.environ.update(
    {
        "DATABASE_URL": f"sqlite+aiosqlite:///{_TMP}/test.db",
        "STORAGE_DIR": f"{_TMP}/storage",
        "MOCK_PROVIDERS": "true",
        "MOCK_EVENT_DELAY": "0",
        "MOCK_AUTO_SENIOR": "false",
        "AUTH_MODE": "local",
        "DEMO_MODE": "true",
        "SCHEDULER_ENABLED": "false",
        "PUBLIC_BASE_URL": "http://test",
    }
)

import httpx  # noqa: E402
import pytest  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services import audio, telnyx  # noqa: E402

API = "/api/v1"


@pytest.fixture(autouse=True)
async def fresh_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    telnyx.MOCK_CALLS.clear()
    telnyx.SENT_SMS.clear()
    shutil.rmtree(f"{_TMP}/storage", ignore_errors=True)
    yield


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def login(client, email="alex@example.com", name="Alex") -> dict:
    r = await client.post(f"{API}/auth/dev-login", json={"email": email, "full_name": name})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
async def auth(client):
    return await login(client)


@pytest.fixture
async def other_auth(client):
    return await login(client, "stranger@example.com", "Stranger")


def wav_bytes(seed: str = "real-voice") -> bytes:
    return audio.tone_wav(1.0, 220, seed)


async def make_circle(client, auth, enroll=True) -> dict:
    r = await client.post(f"{API}/circles", json={"name": "Grandma Ada's Circle", "my_phone_e164": "+2348010000002"}, headers=auth)
    assert r.status_code == 201, r.text
    circle = r.json()
    me = circle["members"][0]
    r = await client.post(
        f"{API}/circles/{circle['id']}/members",
        json={"role": "senior", "display_name": "Grandma Ada", "phone_e164": "+2348010000001", "relationship": "grandmother"},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    senior = r.json()
    if enroll:
        r = await client.post(
            f"{API}/members/{me['id']}/voice",
            files={"file": ("sample.wav", wav_bytes(), "audio/wav")},
            data={"consent": "true", "consent_version": "v1"},
            headers=auth,
        )
        assert r.status_code == 202, r.text
    return {"circle": circle, "senior": senior, "contact": me}
