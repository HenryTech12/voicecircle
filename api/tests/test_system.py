import base64
import json
import time
from datetime import datetime, timezone

from nacl.signing import SigningKey

from app.config import settings
from app.db import CircleMember, CompanionCall, PracticeCall, SessionLocal
from app.jobs import scheduler_tick
from app.services import storage, telnyx

from .conftest import API, make_circle


# ------------------------------------------------------------------ webhooks


def _signed(body: bytes, key: SigningKey, ts: int | None = None):
    ts = str(ts or int(time.time()))
    sig = key.sign(f"{ts}|".encode() + body).signature
    return {"telnyx-signature-ed25519": base64.b64encode(sig).decode(), "telnyx-timestamp": ts, "content-type": "application/json"}


async def test_webhook_signature_required_in_live_mode(client, monkeypatch):
    key = SigningKey.generate()
    monkeypatch.setattr(settings, "MOCK_PROVIDERS", False)
    monkeypatch.setattr(settings, "TELNYX_PUBLIC_KEY", base64.b64encode(bytes(key.verify_key)).decode())
    body = json.dumps({"data": {"id": "evt-1", "event_type": "call.initiated", "payload": {}}}).encode()
    r = await client.post(f"{API}/webhooks/telnyx", content=body, headers={"content-type": "application/json"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_signature"
    wrong = SigningKey.generate()
    r = await client.post(f"{API}/webhooks/telnyx", content=body, headers=_signed(body, wrong))
    assert r.status_code == 401
    r = await client.post(f"{API}/webhooks/telnyx", content=body, headers=_signed(body, key, ts=int(time.time()) - 3600))
    assert r.status_code == 401  # replay protection
    r = await client.post(f"{API}/webhooks/telnyx", content=body, headers=_signed(body, key))
    assert r.status_code == 200 and r.json() == {"received": True}


async def test_webhook_bad_payloads(client):
    r = await client.post(f"{API}/webhooks/telnyx", content=b"not json", headers={"content-type": "application/json"})
    assert r.status_code == 400
    r = await client.post(f"{API}/webhooks/telnyx", json={"hello": 1})
    assert r.status_code == 400


async def test_webhook_drives_call_and_is_idempotent(client, auth):
    """Simulate real Telnyx webhooks hitting the endpoint for a practice call."""
    data = await make_circle(client, auth)
    r = await client.post(
        f"{API}/circles/{data['circle']['id']}/practice-calls",
        json={"senior_member_id": data["senior"]["id"], "voice_member_id": data["contact"]["id"], "scenario": "grandchild_in_trouble", "difficulty": "easy"},
        headers=auth,
    )
    call_id = r.json()["id"]
    ccid = next(iter(telnyx.MOCK_CALLS))
    state = telnyx.encode_state({"kind": "practice", "id": call_id})
    evt = {"data": {"id": "evt-say-1", "event_type": "call.transcription", "payload": {
        "call_control_id": ccid, "client_state": state,
        "transcription_data": {"transcript": "Who is this?", "is_final": True}}}}
    assert (await client.post(f"{API}/webhooks/telnyx", json=evt)).status_code == 200
    assert (await client.post(f"{API}/webhooks/telnyx", json=evt)).status_code == 200  # duplicate delivery
    c = (await client.get(f"{API}/practice-calls/{call_id}", headers=auth)).json()
    assert [t["text"] for t in c["transcript"]].count("Who is this?") == 1
    # interim transcripts are ignored
    interim = {"data": {"id": "evt-say-2", "event_type": "call.transcription", "payload": {
        "call_control_id": ccid, "transcription_data": {"transcript": "Who", "is_final": False}}}}
    await client.post(f"{API}/webhooks/telnyx", json=interim)
    # hangup routed by call_control_id only (no client_state)
    hang = {"data": {"id": "evt-hang", "event_type": "call.hangup", "payload": {"call_control_id": ccid}}}
    await client.post(f"{API}/webhooks/telnyx", json=hang)
    c = (await client.get(f"{API}/practice-calls/{call_id}", headers=auth)).json()
    assert c["status"] == "completed" and c["outcome"] == "hung_up_early"
    assert "Who" not in [t["text"] for t in c["transcript"]]


async def test_webhook_unknown_call_is_ignored(client):
    evt = {"data": {"id": "evt-x", "event_type": "call.answered", "payload": {"call_control_id": "unknown"}}}
    assert (await client.post(f"{API}/webhooks/telnyx", json=evt)).status_code == 200


async def test_ai_assistant_history_event(client, auth):
    data = await make_circle(client, auth, enroll=False)
    r = await client.post(f"{API}/members/{data['senior']['id']}/companion-calls", headers=auth)
    cid = r.json()["id"]
    ccid = next(iter(telnyx.MOCK_CALLS))
    evt = {"data": {"id": "evt-hist", "event_type": "call.ai_gather.message_history_updated", "payload": {
        "call_control_id": ccid, "message_history": [
            {"role": "assistant", "content": "Hello Ada, it's Hugh."},
            {"role": "user", "content": "Hello Hugh, I'm well and I baked a cake."},
            {"role": "system", "content": "ignored"}]}}}
    await client.post(f"{API}/webhooks/telnyx", json=evt)
    c = (await client.get(f"{API}/companion-calls/{cid}", headers=auth)).json()
    assert [t["speaker"] for t in c["transcript"]] == ["hugh", "senior"]


# ------------------------------------------------------------------ media


async def test_media_signed_urls(client):
    path = await storage.save("call-audio", b"RIFFdata", "wav")
    url = await storage.signed_url(path)
    token = url.rsplit("/", 1)[1]
    r = await client.get(f"{API}/media/{token}")
    assert r.status_code == 200 and r.content == b"RIFFdata" and r.headers["content-type"] == "audio/wav"
    assert (await client.get(f"{API}/media/not-a-token")).status_code == 403
    await storage.delete(path)
    assert (await client.get(f"{API}/media/{token}")).status_code == 404


# ------------------------------------------------------------------ demo


async def test_demo_seed_and_reset(client, auth):
    r = await client.post(f"{API}/demo/seed", headers=auth)
    assert r.status_code == 200
    c = r.json()
    assert c["name"] == "Grandma Ada's Circle"
    roles = [m["role"] for m in c["members"]]
    assert roles.count("senior") == 1 and roles.count("trusted_contact") == 2
    assert c["stats"]["voices_enrolled"] == 1 and c["stats"]["open_alerts"] == 3 and c["stats"]["detections"] == 2
    senior = next(m for m in c["members"] if m["role"] == "senior")
    trends = (await client.get(f"{API}/members/{senior['id']}/companion-trends", headers=auth)).json()
    assert len(trends["points"]) == 14 and trends["flags"]
    assert trends["points"][-1]["wpm"] < trends["baseline"]["wpm"]
    pcs = (await client.get(f"{API}/circles/{c['id']}/practice-calls", headers=auth)).json()
    assert {p["outcome"] for p in pcs} == {"hung_up_early", "hesitated"}
    # seeded data still supports live (mock) features
    contact = next(m for m in c["members"] if m["voice_status"] == "enrolled")
    r = await client.post(
        f"{API}/circles/{c['id']}/practice-calls",
        json={"senior_member_id": senior["id"], "voice_member_id": contact["id"], "scenario": "car_accident_bail", "difficulty": "medium"},
        headers=auth,
    )
    assert r.status_code == 201
    r = await client.post(f"{API}/demo/reset", headers=auth)
    assert r.status_code == 200 and "1 circle" in r.json()["detail"]
    assert (await client.get(f"{API}/circles", headers=auth)).json() == []


async def test_demo_disabled(client, auth, monkeypatch):
    monkeypatch.setattr(settings, "DEMO_MODE", False)
    assert (await client.post(f"{API}/demo/seed", headers=auth)).status_code == 403
    assert (await client.post(f"{API}/demo/reset", headers=auth)).status_code == 403


# ------------------------------------------------------------------ scheduler


async def test_scheduler_starts_daily_companion_call_once(client, auth):
    data = await make_circle(client, auth, enroll=False)
    sid = data["senior"]["id"]
    await client.patch(f"{API}/members/{sid}", json={"companion_enabled": True, "companion_call_time": "09:00", "timezone": "Africa/Lagos"}, headers=auth)
    at_9_lagos = datetime(2026, 10, 9, 8, 0, 30, tzinfo=timezone.utc)  # 09:00 WAT
    started = await scheduler_tick(at_9_lagos)
    assert len(started["companion"]) == 1
    again = await scheduler_tick(at_9_lagos)
    assert again["companion"] == []
    wrong_time = await scheduler_tick(datetime(2026, 10, 9, 10, 0, tzinfo=timezone.utc))
    assert wrong_time["companion"] == []
    async with SessionLocal() as s:
        c = await s.get(CompanionCall, started["companion"][0])
        assert c.status in ("in_progress", "dialing")


async def test_scheduler_skips_disabled_seniors(client, auth):
    data = await make_circle(client, auth, enroll=False)
    async with SessionLocal() as s:
        m = await s.get(CircleMember, data["senior"]["id"])
        m.companion_call_time = "09:00"
        m.companion_enabled = False
        await s.commit()
    started = await scheduler_tick(datetime(2026, 10, 9, 8, 0, tzinfo=timezone.utc))
    assert started["companion"] == []


async def test_scheduler_starts_due_practice_calls(client, auth):
    data = await make_circle(client, auth)
    r = await client.post(
        f"{API}/circles/{data['circle']['id']}/practice-calls",
        json={"senior_member_id": data["senior"]["id"], "voice_member_id": data["contact"]["id"], "scenario": "stuck_abroad",
              "difficulty": "easy", "scheduled_for": "2026-10-09T10:00:00Z"},
        headers=auth,
    )
    pid = r.json()["id"]
    early = await scheduler_tick(datetime(2026, 10, 9, 9, 0, tzinfo=timezone.utc))
    assert early["practice"] == []
    due = await scheduler_tick(datetime(2026, 10, 9, 10, 1, tzinfo=timezone.utc))
    assert due["practice"] == [pid]
    async with SessionLocal() as s:
        assert (await s.get(PracticeCall, pid)).status == "in_progress"


# ------------------------------------------------------------------ openapi


async def test_openapi_lists_every_endpoint(client):
    spec = (await client.get("/openapi.json")).json()
    paths = spec["paths"]
    expected = [
        "/api/v1/health", "/api/v1/auth/config", "/api/v1/auth/dev-login", "/api/v1/me", "/api/v1/circles",
        "/api/v1/circles/{circle_id}", "/api/v1/circles/{circle_id}/members", "/api/v1/members/{member_id}",
        "/api/v1/voice/prompts", "/api/v1/members/{member_id}/voice", "/api/v1/practice/scenarios",
        "/api/v1/circles/{circle_id}/practice-calls", "/api/v1/practice-calls/{call_id}",
        "/api/v1/practice-calls/{call_id}/cancel", "/api/v1/circles/{circle_id}/detections",
        "/api/v1/detections/{detection_id}", "/api/v1/members/{member_id}/companion-calls",
        "/api/v1/companion-calls/{call_id}", "/api/v1/members/{member_id}/companion-trends",
        "/api/v1/circles/{circle_id}/alerts", "/api/v1/alerts/{alert_id}/ack", "/api/v1/webhooks/telnyx",
        "/api/v1/dev/calls/{call_id}/say", "/api/v1/dev/calls/{call_id}/hangup", "/api/v1/dev/sms",
        "/api/v1/demo/seed", "/api/v1/demo/reset",
    ]
    for p in expected:
        assert p in paths, p
