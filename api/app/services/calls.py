"""Call engines: practice scam calls and Hugh companion calls, driven by call events (Twilio webhooks, or the mock provider).

State machine (practice): queued -> dialing -> in_progress -> completed | no_answer | failed | cancelled
"""
import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select

from ..config import settings
from ..db import CircleMember, CompanionCall, PracticeCall, ProcessedEvent, SessionLocal, utcnow
from . import events, llm, metrics, notify, scenarios, storage, twilio, voices

log = logging.getLogger("voicecircle.calls")
_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

TERMINAL = {"completed", "failed", "no_answer", "cancelled"}


def _ms_since(start: datetime | None) -> int:
    if not start:
        return 0
    return int((datetime.now(timezone.utc) - start).total_seconds() * 1000)


async def _tts_url(text: str, voice_uuid: str | None) -> str | None:
    """Synthesize text in the cloned voice and return a fetchable URL (None on failure)."""
    try:
        wav = await voices.synthesize(text, voice_uuid)
        path = await storage.save("call-audio", wav, "wav")
        return await storage.signed_url(path)
    except Exception as e:
        log.warning("TTS failed, falling back to Twilio <Say>: %s", e)
        return None


async def _say(ccid: str, text: str, voice_uuid: str | None) -> None:
    url = await _tts_url(text, voice_uuid) if voice_uuid else None
    if url:
        await twilio.playback_start(ccid, url)
    else:
        await twilio.speak(ccid, text)


# ====================================================================== practice


async def start_practice_call(call_id: str) -> None:
    async with SessionLocal() as s:
        call = await s.get(PracticeCall, call_id)
        if not call or call.status != "queued":
            return
        senior = await s.get(CircleMember, call.senior_member_id)
        contact = await s.get(CircleMember, call.voice_member_id)
        voice_uuid = contact.voice.resemble_voice_uuid if contact and contact.voice else None
        opener = scenarios.opener(
            call.scenario, call.difficulty, senior.display_name, contact.display_name, contact.personal_facts or senior.personal_facts or []
        )
        opener_url = await _tts_url(opener, voice_uuid)
        call.status = "dialing"
        call.engine_state = {"phase": "dialing", "opener": opener, "opener_url": opener_url, "transcribing": False}
        await s.commit()
        try:
            ccid = await twilio.dial(senior.phone_e164, {"kind": "practice", "id": call.id})
        except Exception as e:
            log.exception("dial failed")
            call.status = "failed"
            call.feedback = {"error": f"Could not place the call: {e}"}
            await s.commit()
            return
        call.provider_call_id = ccid
        await notify.audit(s, "voice_clone.used", call.circle_id, call.created_by, practice_call_id=call.id, voice_member_id=contact.id)
        await s.commit()
    await events.flush()


async def _practice_closing(s, call: PracticeCall, ccid: str, reason: str) -> None:
    contact = await s.get(CircleMember, call.voice_member_id)
    text = scenarios.DISCLOSURE.format(contact=contact.display_name if contact else "your family member")
    st = dict(call.engine_state or {})
    st["phase"] = "closing"
    st["close_reason"] = reason
    call.engine_state = st
    call.transcript = [*call.transcript, {"speaker": "system", "text": text, "t_ms": _ms_since(call.started_at)}]
    await s.commit()
    await twilio.speak(ccid, text)  # neutral voice, never the clone


