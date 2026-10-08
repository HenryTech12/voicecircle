"""Health, auth, circles and members."""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import settings
from ..db import (
    Alert, Circle, CircleMember, CompanionCall, DetectionCheck, PracticeCall, User, VoiceProfile, get_session,
)
from ..deps import create_local_token, ensure_member, get_current_user, get_member_checked
from ..errors import APIError, bad_request
from ..schemas import (
    AuthConfigOut, CircleBrief, CircleIn, CircleOut, CircleStats, DevLoginIn, MeOut, MemberIn, MemberOut,
    MemberPatch, OkOut, TokenOut, UserOut,
)
from ..services import notify, resemble, storage

router = APIRouter()


def member_out(m: CircleMember) -> MemberOut:
    out = MemberOut.model_validate(m)
    out.voice_status = m.voice.status if m.voice else "none"
    return out


async def circle_out(session: AsyncSession, circle: Circle, with_stats: bool = True) -> CircleOut:
    rows = (
        await session.execute(
            select(CircleMember).options(selectinload(CircleMember.voice))
            .where(CircleMember.circle_id == circle.id).execution_options(populate_existing=True)
        )
    ).scalars().all()
    members = sorted(rows, key=lambda m: (m.role != "senior", m.created_at))
    out = CircleOut(
        id=circle.id, name=circle.name, owner_id=circle.owner_id, created_at=circle.created_at,
        members=[member_out(m) for m in members],
    )
    if with_stats:
        last_pc = (
            await session.execute(
                select(PracticeCall).where(PracticeCall.circle_id == circle.id, PracticeCall.status == "completed")
                .order_by(PracticeCall.ended_at.desc()).limit(1)
            )
        ).scalar()
        last_cc = (
            await session.execute(
                select(func.max(CompanionCall.ended_at)).where(
                    CompanionCall.circle_id == circle.id, CompanionCall.status == "completed"
                )
            )
        ).scalar()
        open_alerts = (
            await session.execute(
                select(func.count(Alert.id)).where(Alert.circle_id == circle.id, Alert.acknowledged_at.is_(None))
            )
        ).scalar()
        detections = (
            await session.execute(select(func.count(DetectionCheck.id)).where(DetectionCheck.circle_id == circle.id))
        ).scalar()
        out.stats = CircleStats(
            voices_enrolled=sum(1 for m in members if m.voice and m.voice.status == "enrolled"),
            last_practice_score=last_pc.score if last_pc else None,
            last_practice_at=last_pc.ended_at if last_pc else None,
            last_companion_at=last_cc,
            open_alerts=open_alerts or 0,
            detections=detections or 0,
        )
    return out


# ---------------------------------------------------------------- health & auth


@router.get("/health", tags=["system"])
async def health():
    return {"status": "ok", "mock_providers": settings.MOCK_PROVIDERS, "auth_mode": settings.AUTH_MODE}


@router.get("/auth/config", response_model=AuthConfigOut, tags=["auth"])
async def auth_config():
    return AuthConfigOut(auth_mode=settings.AUTH_MODE, mock_providers=settings.MOCK_PROVIDERS, demo_mode=settings.DEMO_MODE)


@router.post("/auth/dev-login", response_model=TokenOut, tags=["auth"])
async def dev_login(body: DevLoginIn, session: AsyncSession = Depends(get_session)):
    """Passwordless local login for development (AUTH_MODE=local only)."""
    if settings.AUTH_MODE != "local":
        raise APIError(403, "disabled", "Local login is disabled. Use Supabase sign-in.")
    email = body.email.lower()
    user = (await session.execute(select(User).where(User.email == email))).scalar()
    if not user:
        user = User(email=email, full_name=body.full_name)
        session.add(user)
    elif body.full_name:
        user.full_name = body.full_name
    await session.commit()
    return TokenOut(access_token=create_local_token(user.id, user.email), user=UserOut.model_validate(user))


