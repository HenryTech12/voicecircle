from app.services import telnyx

from .conftest import API, make_circle


async def start_call(client, auth, data, difficulty="easy", scenario="grandchild_in_trouble"):
    r = await client.post(
        f"{API}/circles/{data['circle']['id']}/practice-calls",
        json={
            "senior_member_id": data["senior"]["id"], "voice_member_id": data["contact"]["id"],
            "scenario": scenario, "difficulty": difficulty,
        },
        headers=auth,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def get_call(client, auth, cid):
    r = await client.get(f"{API}/practice-calls/{cid}", headers=auth)
    assert r.status_code == 200
    return r.json()


async def say(client, auth, cid, text):
    r = await client.post(f"{API}/dev/calls/{cid}/say", json={"text": text}, headers=auth)
    assert r.status_code == 200, r.text


async def hangup(client, auth, cid):
    r = await client.post(f"{API}/dev/calls/{cid}/hangup", headers=auth)
    assert r.status_code == 200, r.text


async def test_scenarios(client, auth):
    r = await client.get(f"{API}/practice/scenarios", headers=auth)
    assert r.status_code == 200
    keys = {s["key"] for s in r.json()}
    assert {"grandchild_in_trouble", "car_accident_bail", "stuck_abroad"} <= keys
    assert r.json()[0]["difficulties"] == ["easy", "medium", "hard"]


async def test_call_connects_and_plays_cloned_opener(client, auth):
    data = await make_circle(client, auth)
    call = await start_call(client, auth, data)
    assert call["status"] == "queued"
    c = await get_call(client, auth, call["id"])
    assert c["status"] == "in_progress" and c["started_at"]
    assert c["transcript"][0]["speaker"] == "caller" and "Grandma Ada" in c["transcript"][0]["text"]
    ccid = next(iter(telnyx.MOCK_CALLS))
    actions = telnyx.MOCK_CALLS[ccid]["actions"]
    assert actions[0][0] == "playback" and "/api/v1/media/" in actions[0][1]  # cloned voice audio
    assert telnyx.MOCK_CALLS[ccid]["transcribing"] is True


async def test_hang_up_early_scores_100(client, auth):
    data = await make_circle(client, auth)
    call = await start_call(client, auth, data)
    await say(client, auth, call["id"], "Who is this? That doesn't sound right.")
    await hangup(client, auth, call["id"])
    c = await get_call(client, auth, call["id"])
    assert c["status"] == "completed"
    assert c["outcome"] == "hung_up_early" and c["score"] == 100
    assert c["feedback"]["hung_up_by_senior"] is True
    assert any(s["to"] == "+2348010000001" and "practice call" in s["text"] for s in telnyx.SENT_SMS)  # debrief
    alerts = (await client.get(f"{API}/circles/{data['circle']['id']}/alerts", headers=auth)).json()
    assert alerts == []


async def test_verification_question_scores_90(client, auth):
    data = await make_circle(client, auth)
    call = await start_call(client, auth, data, "medium")
    await say(client, auth, call["id"], "Oh dear, what happened?")
    await say(client, auth, call["id"], "Let me call your mother first and check.")
    await hangup(client, auth, call["id"])
    c = await get_call(client, auth, call["id"])
    assert c["outcome"] == "verified" and c["score"] == 90
    assert c["turns"] == 2
    assert [t["speaker"] for t in c["transcript"]][:4] == ["caller", "senior", "caller", "senior"]


async def test_complied_creates_urgent_alert_and_sms_to_family(client, auth):
    data = await make_circle(client, auth)
    call = await start_call(client, auth, data, "hard", "stuck_abroad")
    await say(client, auth, call["id"], "Oh no, are you okay?")
    await say(client, auth, call["id"], "How much do you need? I'll send it today.")
    await hangup(client, auth, call["id"])
    c = await get_call(client, auth, call["id"])
    assert c["outcome"] == "complied" and c["score"] == 0
    alerts = (await client.get(f"{API}/circles/{data['circle']['id']}/alerts", headers=auth)).json()
    assert alerts[0]["type"] == "scam_risk" and alerts[0]["severity"] == "urgent"
    assert any(s["to"] == "+2348010000002" for s in telnyx.SENT_SMS)  # trusted contact notified


async def test_hesitated_when_she_catches_on(client, auth):
    data = await make_circle(client, auth)
    call = await start_call(client, auth, data, "hard")
    await say(client, auth, call["id"], "Where do I send it?")
    await say(client, auth, call["id"], "Wait, no. This is a scam, I won't send anything.")
    await hangup(client, auth, call["id"])
    c = await get_call(client, auth, call["id"])
    assert c["outcome"] == "hesitated" and c["score"] == 50
    alerts = (await client.get(f"{API}/circles/{data['circle']['id']}/alerts", headers=auth)).json()
    assert alerts[0]["severity"] == "warning"


async def test_safety_stop_when_reading_digits(client, auth):
    data = await make_circle(client, auth)
    call = await start_call(client, auth, data, "easy")
    await say(client, auth, call["id"], "Okay the card number is 4111 2222 3333")
    c = await get_call(client, auth, call["id"])
    # disclosure played in neutral voice, then we hung up
    assert c["status"] == "completed"
    assert c["safety_stop"] is True and c["outcome"] == "complied"
    assert c["transcript"][-1]["speaker"] == "system" and "practice call" in c["transcript"][-1]["text"]
    ccid = next(iter(telnyx.MOCK_CALLS))
    assert ("speak", c["transcript"][-1]["text"]) in telnyx.MOCK_CALLS[ccid]["actions"]
    assert c["feedback"]["hung_up_by_senior"] is False
    # the digits were never stored
    assert "4111" not in str(c["transcript"]) and "[personal details removed]" in str(c["transcript"])


async def test_script_end_triggers_disclosure(client, auth):
    data = await make_circle(client, auth)
    call = await start_call(client, auth, data, "easy")
    for line in ["Hello?", "What?", "I don't understand", "Hmm", "Okay"]:
        r = await client.post(f"{API}/dev/calls/{call['id']}/say", json={"text": line}, headers=auth)
        if r.status_code == 409:
            break
    c = await get_call(client, auth, call["id"])
    assert c["status"] == "completed"
    assert c["transcript"][-1]["speaker"] == "system"


async def test_max_turns_limit(client, auth, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "PRACTICE_MAX_TURNS", 2)
    data = await make_circle(client, auth)
    call = await start_call(client, auth, data, "medium")
    await say(client, auth, call["id"], "Hello?")
    await say(client, auth, call["id"], "Who is it?")
    c = await get_call(client, auth, call["id"])
    assert c["status"] == "completed" and c["turns"] == 1


async def test_validation_errors(client, auth):
    data = await make_circle(client, auth, enroll=False)
    url = f"{API}/circles/{data['circle']['id']}/practice-calls"
    base = {"senior_member_id": data["senior"]["id"], "voice_member_id": data["contact"]["id"], "scenario": "grandchild_in_trouble", "difficulty": "easy"}
    r = await client.post(url, json=base, headers=auth)
    assert r.status_code == 400 and r.json()["error"]["code"] == "voice_not_enrolled"
    r = await client.post(url, json={**base, "scenario": "lottery"}, headers=auth)
    assert r.json()["error"]["code"] == "unknown_scenario"
    r = await client.post(url, json={**base, "difficulty": "extreme"}, headers=auth)
    assert r.status_code == 422
    r = await client.post(url, json={**base, "senior_member_id": data["contact"]["id"]}, headers=auth)
    assert r.json()["error"]["code"] == "invalid_senior"
    r = await client.post(url, json={**base, "voice_member_id": data["senior"]["id"]}, headers=auth)
    assert r.json()["error"]["code"] == "invalid_voice"


async def test_one_active_call_at_a_time(client, auth):
    data = await make_circle(client, auth)
    await start_call(client, auth, data)
    r = await client.post(
        f"{API}/circles/{data['circle']['id']}/practice-calls",
        json={"senior_member_id": data["senior"]["id"], "voice_member_id": data["contact"]["id"], "scenario": "grandchild_in_trouble", "difficulty": "hard"},
        headers=auth,
    )
    assert r.status_code == 409


async def test_cancel_call(client, auth):
    data = await make_circle(client, auth)
    call = await start_call(client, auth, data)
    r = await client.post(f"{API}/practice-calls/{call['id']}/cancel", headers=auth)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    ccid = next(iter(telnyx.MOCK_CALLS))
    assert telnyx.MOCK_CALLS[ccid]["hung_up"] is True
    r = await client.post(f"{API}/practice-calls/{call['id']}/cancel", headers=auth)
    assert r.status_code == 409


async def test_scheduled_call_is_not_started_immediately(client, auth):
    data = await make_circle(client, auth)
    r = await client.post(
        f"{API}/circles/{data['circle']['id']}/practice-calls",
        json={"senior_member_id": data["senior"]["id"], "voice_member_id": data["contact"]["id"], "scenario": "car_accident_bail",
              "difficulty": "medium", "scheduled_for": "2099-01-01T09:00:00Z"},
        headers=auth,
    )
    assert r.status_code == 201
    c = await get_call(client, auth, r.json()["id"])
    assert c["status"] == "queued" and telnyx.MOCK_CALLS == {}


async def test_list_and_access(client, auth, other_auth):
    data = await make_circle(client, auth)
    call = await start_call(client, auth, data)
    r = await client.get(f"{API}/circles/{data['circle']['id']}/practice-calls", headers=auth)
    assert r.status_code == 200 and [c["id"] for c in r.json()] == [call["id"]]
    assert (await client.get(f"{API}/practice-calls/{call['id']}", headers=other_auth)).status_code == 403
    assert (await client.get(f"{API}/circles/{data['circle']['id']}/practice-calls", headers=other_auth)).status_code == 403
    assert (await client.get(f"{API}/practice-calls/missing", headers=auth)).status_code == 404
    assert (await client.post(f"{API}/dev/calls/{call['id']}/say", json={"text": "hi"}, headers=other_auth)).status_code == 403


async def test_simulator_errors(client, auth, monkeypatch):
    data = await make_circle(client, auth)
    call = await start_call(client, auth, data)
    await hangup(client, auth, call["id"])
    r = await client.post(f"{API}/dev/calls/{call['id']}/say", json={"text": "hello"}, headers=auth)
    assert r.status_code == 409
    r = await client.post(f"{API}/dev/calls/{call['id']}/hangup", headers=auth)
    assert r.status_code == 409
    r = await client.post(f"{API}/dev/calls/unknown/hangup", headers=auth)
    assert r.status_code == 404
    r = await client.post(f"{API}/dev/calls/{call['id']}/say", json={"text": ""}, headers=auth)
    assert r.status_code == 422
    r = await client.get(f"{API}/dev/sms", headers=auth)
    assert r.status_code == 200 and len(r.json()["messages"]) >= 1
    from app.config import settings

    monkeypatch.setattr(settings, "MOCK_PROVIDERS", False)
    assert (await client.get(f"{API}/dev/sms", headers=auth)).status_code == 404


async def test_no_answer(client, auth):
    """If Telnyx reports hangup before answer, the call is no_answer."""
    from app.services import calls, events

    data = await make_circle(client, auth)
    # intercept dial so no answered event is emitted
    orig = telnyx.dial

    async def dial_no_answer(to, state):
        ccid = await orig(to, state)
        events._inline_queue.clear()
        telnyx.MOCK_CALLS[ccid]["hung_up"] = True
        events.emit(events.make_event("call.hangup", {"call_control_id": ccid, "client_state": telnyx.MOCK_CALLS[ccid]["client_state"]}))
        return ccid

    telnyx.dial = dial_no_answer
    try:
        call = await start_call(client, auth, data)
    finally:
        telnyx.dial = orig
    c = await get_call(client, auth, call["id"])
    assert c["status"] == "no_answer"
    assert calls.TERMINAL >= {"no_answer"}


async def test_dial_failure_marks_failed(client, auth, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("Telnyx rejected the number")

    monkeypatch.setattr(telnyx, "dial", boom)
    data = await make_circle(client, auth)
    call = await start_call(client, auth, data)
    c = await get_call(client, auth, call["id"])
    assert c["status"] == "failed" and "Telnyx rejected" in c["feedback"]["error"]


async def test_auto_senior_mode_runs_whole_call(client, auth, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "MOCK_AUTO_SENIOR", True)
    data = await make_circle(client, auth)
    call = await start_call(client, auth, data, "hard")
    c = await get_call(client, auth, call["id"])
    assert c["status"] == "completed"
    assert c["outcome"] == "hesitated"  # asks "how much", then "let me call your mother"


async def test_call_wraps_up_when_senior_stands_firm(client, auth):
    data = await make_circle(client, auth)
    call = await start_call(client, auth, data, "hard")
    await say(client, auth, call["id"], "Who is this really?")
    c = await get_call(client, auth, call["id"])
    assert c["status"] == "in_progress" and c["transcript"][-1]["speaker"] == "caller"  # one push-back: caller keeps pressing
    await say(client, auth, call["id"], "Let me call you back on your own number.")
    c = await get_call(client, auth, call["id"])
    assert c["status"] == "completed"
    assert c["outcome"] == "verified" and c["score"] == 90
    assert c["transcript"][-1]["speaker"] == "system" and "practice" in c["transcript"][-1]["text"].lower()


async def test_stood_firm_rule():
    from app.services.llm import stood_firm
    s = lambda *xs: [{"speaker": "senior", "text": x} for x in xs]  # noqa: E731
    assert stood_firm(s("No.", "I won't send anything."))
    assert not stood_firm(s("Who is this really?"))
    assert not stood_firm(s("How much do you need?", "No.", "I won't."))
