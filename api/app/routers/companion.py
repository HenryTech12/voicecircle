"""Companion Calls (Hugh) and alerts."""
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import Alert, CompanionCall, User, get_session, utcnow
from ..deps import ensure_member, get_current_user, get_member_checked
from ..errors import APIError, bad_request, not_found
from ..schemas import AlertOut, CompanionCallOut, TrendPoint, TrendsOut
from ..services import calls, metrics

router = APIRouter()


@router.post("/members/{member_id}/companion-calls", response_model=CompanionCallOut, status_code=201, tags=["companion"])
async def call_hugh_now(member_id: str, background: BackgroundTasks, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    m = await get_member_checked(session, member_id, user)
    if m.role != "senior":
        raise bad_request("Hugh only calls the senior", "wrong_role")
    if not m.phone_e164:
        raise bad_request("The senior needs a phone number", "phone_required")
    active = (
        await session.execute(
            select(CompanionCall.id).where(CompanionCall.senior_member_id == m.id, CompanionCall.status.in_(["dialing", "in_progress"]))
        )
    ).first()
    if active:
        raise APIError(409, "call_in_progress", "Hugh is already on a call with them")
    c = CompanionCall(circle_id=m.circle_id, senior_member_id=m.id, status="queued", transcript=[], flags=[])
    session.add(c)
    await session.commit()
    background.add_task(calls.start_companion_call, c.id)
    return CompanionCallOut.model_validate(c)


@router.get("/members/{member_id}/companion-calls", response_model=list[CompanionCallOut], tags=["companion"])
async def list_companion_calls(member_id: str, limit: int = Query(30, ge=1, le=200), user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    m = await get_member_checked(session, member_id, user)
    rows = await session.execute(
        select(CompanionCall).where(CompanionCall.senior_member_id == m.id).order_by(CompanionCall.created_at.desc()).limit(limit)
    )
    return [CompanionCallOut.model_validate(c) for c in rows.scalars()]


@router.get("/companion-calls/{call_id}", response_model=CompanionCallOut, tags=["companion"])
async def get_companion_call(call_id: str, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    c = await session.get(CompanionCall, call_id)
    if not c:
        raise not_found("Companion call")
    await ensure_member(session, c.circle_id, user)
    await session.refresh(c)
    return CompanionCallOut.model_validate(c)


@router.get("/members/{member_id}/companion-trends", response_model=TrendsOut, tags=["companion"])
async def companion_trends(member_id: str, days: int = Query(14, ge=1, le=90), user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    m = await get_member_checked(session, member_id, user)
    rows = (
        await session.execute(
            select(CompanionCall).where(CompanionCall.senior_member_id == m.id, CompanionCall.status == "completed")
            .order_by(CompanionCall.created_at.asc())
        )
    ).scalars().all()
    all_metrics = [c.metrics for c in rows if c.metrics]
    base = metrics.baseline(all_metrics)
    since = utcnow() - timedelta(days=days)
    points = [
        TrendPoint(
            date=(c.started_at or c.created_at).date().isoformat(),
            wpm=(c.metrics or {}).get("wpm"), latency_ms=(c.metrics or {}).get("latency_ms"),
            filler_rate=(c.metrics or {}).get("filler_rate"), recall=(c.metrics or {}).get("recall"),
            mood=(c.metrics or {}).get("mood"),
        )
        for c in rows if (c.started_at or c.created_at) >= since
    ]
    latest_flags = rows[-1].flags if rows else []
    return TrendsOut(member_id=m.id, days=days, points=points, baseline=base, flags=latest_flags or [])


@router.get("/circles/{circle_id}/alerts", response_model=list[AlertOut], tags=["alerts"])
async def list_alerts(circle_id: str, include_acknowledged: bool = True, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    await ensure_member(session, circle_id, user)
    q = select(Alert).where(Alert.circle_id == circle_id)
    if not include_acknowledged:
        q = q.where(Alert.acknowledged_at.is_(None))
    rows = await session.execute(q.order_by(Alert.created_at.desc()))
    return [AlertOut.model_validate(a) for a in rows.scalars()]


@router.post("/alerts/{alert_id}/ack", response_model=AlertOut, tags=["alerts"])
async def ack_alert(alert_id: str, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    a = await session.get(Alert, alert_id)
    if not a:
        raise not_found("Alert")
    await ensure_member(session, a.circle_id, user)
    if not a.acknowledged_at:
        a.acknowledged_at = utcnow()
        await session.commit()
    return AlertOut.model_validate(a)
