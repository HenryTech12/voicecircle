from datetime import datetime, timezone

import pytest

from app.config import settings
from app.db import CircleMember, CompanionCall, PracticeCall, SessionLocal
from app.jobs import scheduler_tick
from app.services import calls, storage, twilio

from .conftest import API, make_circle

TOKEN = "test-auth-token"


# ------------------------------------------------------------------ Twilio webhooks


def _signed_post(client, url: str, params: dict, token: str = TOKEN):
    sig = twilio.compute_signature(url, params, token)
    return client.post(url, data=params, headers={"X-Twilio-Signature": sig})


@pytest.fixture
def live(monkeypatch):
    """Live (non-mock) Twilio mode with the REST API faked out."""
    sent: list[tuple[str, object]] = []
    sids = iter(f"CAlive{i:026d}" for i in range(1, 100))

    async def fake_post(path, data):
        sent.append((path, data))
        if path == "/Calls.json":
            return {"sid": next(sids)}
        return {"sid": "SMfake"}

    async def fake_tts(text, voice_uuid):
        return f"http://test/api/v1/media/fake-{abs(hash(text)) % 10000}.wav"

    class Live:
        def __init__(self):
            self.sent = sent

        def on(self):
            """Switch to live mode (call after setting up the circle in mock mode)."""
            monkeypatch.setattr(settings, "MOCK_PROVIDERS", False)
            monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", TOKEN)
            monkeypatch.setattr(settings, "TWILIO_ACCOUNT_SID", "ACtest")
            monkeypatch.setattr(settings, "TWILIO_FROM_NUMBER", "+15005550006")
            monkeypatch.setattr(twilio, "_post", fake_post)
            monkeypatch.setattr(calls, "_tts_url", fake_tts)
            return self

    return Live()


def test_signature_algorithm_matches_twilio_docs_example():
    # Worked example from https://www.twilio.com/docs/usage/security
    url = "https://example.com/myapp.php?foo=1&bar=2"
    params = {"Digits": "1234", "To": "+18005551212", "From": "+14158675310", "Caller": "+14158675310", "CallSid": "CA1234567890ABCDE"}
    assert twilio.compute_signature(url, params, "12345") == "L/OH5YylLD5NRKLltdqwSvS0BnU="


async def test_webhook_signature_required_in_live_mode(client, monkeypatch):
    monkeypatch.setattr(settings, "MOCK_PROVIDERS", False)
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", TOKEN)
    url = twilio.webhook_url("voice", twilio.encode_state({"kind": "practice", "id": "nope"}))
    params = {"CallSid": "CAx", "CallStatus": "in-progress"}
    r = await client.post(url, data=params)
    assert r.status_code == 403 and r.json()["error"]["code"] == "invalid_signature"
    r = await _signed_post(client, url, params, token="wrong-token")
    assert r.status_code == 403
    r = await client.post(url, data={**params, "CallStatus": "tampered"}, headers={"X-Twilio-Signature": twilio.compute_signature(url, params, TOKEN)})
    assert r.status_code == 403  # body changed after signing
    r = await _signed_post(client, url, params)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    assert "<Hangup/>" in r.text  # unknown call: just hang up


async def test_webhook_missing_callsid(client):
    r = await client.post(f"{API}/webhooks/twilio/voice", data={})
    assert r.status_code == 400


