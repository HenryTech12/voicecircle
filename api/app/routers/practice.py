"""Scam Training: practice calls."""
from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import CircleMember, PracticeCall, User, get_session, utcnow
from ..deps import ensure_member, get_current_user
from ..errors import APIError, bad_request, not_found
from ..schemas import PracticeCallIn, PracticeCallOut, ScenarioOut
from ..services import calls, notify, scenarios, twilio

router = APIRouter(tags=["practice"])


@router.get("/practice/scenarios", response_model=list[ScenarioOut])
async def list_scenarios(user: User = Depends(get_current_user)):
    return [
        ScenarioOut(key=k, title=v["title"], description=v["description"], difficulties=scenarios.DIFFICULTIES)
        for k, v in scenarios.SCENARIOS.items()
    ]


@router.post("/circles/{circle_id}/practice-calls", response_model=PracticeCallOut, status_code=201)
async def create_practice_call(
    circle_id: str, body: PracticeCallIn, background: BackgroundTasks,
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session),
):
    await ensure_member(session, circle_id, user)
    if body.scenario not in scenarios.SCENARIOS:
        raise bad_request("Unknown scenario", "unknown_scenario")
    senior = await session.get(CircleMember, body.senior_member_id)
    contact = await session.get(CircleMember, body.voice_member_id)
    if not senior or senior.circle_id != circle_id or senior.role != "senior":
        raise bad_request("Pick the senior from this circle", "invalid_senior")
    if not contact or contact.circle_id != circle_id or contact.role != "trusted_contact":
        raise bad_request("Pick a trusted contact from this circle", "invalid_voice")
    if not contact.voice or contact.voice.status != "enrolled":
        raise bad_request(f"{contact.display_name}'s voice isn't enrolled yet", "voice_not_enrolled")
    if not senior.phone_e164:
        raise bad_request("The senior needs a phone number", "phone_required")
    active = (
        await session.execute(
            select(PracticeCall.id).where(
                PracticeCall.senior_member_id == senior.id, PracticeCall.status.in_(["dialing", "in_progress"])
            )
        )
    ).first()
    if active:
        raise APIError(409, "call_in_progress", "A practice call is already in progress for this person")
    call = PracticeCall(
        circle_id=circle_id, senior_member_id=senior.id, voice_member_id=contact.id, scenario=body.scenario,
        difficulty=body.difficulty, status="queued", scheduled_for=body.scheduled_for, created_by=user.id, transcript=[],
    )
    session.add(call)
    await notify.audit(session, "practice_call.created", circle_id, user.id, difficulty=body.difficulty)
    await session.commit()
    if not body.scheduled_for or body.scheduled_for <= utcnow():
        background.add_task(calls.start_practice_call, call.id)
    return PracticeCallOut.model_validate(call)


@router.get("/circles/{circle_id}/practice-calls", response_model=list[PracticeCallOut])
async def list_practice_calls(circle_id: str, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    await ensure_member(session, circle_id, user)
    rows = await session.execute(
        select(PracticeCall).where(PracticeCall.circle_id == circle_id).order_by(PracticeCall.created_at.desc())
    )
    return [PracticeCallOut.model_validate(r) for r in rows.scalars()]


async def _get_call(session: AsyncSession, call_id: str, user: User) -> PracticeCall:
    call = await session.get(PracticeCall, call_id)
    if not call:
        raise not_found("Practice call")
    await ensure_member(session, call.circle_id, user)
    return call


@router.get("/practice-calls/{call_id}", response_model=PracticeCallOut)
async def get_practice_call(call_id: str, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    call = await _get_call(session, call_id, user)
    await session.refresh(call)
    return PracticeCallOut.model_validate(call)


@router.post("/practice-calls/{call_id}/cancel", response_model=PracticeCallOut)
async def cancel_practice_call(call_id: str, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    call = await _get_call(session, call_id, user)
    if call.status in calls.TERMINAL:
        raise APIError(409, "already_finished", "This call has already finished")
    ccid = call.provider_call_id
    call.status = "cancelled"
    call.ended_at = utcnow()
    await session.commit()
    if ccid:
        await twilio.hangup(ccid)
    return PracticeCallOut.model_validate(call)
