"""Alerts + audit log helpers."""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import Alert, AuditLog, CircleMember
from . import telnyx

log = logging.getLogger("voicecircle.notify")


async def audit(session: AsyncSession, action: str, circle_id: str | None = None, actor_id: str | None = None, **details) -> None:
    session.add(AuditLog(action=action, circle_id=circle_id, actor_id=actor_id, details=details))


async def create_alert(
    session: AsyncSession, circle_id: str, type_: str, severity: str, title: str, message: str,
    source_id: str | None = None, sms: bool = True,
) -> Alert:
    alert = Alert(circle_id=circle_id, type=type_, severity=severity, title=title, message=message, source_id=source_id)
    session.add(alert)
    await audit(session, "alert.created", circle_id, None, type=type_, severity=severity, source_id=source_id)
    if sms and severity in ("warning", "urgent"):
        res = await session.execute(
            select(CircleMember).where(CircleMember.circle_id == circle_id, CircleMember.role == "trusted_contact")
        )
        for m in res.scalars():
            if m.phone_e164:
                await telnyx.send_sms(m.phone_e164, f"VoiceCircle: {title}. {message}")
    return alert