async def test_live_practice_call_end_to_end(client, auth, live):
    data = await make_circle(client, auth)
    live.on()
    r = await client.post(
        f"{API}/circles/{data['circle']['id']}/practice-calls",
        json={"senior_member_id": data["senior"]["id"], "voice_member_id": data["contact"]["id"], "scenario": "grandchild_in_trouble", "difficulty": "easy"},
        headers=auth,
    )
    call_id = r.json()["id"]
    # 1. we asked Twilio to dial with our webhook URLs
    path, form = live.sent[0]
    form = dict(form)
    assert path == "/Calls.json" and form["To"] == "+2348010000001" and form["From"] == "+15005550006"
    assert form["Url"].startswith("http://test/api/v1/webhooks/twilio/voice?state=")
    assert form["StatusCallback"].startswith("http://test/api/v1/webhooks/twilio/status?state=")
    c = (await client.get(f"{API}/practice-calls/{call_id}", headers=auth)).json()
    assert c["status"] == "dialing"
    sid = "CAlive" + "1".zfill(26)
    voice_url, status_url = form["Url"], form["StatusCallback"]

    # 2. senior answers -> cloned opener plays, then we listen
    r = await _signed_post(client, voice_url, {"CallSid": sid, "CallStatus": "in-progress"})
    assert r.status_code == 200
    assert "<Play>http://test/api/v1/media/fake-" in r.text
    assert '<Gather input="speech"' in r.text and "webhooks/twilio/gather?state=" in r.text
    # the prompt is nested inside the <Gather> so the senior can answer without waiting (barge-in)
    assert r.text.index("<Gather") < r.text.index("<Play>") < r.text.index("</Gather>")
    gather_url = r.text.split('action="')[1].split('"')[0].replace("&amp;", "&")
    c = (await client.get(f"{API}/practice-calls/{call_id}", headers=auth)).json()
    assert c["status"] == "in_progress" and c["transcript"][0]["speaker"] == "caller"

    # 3. silence -> just listen again
    r = await _signed_post(client, gather_url, {"CallSid": sid, "SpeechResult": ""})
    assert "<Gather" in r.text and "silence=1" in r.text and "<Play>" not in r.text

    # 4. senior asks who it is -> caller presses on in the cloned voice
    r = await _signed_post(client, gather_url, {"CallSid": sid, "SpeechResult": "Who is this really?", "Confidence": "0.91"})
    assert "<Play>" in r.text and "<Gather" in r.text and "<Hangup/>" not in r.text

    # 5. senior stands firm -> neutral-voice disclosure, then hang up
    r = await _signed_post(client, gather_url, {"CallSid": sid, "SpeechResult": "Let me call you back on your own number."})
    assert "<Say" in r.text and "practice call" in r.text and r.text.rstrip().endswith("<Hangup/></Response>")
    assert "<Gather" not in r.text and "<Play>" not in r.text

    # 6. status callback (twice: Twilio may retry) finalises the call once
    for _ in range(2):
        r = await _signed_post(client, status_url, {"CallSid": sid, "CallStatus": "completed", "CallDuration": "42"})
        assert r.status_code == 200
    c = (await client.get(f"{API}/practice-calls/{call_id}", headers=auth)).json()
    assert c["status"] == "completed" and c["outcome"] == "verified" and c["score"] == 90
    sms = [d for p, d in live.sent if p == "/Messages.json"]
    assert len(sms) == 1 and sms[0]["To"] == "+2348010000001" and "practice call" in sms[0]["Body"]
    assert sms[0]["From"] == "+15005550006"


async def test_live_safety_stop_and_no_digits_stored(client, auth, live):
    data = await make_circle(client, auth)
    live.on()
    r = await client.post(
        f"{API}/circles/{data['circle']['id']}/practice-calls",
        json={"senior_member_id": data["senior"]["id"], "voice_member_id": data["contact"]["id"], "scenario": "stuck_abroad", "difficulty": "hard"},
        headers=auth,
    )
    call_id = r.json()["id"]
    form = dict(live.sent[0][1])
    sid = "CAlive" + "1".zfill(26)
    r = await _signed_post(client, form["Url"], {"CallSid": sid})
    gather_url = r.text.split('action="')[1].split('"')[0].replace("&amp;", "&")
    r = await _signed_post(client, gather_url, {"CallSid": sid, "SpeechResult": "my card number is 4111 1111 1111 1111"})
    assert "<Say" in r.text and "<Hangup/>" in r.text
    c = (await client.get(f"{API}/practice-calls/{call_id}", headers=auth)).json()
    assert c["safety_stop"] is True and "4111" not in str(c["transcript"])


