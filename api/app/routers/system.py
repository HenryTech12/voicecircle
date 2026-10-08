"""Twilio webhooks, signed media, mock call simulator and demo data."""
import logging
import random
from datetime import timedelta

import jwt
from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import (
    Alert, Circle, CircleMember, CompanionCall, DetectionCheck, PracticeCall, User, VoiceProfile, get_session, utcnow,
)
from ..deps import ensure_member, get_current_user
from ..errors import APIError, not_found
from ..schemas import OkOut, SimSayIn
from ..services import calls, events, metrics, scenarios, storage, twilio
from .core import _delete_circle_data, circle_out
from ..schemas import CircleOut

log = logging.getLogger("voicecircle.system")
router = APIRouter()


# ---------------------------------------------------------------- webhooks


def _public_url(request: Request) -> str:
    """The exact URL Twilio called (behind Render's proxy request.url is http://internal)."""
    q = request.url.query
    return settings.PUBLIC_BASE_URL.rstrip("/") + request.url.path + (f"?{q}" if q else "")


async def _twilio_params(request: Request) -> dict[str, str] | Response:
    form = await request.form()
    params = {k: str(v) for k, v in form.items()}
    sig = request.headers.get("x-twilio-signature")
    if not settings.MOCK_PROVIDERS or sig:
        if not twilio.verify_signature(_public_url(request), params, sig):
            return JSONResponse(status_code=403, content={"error": {"code": "invalid_signature", "message": "Invalid Twilio signature"}})
    return params


def _xml(body: str) -> Response:
    return Response(content=body, media_type="application/xml")


async def _run_turn(sid: str, state: str, etype: str, extra: dict, silence: int = 0) -> Response:
    """Feed one event to the call engine and return its actions as TwiML."""
    payload = {"call_control_id": sid, "client_state": state, **extra}
    with twilio.twiml_context(sid) as ctx:
        await calls.handle_event(events.make_event(etype, payload))
        # Twilio plays audio and moves on by itself: tell the engine it finished speaking so it
        # decides whether to listen (<Gather>) or hang up.
        for _ in range(3):
            if not twilio.needs_followup(ctx["verbs"]):
                break
            await calls.handle_event(events.make_event("call.speak.ended", payload))
        verbs = list(ctx["verbs"])
    if not verbs:
        verbs = [("hangup",)] if etype == "call.answered" else [("gather",)]
    return _xml(twilio.render_twiml(verbs, twilio.webhook_url("gather", state, silence=silence)))


@router.post("/webhooks/twilio/voice", tags=["webhooks"])
async def twilio_voice(request: Request, state: str = ""):
    """Twilio fetches this when the senior answers. Returns the opening TwiML."""
    params = await _twilio_params(request)
    if isinstance(params, Response):
        return params
    sid = params.get("CallSid", "")
    if not sid:
        return JSONResponse(status_code=400, content={"error": {"code": "bad_payload", "message": "Missing CallSid"}})
    return await _run_turn(sid, state, "call.answered", {"answered_by": params.get("AnsweredBy")})


@router.post("/webhooks/twilio/gather", tags=["webhooks"])
async def twilio_gather(request: Request, state: str = "", silence: int = 0):
    """Twilio posts the senior's speech (SpeechResult) here after each <Gather>."""
    params = await _twilio_params(request)
    if isinstance(params, Response):
        return params
    sid = params.get("CallSid", "")
    text = (params.get("SpeechResult") or "").strip()
    if not text:
        silence += 1
        if silence >= settings.TWILIO_MAX_SILENCES:
            return await _run_turn(sid, state, "call.silence", {}, silence=0)
        return _xml(twilio.render_twiml([("gather",)], twilio.webhook_url("gather", state, silence=silence)))
    try:
        confidence = float(params.get("Confidence") or 0)
    except ValueError:
        confidence = 0.0
    return await _run_turn(
        sid, state, "call.transcription",
        {"transcription_data": {"transcript": text, "is_final": True, "confidence": confidence}},
    )


