"""Scheduler: daily Hugh calls at each senior's local time + scheduled practice calls."""
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .db import CircleMember, CompanionCall, PracticeCall, SessionLocal
from .services import calls

log = logging.getLogger("voicecircle.jobs")


async def scheduler_tick(now: datetime | None = None) -> dict:
    """Run once a minute. Returns what it started (useful for tests)."""
    now = now or datetime.now(timezone.utc)
    started = {"companion": [], "practice": []}
    async with SessionLocal() as s:
        seniors = (
            await s.execute(
                select(CircleMember).where(
                    CircleMember.role == "senior", CircleMember.companion_enabled.is_(True),
                    CircleMember.companion_call_time.is_not(None), CircleMember.phone_e164.is_not(None),
                )
            )
        ).scalars().all()
        for m in seniors:
            local = now.astimezone(ZoneInfo(m.timezone))
            if local.strftime("%H:%M") != m.companion_call_time:
                continue
            day_start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
            already = (
                await s.execute(
                    select(CompanionCall.id).where(
                        CompanionCall.senior_member_id == m.id,
                        CompanionCall.created_at >= day_start_local.astimezone(timezone.utc),
                    )
                )
            ).first()
            if already:
                continue
            c = CompanionCall(circle_id=m.circle_id, senior_member_id=m.id, status="queued", transcript=[], flags=[], created_at=now)
            s.add(c)
            await s.commit()
            started["companion"].append(c.id)
        due = (
            await s.execute(
                select(PracticeCall.id).where(
                    PracticeCall.status == "queued", PracticeCall.scheduled_for.is_not(None), PracticeCall.scheduled_for <= now
                )
            )
        ).scalars().all()
        started["practice"].extend(due)
    for cid in started["companion"]:
        await calls.start_companion_call(cid)
    for pid in started["practice"]:
        await calls.start_practice_call(pid)
    return started


def start_scheduler():
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    sched = AsyncIOScheduler()
    sched.add_job(scheduler_tick, "cron", second=5, id="voicecircle-tick", max_instances=1, coalesce=True)
    sched.start()
    log.info("scheduler started")
    return sched
