"""Voice Circle: trusted voice enrollment."""
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import CircleMember, SessionLocal, User, VoiceProfile, get_session, utcnow
from ..deps import ensure_member, get_current_user, get_member_checked
from ..errors import APIError, bad_request
from ..schemas import OkOut, VoicePromptsOut, VoiceStatusOut
from ..services import audio, notify, resemble, storage

log = logging.getLogger("voicecircle.voice")
router = APIRouter(tags=["voice"])

CONSENT_VERSION = "v1"
CONSENT_TEXT = (
    "I agree that my voice recording can be used by VoiceCircle to verify calls and to create practice "
    "calls for this circle only. I can delete my voice at any time."
)


@router.get("/voice/prompts", response_model=VoicePromptsOut)
async def voice_prompts(
    circle_id: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    senior_name = "Grandma"
    if circle_id:
        circle = await ensure_member(session, circle_id, user)
        await session.refresh(circle, ["members"])
        senior = next((m for m in circle.members if m.role == "senior"), None)
        if senior:
            senior_name = senior.display_name
    prompts = [
        f"Hi {senior_name}, it's me. I just wanted to hear your voice and see how you're doing.",
        "The weather has been lovely this week, and I finally finished the book you gave me.",
        "I'll come by on Sunday afternoon, and we can have tea and talk about everything.",
        "Remember, if anyone ever calls asking for money in a hurry, hang up and call me back.",
        "Okay, I have to go now. Take care of yourself, and I'll talk to you very soon.",
    ]
    return VoicePromptsOut(prompts=prompts, consent_text=CONSENT_TEXT, consent_version=CONSENT_VERSION)


async def enroll_voice_task(profile_id: str) -> None:
    async with SessionLocal() as s:
        vp = await s.get(VoiceProfile, profile_id)
        if not vp:
            return
        member = await s.get(CircleMember, vp.member_id)
        try:
            wav = await storage.read(vp.sample_path)
            url = await storage.signed_url(vp.sample_path, ttl=3600)
            vp.resemble_voice_uuid = await resemble.create_voice(f"VoiceCircle {member.display_name} {member.id[:8]}", url)
            vp.resemble_identity_id = await resemble.create_identity(f"{member.display_name} {member.id[:8]}", wav)
            vp.status = "enrolled"
            vp.error = None
            await notify.audit(s, "voice.enrolled", member.circle_id, member.user_id, member_id=member.id)
        except Exception as e:
            log.exception("enrollment failed")
            vp.status = "failed"
            vp.error = f"We couldn't create the voice profile: {str(e)[:200]}"
        await s.commit()


@router.post("/members/{member_id}/voice", response_model=VoiceStatusOut, status_code=202)
async def upload_voice(
    member_id: str,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    consent: bool = Form(...),
    consent_version: str = Form(CONSENT_VERSION),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    member = await get_member_checked(session, member_id, user)
    if member.role != "trusted_contact":
        raise bad_request("Only trusted contacts enroll their voice", "wrong_role")
    if member.user_id and member.user_id != user.id:
        raise APIError(403, "forbidden", "Only this person can record their own voice")
    if not consent:
        raise bad_request("Consent is required to enroll a voice", "consent_required")
    data = await file.read()
    ext = audio.validate_upload(file.filename, data)
    wav, ext = await audio.to_wav(data, ext)
    path = await storage.save("voice-samples", wav, ext)
    if member.voice:
        old = member.voice
        await resemble.delete_voice(old.resemble_voice_uuid)
        await resemble.delete_identity(old.resemble_identity_id)
        await storage.delete(old.sample_path)
        await session.delete(old)
        await session.flush()
    vp = VoiceProfile(
        member_id=member.id, status="processing", sample_path=path,
        consent_text_version=consent_version, consent_at=utcnow(),
    )
    session.add(vp)
    await notify.audit(session, "voice.consent_given", member.circle_id, user.id, member_id=member.id, version=consent_version)
    await session.commit()
    background.add_task(enroll_voice_task, vp.id)
    return VoiceStatusOut.model_validate(vp)


@router.get("/members/{member_id}/voice", response_model=VoiceStatusOut)
async def voice_status(member_id: str, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    member = await get_member_checked(session, member_id, user)
    await session.refresh(member, ["voice"])
    if not member.voice:
        return VoiceStatusOut(status="none")
    return VoiceStatusOut.model_validate(member.voice)


@router.delete("/members/{member_id}/voice", response_model=OkOut)
async def delete_voice(member_id: str, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    member = await get_member_checked(session, member_id, user)
    if member.user_id and member.user_id != user.id:
        raise APIError(403, "forbidden", "Only this person can delete their voice")
    if not member.voice:
        raise APIError(404, "not_found", "No voice enrolled")
    vp = member.voice
    await resemble.delete_voice(vp.resemble_voice_uuid)
    await resemble.delete_identity(vp.resemble_identity_id)
    await storage.delete(vp.sample_path)
    await session.delete(vp)
    await notify.audit(session, "voice.deleted", member.circle_id, user.id, member_id=member.id)
    await session.commit()
    return OkOut(detail="Voice deleted")