async def test_live_repeated_silence_wraps_up(client, auth, live, monkeypatch):
    monkeypatch.setattr(settings, "TWILIO_MAX_SILENCES", 2)
    data = await make_circle(client, auth, enroll=False)
    live.on()
    r = await client.post(f"{API}/members/{data['senior']['id']}/companion-calls", headers=auth)
    cid = r.json()["id"]
    form = dict(live.sent[0][1])
    sid = "CAlive" + "1".zfill(26)
    r = await _signed_post(client, form["Url"], {"CallSid": sid})
    assert "<Say" in r.text and "Hugh" in r.text and "<Gather" in r.text  # Hugh greets with Twilio <Say>
    gather_url = r.text.split('action="')[1].split('"')[0].replace("&amp;", "&")
    r = await _signed_post(client, gather_url, {"CallSid": sid, "SpeechResult": ""})
    gather_url = r.text.split('action="')[1].split('"')[0].replace("&amp;", "&")
    assert "silence=1" in gather_url
    r = await _signed_post(client, gather_url, {"CallSid": sid, "SpeechResult": ""})
    assert "call again tomorrow" in r.text and "<Hangup/>" in r.text
    r = await _signed_post(client, form["StatusCallback"], {"CallSid": sid, "CallStatus": "completed"})
    c = (await client.get(f"{API}/companion-calls/{cid}", headers=auth)).json()
    assert c["status"] == "completed"


async def test_live_no_answer_status(client, auth, live):
    data = await make_circle(client, auth)
    live.on()
    r = await client.post(
        f"{API}/circles/{data['circle']['id']}/practice-calls",
        json={"senior_member_id": data["senior"]["id"], "voice_member_id": data["contact"]["id"], "scenario": "grandchild_in_trouble", "difficulty": "easy"},
        headers=auth,
    )
    call_id = r.json()["id"]
    form = dict(live.sent[0][1])
    r = await _signed_post(client, form["StatusCallback"], {"CallSid": "CAlive" + "1".zfill(26), "CallStatus": "no-answer"})
    assert r.status_code == 200
    c = (await client.get(f"{API}/practice-calls/{call_id}", headers=auth)).json()
    assert c["status"] == "no_answer"
    # non-final statuses are ignored
    r = await _signed_post(client, form["StatusCallback"], {"CallSid": "CAother", "CallStatus": "ringing"})
    assert r.status_code == 200


async def test_live_cancel_hangs_up_via_rest(client, auth, live):
    data = await make_circle(client, auth)
    live.on()
    r = await client.post(
        f"{API}/circles/{data['circle']['id']}/practice-calls",
        json={"senior_member_id": data["senior"]["id"], "voice_member_id": data["contact"]["id"], "scenario": "grandchild_in_trouble", "difficulty": "easy"},
        headers=auth,
    )
    r = await client.post(f"{API}/practice-calls/{r.json()['id']}/cancel", headers=auth)
    assert r.json()["status"] == "cancelled"
    sid = "CAlive" + "1".zfill(26)
    assert (f"/Calls/{sid}.json", {"Status": "completed"}) in live.sent


async def test_live_sms_uses_messaging_service_when_set(live, monkeypatch):
    live.on()
    monkeypatch.setattr(settings, "TWILIO_MESSAGING_SERVICE_SID", "MGabc")
    assert await twilio.send_sms("+2348000000000", "hi") is True
    assert live.sent[-1] == ("/Messages.json", {"To": "+2348000000000", "Body": "hi", "MessagingServiceSid": "MGabc"})
    assert await twilio.send_sms(None, "hi") is False


def test_twiml_rendering_escapes_text():
    xml = twilio.render_twiml([("say", "Tom & Jerry <3"), ("gather",)], "http://x/g?state=a&silence=0")
    assert "Tom &amp; Jerry &lt;3" in xml and 'action="http://x/g?state=a&amp;silence=0"' in xml
    assert twilio.render_twiml([("play", "http://a/b.wav")], "http://x/g").count("<Gather") == 1  # listen by default
    assert twilio.render_twiml([("hangup",), ("say", "never")], "").endswith("<Hangup/></Response>")


