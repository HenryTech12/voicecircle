from app.routers.detection import decide
from app.services import storage, telnyx

from .conftest import API, make_circle, wav_bytes


async def upload(client, auth, data, filename="voicemail.wav", content=None, member=None):
    r = await client.post(
        f"{API}/circles/{data['circle']['id']}/detections",
        files={"file": (filename, content or wav_bytes(filename), "audio/wav")},
        data={"claimed_member_id": member or data["contact"]["id"]},
        headers=auth,
    )
    return r


async def result(client, auth, did):
    r = await client.get(f"{API}/detections/{did}", headers=auth)
    assert r.status_code == 200
    return r.json()


async def test_real_voice(client, auth):
    data = await make_circle(client, auth)
    r = await upload(client, auth, data)
    assert r.status_code == 202 and r.json()["status"] == "processing"
    d = await result(client, auth, r.json()["id"])
    assert d["status"] == "done" and d["verdict"] == "real"
    assert d["synthetic_score"] < 0.5 and d["speaker_match_score"] > 0.75
    assert "call them back" in d["explanation"] and d["claimed_member_name"] == "Alex"
    alerts = (await client.get(f"{API}/circles/{data['circle']['id']}/alerts", headers=auth)).json()
    assert alerts == []


async def test_fake_voice_creates_alert(client, auth):
    data = await make_circle(client, auth)
    r = await upload(client, auth, data, "deepfake_call.wav")
    d = await result(client, auth, r.json()["id"])
    assert d["verdict"] == "fake" and d["synthetic_score"] > 0.6
    alerts = (await client.get(f"{API}/circles/{data['circle']['id']}/alerts", headers=auth)).json()
    assert alerts[0]["type"] == "detection_fake" and alerts[0]["severity"] == "urgent"


async def test_clone_from_practice_call_is_detected_as_fake(client, auth):
    data = await make_circle(client, auth)
    r = await client.post(
        f"{API}/circles/{data['circle']['id']}/practice-calls",
        json={"senior_member_id": data["senior"]["id"], "voice_member_id": data["contact"]["id"], "scenario": "grandchild_in_trouble", "difficulty": "easy"},
        headers=auth,
    )
    assert r.status_code == 201
    # grab the cloned opener audio that was played into the call
    ccid = next(iter(telnyx.MOCK_CALLS))
    url = telnyx.MOCK_CALLS[ccid]["actions"][0][1]
    clone_bytes = storage.resolve_media_token(url.rsplit("/", 1)[1]).read_bytes()
    r = await upload(client, auth, data, "recording_from_phone.wav", content=clone_bytes)
    assert (await result(client, auth, r.json()["id"]))["verdict"] == "fake"


async def test_not_them(client, auth):
    data = await make_circle(client, auth)
    r = await upload(client, auth, data, "stranger_voice.wav")
    d = await result(client, auth, r.json()["id"])
    assert d["verdict"] == "not_them"


async def test_unsure_and_no_reference(client, auth):
    data = await make_circle(client, auth)
    r = await upload(client, auth, data, "unsure_clip.wav")
    assert (await result(client, auth, r.json()["id"]))["verdict"] == "unsure"
    # Chioma has no enrolled voice -> cannot compare -> unsure
    m = await client.post(f"{API}/circles/{data['circle']['id']}/members", json={"role": "trusted_contact", "display_name": "Chioma"}, headers=auth)
    r = await upload(client, auth, data, "call.wav", member=m.json()["id"])
    d = await result(client, auth, r.json()["id"])
    assert d["verdict"] == "unsure" and d["speaker_match_score"] is None


async def test_detection_validation(client, auth, other_auth):
    data = await make_circle(client, auth)
    r = await client.post(
        f"{API}/circles/{data['circle']['id']}/detections",
        files={"file": ("doc.pdf", b"%PDF", "application/pdf")}, data={"claimed_member_id": data["contact"]["id"]}, headers=auth,
    )
    assert r.status_code == 415
    r = await upload(client, auth, data, member="nope")
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_member"
    r = await upload(client, other_auth, data)
    assert r.status_code == 403
    r = await client.post(f"{API}/circles/{data['circle']['id']}/detections", data={"claimed_member_id": data["contact"]["id"]}, headers=auth)
    assert r.status_code == 422


async def test_list_get_and_access(client, auth, other_auth):
    data = await make_circle(client, auth)
    a = (await upload(client, auth, data, "one.wav")).json()["id"]
    b = (await upload(client, auth, data, "fake_two.wav")).json()["id"]
    r = await client.get(f"{API}/circles/{data['circle']['id']}/detections", headers=auth)
    assert r.status_code == 200 and {d["id"] for d in r.json()} == {a, b}
    assert all(d["claimed_member_name"] == "Alex" for d in r.json())
    assert (await client.get(f"{API}/detections/{a}", headers=other_auth)).status_code == 403
    assert (await client.get(f"{API}/detections/missing", headers=auth)).status_code == 404
    assert (await client.get(f"{API}/circles/{data['circle']['id']}/detections", headers=other_auth)).status_code == 403


async def test_detection_provider_failure(client, auth, monkeypatch):
    from app.services import resemble

    async def boom(*a, **k):
        raise resemble.ResembleError("detect timed out")

    monkeypatch.setattr(resemble, "detect_synthetic", boom)
    data = await make_circle(client, auth)
    r = await upload(client, auth, data)
    d = await result(client, auth, r.json()["id"])
    assert d["status"] == "failed" and d["error"]


def test_decide_matrix():
    assert decide(0.9, 0.9, "Alex")[0] == "fake"
    assert decide(0.5, 0.9, "Alex")[0] == "unsure"
    assert decide(0.1, 0.9, "Alex")[0] == "real"
    assert decide(0.1, 0.2, "Alex")[0] == "not_them"
    assert decide(0.1, 0.65, "Alex")[0] == "unsure"
    assert decide(0.1, None, "Alex")[0] == "unsure"
    for v in decide(0.9, 0.9, "Alex"), decide(0.1, 0.9, "Alex"):
        assert "Alex" in v[1]