async def handle_practice(etype: str, payload: dict, call_id: str) -> None:
    ccid = payload.get("call_control_id")
    async with _locks[call_id]:
        async with SessionLocal() as s:
            call = await s.get(PracticeCall, call_id)
            if not call or call.status in TERMINAL:
                return
            st = dict(call.engine_state or {})
            contact = await s.get(CircleMember, call.voice_member_id)
            senior = await s.get(CircleMember, call.senior_member_id)
            voice_uuid = contact.voice.resemble_voice_uuid if contact and contact.voice else None

            if etype == "call.answered":
                call.status = "in_progress"
                call.started_at = utcnow()
                call.provider_call_id = ccid or call.provider_call_id
                st["phase"] = "talking"
                call.engine_state = st
                call.transcript = [{"speaker": "caller", "text": st.get("opener", ""), "t_ms": 0}]
                await s.commit()
                if st.get("opener_url"):
                    await twilio.playback_start(ccid, st["opener_url"])
                else:
                    await twilio.speak(ccid, st.get("opener", "Hello?"))

            elif etype in ("call.playback.ended", "call.speak.ended"):
                if st.get("phase") == "closing":
                    await twilio.hangup(ccid)
                elif not st.get("transcribing"):
                    st["transcribing"] = True
                    call.engine_state = st
                    await s.commit()
                    await twilio.transcription_start(ccid)
                else:
                    await twilio.listen_again(ccid)

            elif etype == "call.transcription":
                td = payload.get("transcription_data") or {}
                text = (td.get("transcript") or "").strip()
                if not text or td.get("is_final") is False or st.get("phase") == "closing" or call.status != "in_progress":
                    return
                if llm.is_sensitive(text):
                    # never store or forward what looks like real personal / financial details
                    call.transcript = [*call.transcript, {"speaker": "senior", "text": "[personal details removed]", "t_ms": _ms_since(call.started_at)}]
                    call.safety_stop = True
                    await _practice_closing(s, call, ccid, "safety_stop")
                    return
                call.transcript = [*call.transcript, {"speaker": "senior", "text": text, "t_ms": _ms_since(call.started_at)}]
                await s.commit()
                if llm.stood_firm(call.transcript):
                    await _practice_closing(s, call, ccid, "senior_stood_firm")
                    return
                if call.turns + 1 >= settings.PRACTICE_MAX_TURNS or _ms_since(call.started_at) > settings.PRACTICE_MAX_SECONDS * 1000:
                    await _practice_closing(s, call, ccid, "limit")
                    return
                call.turns += 1
                nxt = await llm.next_scam_line(
                    call.scenario, call.difficulty, call.turns, senior.display_name, contact.display_name,
                    contact.relationship_label, contact.personal_facts or [], call.transcript,
                )
                if nxt.get("end") or not nxt.get("line"):
                    await _practice_closing(s, call, ccid, "script_end")
                    return
                call.transcript = [*call.transcript, {"speaker": "caller", "text": nxt["line"], "t_ms": _ms_since(call.started_at)}]
                await s.commit()
                await _say(ccid, nxt["line"], voice_uuid)

            elif etype == "call.silence":
                if st.get("phase") != "closing" and call.status == "in_progress":
                    await _practice_closing(s, call, ccid, "silence")

            elif etype == "call.hangup":
                await _finish_practice(s, call, st, payload)


async def _finish_practice(s, call: PracticeCall, st: dict, payload: dict) -> None:
    call.ended_at = utcnow()
    if not call.started_at:
        call.status = "no_answer"
        call.feedback = {"error": "The call was not answered."}
        await s.commit()
        return
    call.status = "completed"
    call.duration_seconds = int((call.ended_at - call.started_at).total_seconds())
    hung_up_by_senior = st.get("phase") != "closing"
    result = await llm.classify_outcome(call.transcript, hung_up_by_senior, call.safety_stop)
    call.outcome = result["outcome"]
    call.score = result["score"]
    call.feedback = {"did_well": result["did_well"], "practice_next": result["practice_next"], "hung_up_by_senior": hung_up_by_senior}
    senior = await s.get(CircleMember, call.senior_member_id)
    contact = await s.get(CircleMember, call.voice_member_id)
    debrief = (
        f"VoiceCircle: That call was a practice call arranged by your family, not really {contact.display_name}. "
        f"{result['did_well'][0]} Tip: {result['practice_next'][0]}"
    )
    await twilio.send_sms(senior.phone_e164 if senior else None, debrief)
    if call.outcome in ("hesitated", "complied"):
        sev = "urgent" if call.outcome == "complied" else "warning"
        await notify.create_alert(
            s, call.circle_id, "scam_risk", sev,
            f"{senior.display_name} {'went along with' if call.outcome == 'complied' else 'nearly went along with'} a practice scam",
            f"On a {call.difficulty} practice call, {senior.display_name} "
            f"{'agreed to send money' if call.outcome == 'complied' else 'engaged with the money request before stopping'}. "
            "More practice and a family code word can help.",
            call.id,
        )
    await notify.audit(s, "practice_call.completed", call.circle_id, None, practice_call_id=call.id, outcome=call.outcome)
    await s.commit()


# ====================================================================== companion


async def start_companion_call(call_id: str) -> None:
    async with SessionLocal() as s:
        call = await s.get(CompanionCall, call_id)
        if not call or call.status != "queued":
            return
        senior = await s.get(CircleMember, call.senior_member_id)
        res = await s.execute(
            select(CompanionCall.summary)
            .where(CompanionCall.senior_member_id == senior.id, CompanionCall.status == "completed", CompanionCall.id != call.id)
            .order_by(CompanionCall.created_at.desc())
            .limit(3)
        )
        previous = [x for x in res.scalars() if x]
        call.recall_question = llm.recall_question_for(previous[0] if previous else None)
        call.engine_state = {"phase": "dialing", "previous": previous, "transcribing": False}
        call.status = "dialing"
        await s.commit()
        try:
            ccid = await twilio.dial(senior.phone_e164, {"kind": "companion", "id": call.id})
        except Exception as e:
            call.status = "failed"
            call.summary = f"Could not place the call: {e}"
            await s.commit()
            return
        call.provider_call_id = ccid
        await s.commit()
    await events.flush()