async def test_mock_webhook_events_still_drive_call(client, auth):
    """Mock mode: engine events from the simulator are idempotent."""
    from app.services import events
    data = await make_circle(client, auth)
    r = await client.post(
        f"{API}/circles/{data['circle']['id']}/practice-calls",
        json={"senior_member_id": data["senior"]["id"], "voice_member_id": data["contact"]["id"], "scenario": "grandchild_in_trouble", "difficulty": "easy"},
        headers=auth,
    )
    call_id = r.json()["id"]
    sid = next(iter(twilio.MOCK_CALLS))
    evt = events.make_event("call.transcription", {"call_control_id": sid, "transcription_data": {"transcript": "Who is this?", "is_final": True}})
    await calls.handle_event(evt)
    await calls.handle_event(evt)  # duplicate delivery
    c = (await client.get(f"{API}/practice-calls/{call_id}", headers=auth)).json()
    assert [t["text"] for t in c["transcript"]].count("Who is this?") == 1
    interim = events.make_event("call.transcription", {"call_control_id": sid, "transcription_data": {"transcript": "Who", "is_final": False}})
    await calls.handle_event(interim)
    await calls.handle_event(events.make_event("call.hangup", {"call_control_id": sid}))
    c = (await client.get(f"{API}/practice-calls/{call_id}", headers=auth)).json()
    assert c["status"] == "completed" and c["outcome"] == "hung_up_early"
    assert "Who" not in [t["text"] for t in c["transcript"]]
    await calls.handle_event(events.make_event("call.answered", {"call_control_id": "unknown"}))  # ignored


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
    from datetime import timedelta

    base = (datetime.now(timezone.utc) + timedelta(days=2)).replace(hour=10, minute=0, second=0, microsecond=0)
    data = await make_circle(client, auth)
    r = await client.post(
        f"{API}/circles/{data['circle']['id']}/practice-calls",
        json={"senior_member_id": data["senior"]["id"], "voice_member_id": data["contact"]["id"], "scenario": "stuck_abroad",
              "difficulty": "easy", "scheduled_for": base.isoformat().replace("+00:00", "Z")},
        headers=auth,
    )
    pid = r.json()["id"]
    early = await scheduler_tick(base - timedelta(hours=1))
    assert early["practice"] == []
    due = await scheduler_tick(base + timedelta(minutes=1))
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
        "/api/v1/circles/{circle_id}/alerts", "/api/v1/alerts/{alert_id}/ack", "/api/v1/webhooks/twilio/voice", "/api/v1/webhooks/twilio/gather", "/api/v1/webhooks/twilio/status",
        "/api/v1/dev/calls/{call_id}/say", "/api/v1/dev/calls/{call_id}/hangup", "/api/v1/dev/sms",
        "/api/v1/demo/seed", "/api/v1/demo/reset",
    ]
    for p in expected:
        assert p in paths, p


async def test_init_db_adds_missing_columns_to_old_tables(tmp_path, monkeypatch):
    """A database created by an older schema must be upgraded in place, not 500 on missing columns."""
    import sqlite3

    from sqlalchemy.ext.asyncio import create_async_engine

    import app.db as db

    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE practice_calls (id VARCHAR(36) PRIMARY KEY, circle_id VARCHAR(36))")
    con.commit()
    con.close()

    eng = create_async_engine(f"sqlite+aiosqlite:///{path}")
    monkeypatch.setattr(db, "engine", eng)
    await db.init_db()
    await eng.dispose()

    cols = {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(practice_calls)")}
    assert {"provider_call_id", "outcome", "score", "engine_state"} <= cols


async def test_supabase_storage_creates_missing_bucket_and_retries(monkeypatch):
    import httpx

    from app.config import settings

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/bucket"):
            return httpx.Response(200, json={"name": "voice-samples"})
        if len([c for c in calls if "/object/" in c[1]]) == 1:
            return httpx.Response(400, json={"error": "Bucket not found", "statusCode": "404"})
        return httpx.Response(200, json={"Key": "ok"})

    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    monkeypatch.setattr(storage.httpx, "AsyncClient", lambda **kw: real(transport=transport, **kw))
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "supabase")
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "sb_secret_abc")

    path = await storage.save("voice-samples", b"RIFF", "wav")
    assert path.startswith("voice-samples/")
    assert ("POST", "/storage/v1/bucket") in calls
    assert storage._sb_headers() == {"apikey": "sb_secret_abc"}