@router.post("/webhooks/twilio/status", tags=["webhooks"])
async def twilio_status(request: Request, state: str = ""):
    """Twilio's status callback: fires once when the call ends (completed, busy, no-answer, failed, canceled)."""
    params = await _twilio_params(request)
    if isinstance(params, Response):
        return params
    sid, status = params.get("CallSid", ""), params.get("CallStatus", "")
    if sid and status in twilio.FINAL_STATUSES:
        event = events.make_event("call.hangup", {"call_control_id": sid, "client_state": state, "call_status": status})
        event["data"]["id"] = f"{sid}:final"  # idempotent if Twilio retries
        await calls.handle_event(event)
    return _xml(twilio.empty_twiml())


# ---------------------------------------------------------------- media


@router.get("/media/{token}", tags=["media"], include_in_schema=False)
async def media(token: str):
    try:
        path = storage.resolve_media_token(token)
    except (jwt.PyJWTError, ValueError, KeyError):
        raise APIError(403, "invalid_media_token", "This media link is invalid or expired")
    if not path.exists():
        raise not_found("File")
    media_type = "audio/wav" if path.suffix == ".wav" else None
    return FileResponse(path, media_type=media_type)


# ---------------------------------------------------------------- mock call simulator


async def _find_call(session: AsyncSession, call_id: str, user: User):
    call = await session.get(PracticeCall, call_id) or await session.get(CompanionCall, call_id)
    if not call:
        raise not_found("Call")
    await ensure_member(session, call.circle_id, user)
    if not call.provider_call_id:
        raise APIError(409, "not_connected", "The call hasn't connected yet")
    return call


def _require_mock():
    if not settings.MOCK_PROVIDERS:
        raise APIError(404, "not_found", "Simulator is only available in mock mode")


