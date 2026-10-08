from datetime import datetime, timedelta, timezone

from app.db import CompanionCall, SessionLocal
from app.services import twilio

from .conftest import API, make_circle


async def call_hugh(client, auth, sid):
    r = await client.post(f"{API}/members/{sid}/companion-calls", headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


async def say(client, auth, cid, text):
    r = await client.post(f"{API}/dev/calls/{cid}/say", json={"text": text}, headers=auth)
    assert r.status_code == 200, r.text


async def get(client, auth, cid):
    r = await client.get(f"{API}/companion-calls/{cid}", headers=auth)
    assert r.status_code == 200
    return r.json()


async def full_conversation(client, auth, sid):
    c = await call_hugh(client, auth, sid)
    await say(client, auth, c["id"], "Oh hello Hugh, I'm doing fine, thank you.")
    await say(client, auth, c["id"], "I made some rice and watered my lovely plants this morning.")
    await say(client, auth, c["id"], "I had bread and tea with a boiled egg for breakfast today.")
    return await get(client, auth, c["id"])


async def test_companion_call_full_flow(client, auth):
    data = await make_circle(client, auth, enroll=False)
    c = await full_conversation(client, auth, data["senior"]["id"])
    assert c["status"] == "completed"
    speakers = [t["speaker"] for t in c["transcript"]]
    assert speakers[0] == "hugh" and "senior" in speakers and speakers[-1] == "hugh"
    assert "Goodbye" in c["transcript"][-1]["text"]
    assert c["summary"] and c["metrics"]["senior_words"] > 10
    assert c["metrics"]["mood"] == "positive"
    assert c["metrics"]["recall"] == "correct"
    assert c["recall_question"] == "What did you have for breakfast this morning?"
    assert c["flags"] == []  # no baseline yet


async def test_recall_question_uses_previous_summary(client, auth):
    data = await make_circle(client, auth, enroll=False)
    sid = data["senior"]["id"]
    await full_conversation(client, auth, sid)
    c2 = await call_hugh(client, auth, sid)
    c2 = await get(client, auth, c2["id"])
    assert c2["recall_question"].startswith("Last time we spoke")


async def test_hugh_only_calls_senior_and_one_at_a_time(client, auth):
    data = await make_circle(client, auth, enroll=False)
    r = await client.post(f"{API}/members/{data['contact']['id']}/companion-calls", headers=auth)
    assert r.status_code == 400 and r.json()["error"]["code"] == "wrong_role"
    await call_hugh(client, auth, data["senior"]["id"])
    r = await client.post(f"{API}/members/{data['senior']['id']}/companion-calls", headers=auth)
    assert r.status_code == 409


async def test_list_companion_calls_and_access(client, auth, other_auth):
    data = await make_circle(client, auth, enroll=False)
    sid = data["senior"]["id"]
    c = await full_conversation(client, auth, sid)
    r = await client.get(f"{API}/members/{sid}/companion-calls", headers=auth)
    assert r.status_code == 200 and r.json()[0]["id"] == c["id"]
    assert (await client.get(f"{API}/members/{sid}/companion-calls", headers=other_auth)).status_code == 403
    assert (await client.get(f"{API}/companion-calls/{c['id']}", headers=other_auth)).status_code == 403
    assert (await client.get(f"{API}/companion-calls/missing", headers=auth)).status_code == 404
    assert (await client.get(f"{API}/members/{sid}/companion-calls?limit=0", headers=auth)).status_code == 422


async def _seed_history(circle_id, sid, n=7):
    async with SessionLocal() as s:
        for i in range(n):
            day = datetime.now(timezone.utc) - timedelta(days=n - i)
            s.add(CompanionCall(
                circle_id=circle_id, senior_member_id=sid, status="completed", transcript=[], flags=[],
                summary=f"Day {i}", metrics={"wpm": 120.0, "latency_ms": 900, "filler_rate": 1.0, "recall": "correct", "mood": "positive"},
                started_at=day, ended_at=day + timedelta(minutes=3), created_at=day,
            ))
        await s.commit()


async def test_change_from_baseline_raises_wellbeing_alert(client, auth):
    data = await make_circle(client, auth, enroll=False)
    sid, cid = data["senior"]["id"], data["circle"]["id"]
    await _seed_history(cid, sid)
    # slow, hesitant answers: very long gaps relative to words
    c = await call_hugh(client, auth, sid)
    ccid = next(iter(twilio.MOCK_CALLS))
    from app.services import calls

    async with SessionLocal() as s:  # pretend the call started 2 minutes ago -> long response gaps
        row = await s.get(CompanionCall, c["id"])
        row.started_at = row.started_at - timedelta(minutes=2)
        row.transcript = [{**row.transcript[0], "t_ms": 0}]
        await s.commit()
    await say(client, auth, c["id"], "Um... I... um, fine.")
    await say(client, auth, c["id"], "I don't remember, erm...")
    await say(client, auth, c["id"], "Um... I don't know.")
    c = await get(client, auth, c["id"])
    assert c["status"] == "completed", ccid
    assert "slower_speech" in c["flags"]
    alerts = (await client.get(f"{API}/circles/{cid}/alerts", headers=auth)).json()
    w = [a for a in alerts if a["type"] == "wellbeing_change"]
    assert w and "Hugh noticed Grandma Ada" in w[0]["message"]
    assert "dementia" not in w[0]["message"].lower()
    assert calls is not None


async def test_trends(client, auth, other_auth):
    data = await make_circle(client, auth, enroll=False)
    sid, cid = data["senior"]["id"], data["circle"]["id"]
    await _seed_history(cid, sid, 5)
    r = await client.get(f"{API}/members/{sid}/companion-trends", params={"days": 14}, headers=auth)
    assert r.status_code == 200
    t = r.json()
    assert len(t["points"]) == 5 and t["baseline"]["wpm"] == 120.0 and t["points"][0]["recall"] == "correct"
    r = await client.get(f"{API}/members/{sid}/companion-trends", params={"days": 2}, headers=auth)
    assert len(r.json()["points"]) <= 2
    assert (await client.get(f"{API}/members/{sid}/companion-trends", headers=other_auth)).status_code == 403
    assert (await client.get(f"{API}/members/{sid}/companion-trends?days=500", headers=auth)).status_code == 422


async def test_alerts_list_filter_and_ack(client, auth, other_auth):
    data = await make_circle(client, auth)
    cid = data["circle"]["id"]
    await client.post(
        f"{API}/circles/{cid}/detections",
        files={"file": ("fake.wav", b"RIFF1234", "audio/wav")}, data={"claimed_member_id": data["contact"]["id"]}, headers=auth,
    )
    alerts = (await client.get(f"{API}/circles/{cid}/alerts", headers=auth)).json()
    assert len(alerts) == 1 and alerts[0]["acknowledged_at"] is None
    aid = alerts[0]["id"]
    assert (await client.post(f"{API}/alerts/{aid}/ack", headers=other_auth)).status_code == 403
    r = await client.post(f"{API}/alerts/{aid}/ack", headers=auth)
    assert r.status_code == 200 and r.json()["acknowledged_at"]
    again = await client.post(f"{API}/alerts/{aid}/ack", headers=auth)
    assert again.json()["acknowledged_at"] == r.json()["acknowledged_at"]  # idempotent
    open_only = await client.get(f"{API}/circles/{cid}/alerts", params={"include_acknowledged": "false"}, headers=auth)
    assert open_only.json() == []
    assert (await client.post(f"{API}/alerts/missing/ack", headers=auth)).status_code == 404
    assert (await client.get(f"{API}/circles/{cid}/alerts", headers=other_auth)).status_code == 403
    circle = (await client.get(f"{API}/circles/{cid}", headers=auth)).json()
    assert circle["stats"]["open_alerts"] == 0 and circle["stats"]["detections"] == 1