@router.get("/me", response_model=MeOut, tags=["auth"])
async def me(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    owned = (await session.execute(select(Circle).where(Circle.owner_id == user.id))).scalars().all()
    member_rows = (
        await session.execute(
            select(Circle, CircleMember.role).join(CircleMember, CircleMember.circle_id == Circle.id)
            .where(CircleMember.user_id == user.id)
        )
    ).all()
    seen, circles = set(), []
    for c in owned:
        seen.add(c.id)
        circles.append(CircleBrief(id=c.id, name=c.name, role="owner"))
    for c, role in member_rows:
        if c.id not in seen:
            seen.add(c.id)
            circles.append(CircleBrief(id=c.id, name=c.name, role=role))
    return MeOut(id=user.id, email=user.email, full_name=user.full_name, circles=circles)


# ---------------------------------------------------------------- circles


@router.post("/circles", response_model=CircleOut, status_code=201, tags=["circles"])
async def create_circle(body: CircleIn, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    circle = Circle(name=body.name.strip(), owner_id=user.id)
    session.add(circle)
    await session.flush()
    session.add(
        CircleMember(
            circle_id=circle.id, user_id=user.id, role="trusted_contact",
            display_name=body.my_display_name or user.full_name or user.email.split("@")[0].title(),
            relationship_label=body.my_relationship, phone_e164=body.my_phone_e164,
        )
    )
    await notify.audit(session, "circle.created", circle.id, user.id)
    await session.commit()
    return await circle_out(session, circle)


@router.get("/circles", response_model=list[CircleOut], tags=["circles"])
async def list_circles(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    ids = set((await session.execute(select(Circle.id).where(Circle.owner_id == user.id))).scalars())
    ids |= set((await session.execute(select(CircleMember.circle_id).where(CircleMember.user_id == user.id))).scalars())
    circles = (await session.execute(select(Circle).where(Circle.id.in_(ids)).order_by(Circle.created_at))).scalars().all()
    return [await circle_out(session, c) for c in circles]


@router.get("/circles/{circle_id}", response_model=CircleOut, tags=["circles"])
async def get_circle(circle_id: str, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    circle = await ensure_member(session, circle_id, user)
    return await circle_out(session, circle)


@router.patch("/circles/{circle_id}", response_model=CircleOut, tags=["circles"])
async def rename_circle(circle_id: str, body: CircleIn, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    circle = await ensure_member(session, circle_id, user)
    circle.name = body.name.strip()
    await session.commit()
    return await circle_out(session, circle)


@router.delete("/circles/{circle_id}", response_model=OkOut, tags=["circles"])
async def delete_circle(circle_id: str, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    circle = await ensure_member(session, circle_id, user)
    if circle.owner_id != user.id:
        raise APIError(403, "forbidden", "Only the circle owner can delete it")
    await _delete_circle_data(session, circle)
    await session.commit()
    return OkOut()


async def _delete_circle_data(session: AsyncSession, circle: Circle) -> None:
    await session.refresh(circle, ["members"])
    for m in circle.members:
        if m.voice:
            await resemble.delete_voice(m.voice.resemble_voice_uuid)
            await resemble.delete_identity(m.voice.resemble_identity_id)
            await storage.delete(m.voice.sample_path)
    for model in (PracticeCall, DetectionCheck, CompanionCall, Alert):
        rows = (await session.execute(select(model).where(model.circle_id == circle.id))).scalars().all()
        for r in rows:
            if isinstance(r, DetectionCheck):
                await storage.delete(r.audio_path)
            await session.delete(r)
    await session.flush()
    await session.delete(circle)


# ---------------------------------------------------------------- members


@router.post("/circles/{circle_id}/members", response_model=MemberOut, status_code=201, tags=["members"])
async def add_member(circle_id: str, body: MemberIn, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    await ensure_member(session, circle_id, user)
    if body.role == "senior" and not body.phone_e164:
        raise bad_request("A phone number is required for the senior so VoiceCircle can call them.", "phone_required")
    if body.link_to_me:
        existing = (
            await session.execute(select(CircleMember).where(CircleMember.circle_id == circle_id, CircleMember.user_id == user.id))
        ).scalar()
        if existing:
            raise APIError(409, "already_member", "You are already a member of this circle")
    m = CircleMember(
        circle_id=circle_id, user_id=user.id if body.link_to_me else None, role=body.role,
        display_name=body.display_name.strip(), relationship_label=body.relationship, phone_e164=body.phone_e164,
        timezone=body.timezone, companion_call_time=body.companion_call_time,
        companion_enabled=body.companion_enabled if body.role == "senior" else False, personal_facts=body.personal_facts,
    )
    session.add(m)
    await notify.audit(session, "member.added", circle_id, user.id, role=body.role)
    await session.commit()
    await session.refresh(m, ["voice"])
    return member_out(m)


@router.get("/members/{member_id}", response_model=MemberOut, tags=["members"])
async def get_member(member_id: str, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    return member_out(await get_member_checked(session, member_id, user))


@router.patch("/members/{member_id}", response_model=MemberOut, tags=["members"])
async def update_member(member_id: str, body: MemberPatch, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    m = await get_member_checked(session, member_id, user)
    data = body.model_dump(exclude_unset=True)
    if "relationship" in data:
        data["relationship_label"] = data.pop("relationship")
    if data.get("companion_enabled") and m.role != "senior":
        raise bad_request("Companion calls are only for the senior")
    for k, v in data.items():
        setattr(m, k, v)
    if m.role == "senior" and not m.phone_e164:
        raise bad_request("The senior needs a phone number", "phone_required")
    await session.commit()
    return member_out(m)


@router.delete("/members/{member_id}", response_model=OkOut, tags=["members"])
async def delete_member(member_id: str, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    m = await get_member_checked(session, member_id, user)
    used = (
        await session.execute(
            select(func.count(PracticeCall.id)).where(
                (PracticeCall.senior_member_id == m.id) | (PracticeCall.voice_member_id == m.id)
            )
        )
    ).scalar()
    used += (
        await session.execute(select(func.count(CompanionCall.id)).where(CompanionCall.senior_member_id == m.id))
    ).scalar()
    used += (
        await session.execute(select(func.count(DetectionCheck.id)).where(DetectionCheck.claimed_member_id == m.id))
    ).scalar()
    if used:
        raise APIError(409, "member_in_use", "This member has call history. Delete the circle instead, or keep the member.")
    if m.voice:
        await resemble.delete_voice(m.voice.resemble_voice_uuid)
        await resemble.delete_identity(m.voice.resemble_identity_id)
        await storage.delete(m.voice.sample_path)
        await session.delete(m.voice)
    await session.delete(m)
    await notify.audit(session, "member.deleted", m.circle_id, user.id, member_id=member_id)
    await session.commit()
    return OkOut()


__all__ = ["router", "member_out", "circle_out", "_delete_circle_data", "VoiceProfile"]
