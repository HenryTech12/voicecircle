"""Deepfake Check: real-or-fake analysis of uploaded recordings."""
import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import CircleMember, DetectionCheck, SessionLocal, User, get_session
from ..deps import ensure_member, get_current_user
from ..errors import bad_request, not_found
from ..schemas import DetectionOut
from ..services import audio, notify, resemble, storage

log = logging.getLogger("voicecircle.detection")
router = APIRouter(tags=["detection"])

SAFE_ACTION = "If you're ever unsure, hang up and call them back on a number you already know."


def decide(synthetic: float, match: float | None, name: str) -> tuple[str, str]:
    """Combine detector + speaker match into one verdict with a plain-language explanation."""
    t, margin = settings.DETECT_FAKE_THRESHOLD, settings.DETECT_UNSURE_MARGIN
    if synthetic >= t + margin:
        return "fake", f"This voice was most likely made by a computer. It is probably not really {name}. {SAFE_ACTION}"
    if synthetic > t - margin:
        return "unsure", f"We can't tell for sure if this is really {name}. {SAFE_ACTION}"
    if match is None:
        return "unsure", f"This sounds like a real human voice, but {name} has no voice sample to compare with. {SAFE_ACTION}"
    if match >= settings.SPEAKER_MATCH_THRESHOLD:
        return "real", f"This looks like a real voice, and it matches {name}'s voice sample. {SAFE_ACTION}"
    if match <= settings.SPEAKER_MATCH_THRESHOLD - 0.25:
        return "not_them", f"This is a real person, but it does not sound like {name}. {SAFE_ACTION}"
    return "unsure", f"This is a real voice, but we can't be sure it's {name}. {SAFE_ACTION}"


def to_out(d: DetectionCheck, name: str | None) -> DetectionOut:
    out = DetectionOut.model_validate(d)
    out.claimed_member_name = name
    return out


async def run_detection(check_id: str) -> None:
    async with SessionLocal() as s:
        d = await s.get(DetectionCheck, check_id)
        if not d:
            return
        member = await s.get(CircleMember, d.claimed_member_id)
        try:
            wav = await storage.read(d.audio_path)
            url = await storage.signed_url(d.audio_path, ttl=900)
            identity = member.voice.resemble_identity_id if member.voice and member.voice.status == "enrolled" else None
            synthetic, match = await asyncio.gather(
                resemble.detect_synthetic(wav, d.original_filename or "clip.wav"),
                resemble.verify_speaker(identity, url, d.original_filename or ""),
            )
            d.synthetic_score = round(float(synthetic), 3)
            d.speaker_match_score = round(float(match), 3) if match is not None else None
            d.verdict, d.explanation = decide(d.synthetic_score, d.speaker_match_score, member.display_name)
            d.status = "done"
            if d.verdict in ("fake", "not_them"):
                await notify.create_alert(
                    s, d.circle_id, "detection_fake", "urgent",
                    f"A recording claiming to be {member.display_name} looks {'fake' if d.verdict == 'fake' else 'like someone else'}",
                    "Someone may be impersonating a family member. Please talk to your loved one and agree a family code word.",
                    d.id,
                )
            await notify.audit(s, "detection.completed", d.circle_id, d.created_by, detection_id=d.id, verdict=d.verdict)
        except Exception as e:
            log.exception("detection failed")
            d.status = "failed"
            d.error = "We couldn't check this recording. Please try again or use a different file."
            d.explanation = str(e)[:300]
        await s.commit()


@router.post("/circles/{circle_id}/detections", response_model=DetectionOut, status_code=202)
async def create_detection(
    circle_id: str, background: BackgroundTasks,
    file: UploadFile = File(...), claimed_member_id: str = Form(...),
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session),
):
    await ensure_member(session, circle_id, user)
    member = await session.get(CircleMember, claimed_member_id)
    if not member or member.circle_id != circle_id:
        raise bad_request("Pick who the caller said they were", "invalid_member")
    data = await file.read()
    ext = audio.validate_upload(file.filename, data)
    wav, ext = await audio.to_wav(data, ext)
    path = await storage.save("detection-uploads", wav, ext)
    d = DetectionCheck(
        circle_id=circle_id, claimed_member_id=member.id, audio_path=path, original_filename=file.filename,
        status="processing", created_by=user.id,
    )
    session.add(d)
    await session.commit()
    background.add_task(run_detection, d.id)
    return to_out(d, member.display_name)


@router.get("/circles/{circle_id}/detections", response_model=list[DetectionOut])
async def list_detections(circle_id: str, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    await ensure_member(session, circle_id, user)
    rows = await session.execute(
        select(DetectionCheck, CircleMember.display_name)
        .join(CircleMember, CircleMember.id == DetectionCheck.claimed_member_id)
        .where(DetectionCheck.circle_id == circle_id)
        .order_by(DetectionCheck.created_at.desc())
    )
    return [to_out(d, name) for d, name in rows.all()]


@router.get("/detections/{detection_id}", response_model=DetectionOut)
async def get_detection(detection_id: str, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    d = await session.get(DetectionCheck, detection_id)
    if not d:
        raise not_found("Check")
    await ensure_member(session, d.circle_id, user)
    await session.refresh(d)
    member = await session.get(CircleMember, d.claimed_member_id)
    return to_out(d, member.display_name if member else None)