async def handle_companion(etype: str, payload: dict, call_id: str) -> None:
    ccid = payload.get("call_control_id")
    async with _locks[call_id]:
        async with SessionLocal() as s:
            call = await s.get(CompanionCall, call_id)
            if not call or call.status in TERMINAL:
                return
            st = dict(call.engine_state or {})
            senior = await s.get(CircleMember, call.senior_member_id)

            if etype == "call.answered":
                call.status = "in_progress"
                call.started_at = utcnow()
                st["phase"] = "talking"
                first = await llm.companion_reply(senior.display_name, 0, call.recall_question or "", st.get("previous", []), [])
                call.transcript = [{"speaker": "hugh", "text": first["line"], "t_ms": 0}]
                call.engine_state = st
                await s.commit()
                await twilio.speak(ccid, first["line"])

            elif etype in ("call.speak.ended", "call.playback.ended"):
                if call.transcript and call.transcript[-1]["speaker"] == "hugh":
                    tr = [dict(t) for t in call.transcript]
                    tr[-1]["t_ms"] = _ms_since(call.started_at)
                    call.transcript = tr
                if st.get("phase") == "closing":
                    await s.commit()
                    await twilio.hangup(ccid)
                elif not st.get("transcribing"):
                    st["transcribing"] = True
                    call.engine_state = st
                    await s.commit()
                    await twilio.transcription_start(ccid)
                else:
                    await s.commit()
                    await twilio.listen_again(ccid)

            elif etype == "call.transcription":
                td = payload.get("transcription_data") or {}
                text = (td.get("transcript") or "").strip()
                if not text or td.get("is_final") is False or st.get("phase") == "closing":
                    return
                call.transcript = [*call.transcript, {"speaker": "senior", "text": text, "t_ms": _ms_since(call.started_at)}]
                call.turns += 1
                reply = await llm.companion_reply(
                    senior.display_name, call.turns, call.recall_question or "", st.get("previous", []), call.transcript
                )
                if reply.get("end"):
                    st["phase"] = "closing"
                    call.engine_state = st
                if reply.get("line"):
                    call.transcript = [*call.transcript, {"speaker": "hugh", "text": reply["line"], "t_ms": _ms_since(call.started_at)}]
                    await s.commit()
                    await twilio.speak(ccid, reply["line"])
                else:
                    await s.commit()
                    await twilio.hangup(ccid)

            elif etype == "call.silence":
                if st.get("phase") != "closing":
                    bye = f"I can't quite hear you, {senior.display_name}. I'll call again tomorrow. Take care!"
                    st["phase"] = "closing"
                    call.engine_state = st
                    call.transcript = [*call.transcript, {"speaker": "hugh", "text": bye, "t_ms": _ms_since(call.started_at)}]
                    await s.commit()
                    await twilio.speak(ccid, bye)

            elif etype == "call.hangup":
                await finalize_companion(s, call, senior)


async def finalize_companion(s, call: CompanionCall, senior: CircleMember) -> None:
    call.ended_at = utcnow()
    if not call.started_at:
        call.status = "no_answer"
        await s.commit()
        return
    call.status = "completed"
    call.duration_seconds = int((call.ended_at - call.started_at).total_seconds())
    summ = await llm.summarize_companion(call.transcript, call.recall_question)
    call.summary = summ["summary"]
    current = metrics.compute(call.transcript, summ["recall"], summ["mood"], summ["repetition"])
    res = await s.execute(
        select(CompanionCall)
        .where(CompanionCall.senior_member_id == senior.id, CompanionCall.status == "completed", CompanionCall.id != call.id)
        .order_by(CompanionCall.created_at.asc())
    )
    history = [c.metrics for c in res.scalars() if c.metrics]
    base = metrics.baseline(history)
    flags = metrics.flags_for(current, base, history)
    call.metrics = current
    call.flags = flags
    if flags:
        await notify.create_alert(
            s, call.circle_id, "wellbeing_change", "warning",
            f"Hugh noticed a change in {senior.display_name}'s calls",
            metrics.describe(flags, senior.display_name), call.id,
        )
    await s.commit()


# ====================================================================== dispatch


async def handle_event(event: dict) -> None:
    data = event.get("data") or {}
    etype = data.get("event_type") or ""
    payload = data.get("payload") or {}
    eid = data.get("id")
    async with SessionLocal() as s:
        if eid:
            if await s.get(ProcessedEvent, eid):
                return
            s.add(ProcessedEvent(event_id=eid))
            await s.commit()
        state = twilio.decode_state(payload.get("client_state"))
        kind, obj_id = state.get("kind"), state.get("id")
        ccid = payload.get("call_control_id")
        if not kind and ccid:
            pc = (await s.execute(select(PracticeCall.id).where(PracticeCall.provider_call_id == ccid))).scalar()
            if pc:
                kind, obj_id = "practice", pc
            else:
                cc = (await s.execute(select(CompanionCall.id).where(CompanionCall.provider_call_id == ccid))).scalar()
                if cc:
                    kind, obj_id = "companion", cc
    if kind == "practice" and obj_id:
        await handle_practice(etype, payload, obj_id)
    elif kind == "companion" and obj_id:
        await handle_companion(etype, payload, obj_id)
    else:
        log.info("ignoring event %s (no matching call)", etype)


events.set_handler(handle_event)
