from .conftest import API, login, make_circle, wav_bytes


async def test_voice_prompts_default_and_personalised(client, auth):
    r = await client.get(f"{API}/voice/prompts", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert len(body["prompts"]) == 5 and body["consent_version"] == "v1" and "consent" not in body["prompts"][0].lower()
    data = await make_circle(client, auth, enroll=False)
    r = await client.get(f"{API}/voice/prompts", params={"circle_id": data["circle"]["id"]}, headers=auth)
    assert "Grandma Ada" in r.json()["prompts"][0]


async def test_voice_prompts_requires_auth(client):
    assert (await client.get(f"{API}/voice/prompts")).status_code == 401


async def test_enroll_voice_success(client, auth):
    data = await make_circle(client, auth, enroll=False)
    mid = data["contact"]["id"]
    r = await client.get(f"{API}/members/{mid}/voice", headers=auth)
    assert r.json()["status"] == "none"
    r = await client.post(
        f"{API}/members/{mid}/voice",
        files={"file": ("sample.wav", wav_bytes(), "audio/wav")},
        data={"consent": "true"},
        headers=auth,
    )
    assert r.status_code == 202 and r.json()["status"] == "processing"
    r = await client.get(f"{API}/members/{mid}/voice", headers=auth)
    assert r.json()["status"] == "enrolled" and r.json()["consent_at"]
    circle = (await client.get(f"{API}/circles/{data['circle']['id']}", headers=auth)).json()
    contact = next(m for m in circle["members"] if m["id"] == mid)
    assert contact["voice_status"] == "enrolled"


async def test_enroll_requires_consent(client, auth):
    data = await make_circle(client, auth, enroll=False)
    r = await client.post(
        f"{API}/members/{data['contact']['id']}/voice",
        files={"file": ("s.wav", wav_bytes(), "audio/wav")}, data={"consent": "false"}, headers=auth,
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "consent_required"
    r = await client.post(f"{API}/members/{data['contact']['id']}/voice", files={"file": ("s.wav", wav_bytes(), "audio/wav")}, headers=auth)
    assert r.status_code == 422


async def test_enroll_rejects_senior_and_bad_files(client, auth):
    data = await make_circle(client, auth, enroll=False)
    r = await client.post(
        f"{API}/members/{data['senior']['id']}/voice",
        files={"file": ("s.wav", wav_bytes(), "audio/wav")}, data={"consent": "true"}, headers=auth,
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "wrong_role"
    mid = data["contact"]["id"]
    r = await client.post(f"{API}/members/{mid}/voice", files={"file": ("notes.txt", b"hello", "text/plain")}, data={"consent": "true"}, headers=auth)
    assert r.status_code == 415
    r = await client.post(f"{API}/members/{mid}/voice", files={"file": ("empty.wav", b"", "audio/wav")}, data={"consent": "true"}, headers=auth)
    assert r.status_code == 400 and r.json()["error"]["code"] == "empty_file"


async def test_enroll_too_large(client, auth, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "MAX_UPLOAD_MB", 0)
    data = await make_circle(client, auth, enroll=False)
    r = await client.post(
        f"{API}/members/{data['contact']['id']}/voice",
        files={"file": ("s.wav", wav_bytes(), "audio/wav")}, data={"consent": "true"}, headers=auth,
    )
    assert r.status_code == 413


async def test_only_owner_of_voice_can_record(client, auth):
    data = await make_circle(client, auth, enroll=False)
    # a second family member joins the circle as their own linked member
    other = await login(client, "chioma@example.com")
    me_other = (await client.get(f"{API}/me", headers=other)).json()
    assert me_other["circles"] == []
    r = await client.post(
        f"{API}/members/{data['contact']['id']}/voice",
        files={"file": ("s.wav", wav_bytes(), "audio/wav")}, data={"consent": "true"}, headers=other,
    )
    assert r.status_code == 403


async def test_unlinked_contact_voice_can_be_enrolled_by_family(client, auth):
    data = await make_circle(client, auth, enroll=False)
    r = await client.post(
        f"{API}/circles/{data['circle']['id']}/members", json={"role": "trusted_contact", "display_name": "Chioma"}, headers=auth
    )
    mid = r.json()["id"]
    r = await client.post(
        f"{API}/members/{mid}/voice", files={"file": ("c.wav", wav_bytes("chioma"), "audio/wav")}, data={"consent": "true"}, headers=auth
    )
    assert r.status_code == 202


async def test_reenroll_replaces_and_delete_voice(client, auth):
    data = await make_circle(client, auth)
    mid = data["contact"]["id"]
    first = (await client.get(f"{API}/members/{mid}/voice", headers=auth)).json()["id"]
    r = await client.post(
        f"{API}/members/{mid}/voice", files={"file": ("s2.wav", wav_bytes("again"), "audio/wav")}, data={"consent": "true"}, headers=auth
    )
    assert r.status_code == 202 and r.json()["id"] != first
    r = await client.delete(f"{API}/members/{mid}/voice", headers=auth)
    assert r.status_code == 200
    assert (await client.get(f"{API}/members/{mid}/voice", headers=auth)).json()["status"] == "none"
    assert (await client.delete(f"{API}/members/{mid}/voice", headers=auth)).status_code == 404


async def test_enrollment_failure_is_reported(client, auth, monkeypatch):
    from app.services import resemble

    async def boom(*a, **k):
        raise resemble.ResembleError("plan does not allow API voice creation")

    monkeypatch.setattr(resemble, "create_voice", boom)
    data = await make_circle(client, auth, enroll=False)
    mid = data["contact"]["id"]
    await client.post(f"{API}/members/{mid}/voice", files={"file": ("s.wav", wav_bytes(), "audio/wav")}, data={"consent": "true"}, headers=auth)
    r = await client.get(f"{API}/members/{mid}/voice", headers=auth)
    assert r.json()["status"] == "failed" and "plan" in r.json()["error"]


async def test_webm_upload_is_converted(client, auth):
    import shutil
    import subprocess

    if not shutil.which("ffmpeg"):
        return
    wav = wav_bytes()
    webm = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "wav", "-i", "pipe:0", "-c:a", "libopus", "-f", "webm", "pipe:1"],
        input=wav, capture_output=True,
    ).stdout
    data = await make_circle(client, auth, enroll=False)
    r = await client.post(
        f"{API}/members/{data['contact']['id']}/voice",
        files={"file": ("rec.webm", webm, "audio/webm")}, data={"consent": "true"}, headers=auth,
    )
    assert r.status_code == 202
    assert (await client.get(f"{API}/members/{data['contact']['id']}/voice", headers=auth)).json()["status"] == "enrolled"