@router.post("/dev/calls/{call_id}/say", response_model=OkOut, tags=["simulator"])
async def sim_say(call_id: str, body: SimSayIn, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    """Mock mode: pretend the senior said something on the call."""
    _require_mock()
    text = body.text.strip()
    call = await _find_call(session, call_id, user)
    if not twilio.mock_say(call.provider_call_id, text):
        raise APIError(409, "call_ended", "This call has ended")
    await events.flush()
    return OkOut()


@router.post("/dev/calls/{call_id}/hangup", response_model=OkOut, tags=["simulator"])
async def sim_hangup(call_id: str, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    """Mock mode: pretend the senior hung up."""
    _require_mock()
    call = await _find_call(session, call_id, user)
    if not twilio.mock_hangup_by_senior(call.provider_call_id):
        raise APIError(409, "call_ended", "This call has ended")
    await events.flush()
    return OkOut()


@router.get("/dev/sms", tags=["simulator"])
async def sim_sms(user: User = Depends(get_current_user)):
    """Mock mode: SMS messages that would have been sent."""
    _require_mock()
    return {"messages": twilio.SENT_SMS[-50:]}


# ---------------------------------------------------------------- demo data

SUMMARIES = [
    "Ada watered her tomato plants and spoke with her neighbour Bisi.",
    "She made jollof rice and watched the evening news.",
    "Ada went to church and enjoyed the choir.",
    "She baked a coconut cake for her grandson's visit.",
    "Ada knitted a scarf and listened to the radio.",
    "She walked to the market and bought fresh peppers.",
    "Ada talked about her late husband's garden.",
    "She called her sister in Ibadan.",
    "Ada read the newspaper and did a crossword.",
    "She had visitors from church in the afternoon.",
    "Ada said she felt tired and stayed in.",
    "She wasn't sure what she did yesterday.",
    "Ada talked about the cake again, the same as before.",
    "She said she felt a little low and forgot breakfast.",
]


def _demo_transcript(i: int, slow: bool) -> list[dict]:
    gap = 4200 if slow else 2600
    lines = [
        {"speaker": "hugh", "text": "Hello Ada, it's Hugh. How are you feeling today?", "t_ms": 3000},
        {"speaker": "senior", "text": ("Um... I'm... fine, I think." if slow else "I'm doing well, thank you Hugh."), "t_ms": 3000 + gap},
        {"speaker": "hugh", "text": "What have you been up to today?", "t_ms": 9000 + gap},
        {"speaker": "senior", "text": SUMMARIES[i], "t_ms": 9000 + gap * 2 + 2000},
    ]
    return lines


@router.post("/demo/seed", response_model=CircleOut, tags=["demo"])
async def demo_seed(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    """Create a fully populated demo circle for the current user (DEMO_MODE only)."""
    if not settings.DEMO_MODE:
        raise APIError(403, "disabled", "Demo mode is off")
    now = utcnow()
    rng = random.Random(42)
    circle = Circle(name="Grandma Ada's Circle", owner_id=user.id)
    session.add(circle)
    await session.flush()
    ada = CircleMember(
        circle_id=circle.id, role="senior", display_name="Grandma Ada", relationship_label="grandmother",
        phone_e164="+2348010000001", timezone="Africa/Lagos", companion_call_time="09:00", companion_enabled=True,
        personal_facts=["your cat Biscuit", "the trip to Calabar"],
    )
    alex = CircleMember(
        circle_id=circle.id, user_id=user.id, role="trusted_contact",
        display_name=user.full_name or "Alex", relationship_label="grandson", phone_e164="+2348010000002",
        personal_facts=["your cat Biscuit"],
    )
    chioma = CircleMember(
        circle_id=circle.id, role="trusted_contact", display_name="Chioma", relationship_label="daughter",
        phone_e164="+2348010000003",
    )
    session.add_all([ada, alex, chioma])
    await session.flush()
    session.add(
        VoiceProfile(
            member_id=alex.id, status="enrolled", resemble_voice_uuid="mock-voice-demo",
            resemble_identity_id="mock-identity-demo", consent_text_version="v1", consent_at=now - timedelta(days=15),
        )
    )
    name = alex.display_name
    easy_open = scenarios.opener("grandchild_in_trouble", "easy", "Grandma Ada", name, [])
    hard_lines = [scenarios.scripted_line("stuck_abroad", "hard", i, "Grandma Ada", name, ["your cat Biscuit"]) for i in range(4)]
    easy = PracticeCall(
        circle_id=circle.id, senior_member_id=ada.id, voice_member_id=alex.id, scenario="grandchild_in_trouble",
        difficulty="easy", status="completed", outcome="hung_up_early", score=100, turns=1, created_by=user.id,
        transcript=[
            {"speaker": "caller", "text": easy_open, "t_ms": 0},
            {"speaker": "senior", "text": "Who is this? My grandson doesn't talk like that.", "t_ms": 6000},
        ],
        feedback={"did_well": ["You didn't give in to the pressure."], "practice_next": ["Keep it up: a secret family code word makes checking even easier."], "hung_up_by_senior": True},
        duration_seconds=14, started_at=now - timedelta(days=2, minutes=5), ended_at=now - timedelta(days=2, minutes=4, seconds=46),
        created_at=now - timedelta(days=2, minutes=6),
    )
    hard = PracticeCall(
        circle_id=circle.id, senior_member_id=ada.id, voice_member_id=alex.id, scenario="stuck_abroad",
        difficulty="hard", status="completed", outcome="hesitated", score=50, turns=4, created_by=user.id,
        transcript=[
            {"speaker": "caller", "text": hard_lines[0], "t_ms": 0},
            {"speaker": "senior", "text": "Oh my goodness, are you alright? Where are you?", "t_ms": 7000},
            {"speaker": "caller", "text": hard_lines[1], "t_ms": 9000},
            {"speaker": "senior", "text": "How much do you need? Where do I send it?", "t_ms": 17000},
            {"speaker": "caller", "text": hard_lines[3], "t_ms": 19000},
            {"speaker": "senior", "text": "Wait. Let me call your mother first to check.", "t_ms": 27000},
            {"speaker": "system", "text": scenarios.DISCLOSURE.format(contact=name), "t_ms": 29000},
        ],
        feedback={
            "did_well": ["You asked to check who was really calling. That is the best move."],
            "practice_next": ["When someone asks for money urgently, hang up and call them back on a number you know."],
            "hung_up_by_senior": False,
        },
        duration_seconds=41, started_at=now - timedelta(days=1, hours=3), ended_at=now - timedelta(days=1, hours=3) + timedelta(seconds=41),
        created_at=now - timedelta(days=1, hours=3, minutes=1),
    )
    session.add_all([easy, hard])
    await session.flush()
    session.add_all([
        DetectionCheck(
            circle_id=circle.id, claimed_member_id=alex.id, original_filename="voicemail_from_alex.m4a", status="done",
            synthetic_score=0.07, speaker_match_score=0.91, verdict="real",
            explanation=f"This looks like a real voice, and it matches {name}'s voice sample. If you're ever unsure, hang up and call them back on a number you already know.",
            created_by=user.id, created_at=now - timedelta(days=3),
        ),
        DetectionCheck(
            circle_id=circle.id, claimed_member_id=alex.id, original_filename="strange_call_recording.wav", status="done",
            synthetic_score=0.93, speaker_match_score=0.62, verdict="fake",
            explanation=f"This voice was most likely made by a computer. It is probably not really {name}. If you're ever unsure, hang up and call them back on a number you already know.",
            created_by=user.id, created_at=now - timedelta(hours=20),
        ),
    ])
    history: list[dict] = []
    last_call = None
    for i in range(14):
        day = now - timedelta(days=13 - i, hours=1)
        changed = i >= 10
        m = {
            "wpm": round((84 if changed else 118) + rng.uniform(-5, 5), 1),
            "latency_ms": round((2150 if changed else 1200) + rng.uniform(-120, 120)),
            "filler_rate": round((5.2 if changed else 2.0) + rng.uniform(-0.4, 0.4), 1),
            "senior_words": rng.randint(70, 140),
            "recall": "none" if i >= 12 else ("partial" if changed else "correct"),
            "mood": "low" if i >= 11 else ("neutral" if i % 4 == 0 else "positive"),
            "repetition": i >= 12,
        }
        base = metrics.baseline(history)
        flags = metrics.flags_for(m, base, history)
        last_call = CompanionCall(
            circle_id=circle.id, senior_member_id=ada.id, status="completed",
            recall_question=llm_recall(SUMMARIES[i - 1] if i else None), transcript=_demo_transcript(i, changed),
            summary=SUMMARIES[i], metrics=m, flags=flags, turns=2,
            duration_seconds=rng.randint(150, 280), started_at=day, ended_at=day + timedelta(minutes=4), created_at=day,
        )
        session.add(last_call)
        history.append(m)
    await session.flush()
    session.add_all([
        Alert(
            circle_id=circle.id, type="scam_risk", severity="warning",
            title="Grandma Ada nearly went along with a practice scam",
            message="On a hard practice call, Grandma Ada engaged with the money request before stopping. More practice and a family code word can help.",
            source_id=hard.id, created_at=now - timedelta(days=1, hours=3),
        ),
        Alert(
            circle_id=circle.id, type="detection_fake", severity="urgent",
            title=f"A recording claiming to be {name} looks fake",
            message="Someone may be impersonating a family member. Please talk to your loved one and agree a family code word.",
            created_at=now - timedelta(hours=20),
        ),
        Alert(
            circle_id=circle.id, type="wellbeing_change", severity="warning",
            title="Hugh noticed a change in Grandma Ada's calls",
            message=metrics.describe(last_call.flags or ["slower_speech", "longer_pauses"], "Grandma Ada"),
            source_id=last_call.id, created_at=now - timedelta(hours=1),
        ),
    ])
    await session.commit()
    return await circle_out(session, circle)


def llm_recall(prev: str | None) -> str:
    from ..services import llm

    return llm.recall_question_for(prev)


@router.post("/demo/reset", response_model=OkOut, tags=["demo"])
async def demo_reset(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    """Delete every circle owned by the current user (DEMO_MODE only)."""
    if not settings.DEMO_MODE:
        raise APIError(403, "disabled", "Demo mode is off")
    circles = (await session.execute(select(Circle).where(Circle.owner_id == user.id))).scalars().all()
    for c in circles:
        await _delete_circle_data(session, c)
    await session.commit()
    return OkOut(detail=f"Deleted {len(circles)} circle(s)")