async def test_twilio_post_encodes_repeated_form_keys(monkeypatch):
    import httpx

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content.decode()
        seen["ctype"] = request.headers["content-type"]
        return httpx.Response(201, json={"sid": "CA123"})

    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    monkeypatch.setattr(twilio.httpx, "AsyncClient", lambda **kw: real(transport=transport, **kw))
    out = await twilio._post("/Calls.json", [("To", "+2348012345678"), ("StatusCallbackEvent", "initiated"), ("StatusCallbackEvent", "completed")])
    assert out == {"sid": "CA123"}
    assert seen["body"].count("StatusCallbackEvent=") == 2
    assert seen["ctype"] == "application/x-www-form-urlencoded"


async def test_live_companion_call_is_a_back_and_forth_conversation(client, auth, live):
    data = await make_circle(client, auth)
    live.on()
    r = await client.post(f"{API}/members/{data['senior']['id']}/companion-calls", headers=auth)
    assert r.status_code == 201, r.text
    call_id = r.json()["id"]
    form = dict(live.sent[0][1])
    sid = "CAlive" + "7".zfill(26)

    r = await _signed_post(client, form["Url"], {"CallSid": sid, "CallStatus": "in-progress"})
    assert "<Say" in r.text and "<Gather" in r.text, r.text
    gather_url = r.text.split('action="')[1].split('"')[0].replace("&amp;", "&")

    # Three turns: each answer must get a spoken reply AND another Gather (until Hugh says goodbye).
    for said in ["I'm fine", "I had rice and stew", "Yes it was nice"]:
        r = await _signed_post(client, gather_url, {"CallSid": sid, "SpeechResult": said, "Confidence": "0.9"})
        assert r.status_code == 200, r.text
        assert "<Say" in r.text, f"Hugh did not reply to {said!r}: {r.text}"
        assert r.text.index("<Gather") < r.text.index("<Say") if "<Gather" in r.text else True
        assert "<Gather" in r.text or "<Hangup/>" in r.text
    c = (await client.get(f"{API}/companion-calls/{call_id}", headers=auth)).json()
    assert [t["speaker"] for t in c["transcript"]][:4] == ["hugh", "senior", "hugh", "senior"]


async def test_fish_audio_clone_and_speak(monkeypatch):
    import httpx

    from app.config import settings
    from app.services import fish, voices

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, dict(request.headers)))
        if request.url.path == "/model" and request.method == "POST":
            return httpx.Response(201, json={"_id": "voice123", "state": "trained"})
        if request.url.path == "/v1/tts":
            assert b'"reference_id":"voice123"' in request.content.replace(b" ", b"")
            return httpx.Response(200, content=b"RIFFaudio")
        return httpx.Response(200, json={})

    real = httpx.AsyncClient
    monkeypatch.setattr(fish.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(settings, "MOCK_PROVIDERS", False)
    monkeypatch.setattr(settings, "VOICE_PROVIDER", "fish")
    monkeypatch.setattr(settings, "FISH_API_KEY", "fk_test")

    vid = await voices.create_voice("VoiceCircle Ada", b"RIFFsample", "https://unused")
    assert vid == "voice123"
    assert await voices.synthesize("Hello Ada", vid) == b"RIFFaudio"
    tts = [h for m, p, h in seen if p == "/v1/tts"][0]
    assert tts["model"] == "s2.1-pro-free" and tts["authorization"] == "Bearer fk_test"
    await voices.delete_voice(vid)
    assert ("DELETE", "/model/voice123") in [(m, p) for m, p, _ in seen]


async def test_tts_never_uses_default_voice_without_a_clone(monkeypatch):
    from app.services import calls, voices

    async def must_not_run(*a, **k):
        raise AssertionError("synthesize must not be called without a cloned voice")

    monkeypatch.setattr(voices, "synthesize", must_not_run)
    assert await calls._tts_url("Hello", None) is None
