"""Telnyx Call Control + Messaging client, with a mock implementation.

Docs used:
- Dial:                POST https://api.telnyx.com/v2/calls
- Playback start:      POST /v2/calls/{call_control_id}/actions/playback_start
- Speak:               POST /v2/calls/{call_control_id}/actions/speak
- Transcription start: POST /v2/calls/{call_control_id}/actions/transcription_start
- AI assistant start:  POST /v2/calls/{call_control_id}/actions/ai_assistant_start
- Hangup:              POST /v2/calls/{call_control_id}/actions/hangup
- Send SMS:            POST https://api.telnyx.com/v2/messages
- Webhooks are signed with Ed25519: headers telnyx-signature-ed25519 + telnyx-timestamp,
  signed message = f"{timestamp}|{raw_body}".
"""
import base64
import json
import logging
import time
import uuid

import httpx
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import settings
from . import events

log = logging.getLogger("voicecircle.telnyx")
API = "https://api.telnyx.com/v2"

# --- client_state helpers -------------------------------------------------------------


def encode_state(state: dict) -> str:
    return base64.b64encode(json.dumps(state).encode()).decode()


def decode_state(value: str | None) -> dict:
    if not value:
        return {}
    try:
        return json.loads(base64.b64decode(value).decode())
    except Exception:
        return {}


# --- webhook signature ----------------------------------------------------------------


def verify_signature(raw_body: bytes, signature_b64: str | None, timestamp: str | None, tolerance: int = 300) -> bool:
    if not settings.TELNYX_PUBLIC_KEY or not signature_b64 or not timestamp:
        return False
    try:
        if abs(time.time() - int(timestamp)) > tolerance:
            return False
        key = VerifyKey(base64.b64decode(settings.TELNYX_PUBLIC_KEY))
        key.verify(f"{timestamp}|".encode() + raw_body, base64.b64decode(signature_b64))
        return True
    except (BadSignatureError, ValueError, TypeError):
        return False


# --- mock state -------------------------------------------------------------------------

MOCK_CALLS: dict[str, dict] = {}
SENT_SMS: list[dict] = []  # inspected by tests and the dev status endpoint

AUTO_SENIOR_LINES = {
    "practice": [
        "Hello? Who is this?",
        "Oh no, are you alright? What happened?",
        "How much do you need? Where do I send it?",
        "Wait. Let me call your mother first to check.",
    ],
    "companion": [
        "Oh hello Hugh, I'm doing fine, thank you.",
        "I had some rice and stew, and I watered my plants.",
        "Yes, the cake turned out lovely, my neighbour had some.",
        "Alright dear, talk tomorrow.",
    ],
}


def _mock_emit(event_type: str, ccid: str, extra: dict | None = None, delay: float | None = None) -> None:
    call = MOCK_CALLS.get(ccid, {})
    payload = {
        "call_control_id": ccid,
        "call_leg_id": call.get("leg_id"),
        "call_session_id": call.get("session_id"),
        "client_state": call.get("client_state"),
        "from": settings.TELNYX_FROM_NUMBER or "+15550000000",
        "to": call.get("to"),
        **(extra or {}),
    }
    events.emit(events.make_event(event_type, payload), delay)


def mock_say(ccid: str, text: str) -> bool:
    """Simulate the senior speaking (dev simulator / tests)."""
    call = MOCK_CALLS.get(ccid)
    if not call or call.get("hung_up"):
        return False
    _mock_emit(
        "call.transcription",
        ccid,
        {"transcription_data": {"transcript": text, "is_final": True, "confidence": 0.95}},
        delay=0.2 if settings.MOCK_EVENT_DELAY > 0 else 0,
    )
    return True


def mock_hangup_by_senior(ccid: str) -> bool:
    call = MOCK_CALLS.get(ccid)
    if not call or call.get("hung_up"):
        return False
    call["hung_up"] = True
    _mock_emit("call.hangup", ccid, {"hangup_cause": "normal_clearing", "hangup_source": "callee"}, delay=0.2)
    return True


def _mock_auto_reply(ccid: str) -> None:
    call = MOCK_CALLS.get(ccid)
    if not call or not settings.MOCK_AUTO_SENIOR or call.get("hung_up"):
        return
    kind = decode_state(call.get("client_state")).get("kind", "practice")
    lines = AUTO_SENIOR_LINES.get(kind, AUTO_SENIOR_LINES["practice"])
    idx = call.get("auto_idx", 0)
    if idx < len(lines):
        call["auto_idx"] = idx + 1
        mock_say(ccid, lines[idx])


# --- client -------------------------------------------------------------------------------


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.TELNYX_API_KEY}", "Content-Type": "application/json"}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=0.5, max=4), reraise=True)
async def _post(path: str, body: dict) -> dict:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{API}{path}", headers=_headers(), json=body)
        if r.status_code >= 400:
            log.error("Telnyx %s failed: %s %s", path, r.status_code, r.text[:500])
        r.raise_for_status()
        return r.json()


async def dial(to: str, client_state: dict) -> str:
    """Place an outbound call. Returns call_control_id."""
    state = encode_state(client_state)
    if settings.MOCK_PROVIDERS:
        ccid = f"mock-cc-{uuid.uuid4().hex[:12]}"
        MOCK_CALLS[ccid] = {
            "to": to,
            "client_state": state,
            "leg_id": str(uuid.uuid4()),
            "session_id": str(uuid.uuid4()),
            "transcribing": False,
            "hung_up": False,
            "actions": [],
        }
        _mock_emit("call.initiated", ccid)
        _mock_emit("call.answered", ccid)
        return ccid
    data = await _post(
        "/calls",
        {
            "connection_id": settings.TELNYX_CONNECTION_ID,
            "to": to,
            "from": settings.TELNYX_FROM_NUMBER,
            "webhook_url": f"{settings.PUBLIC_BASE_URL.rstrip('/')}/api/v1/webhooks/telnyx",
            "client_state": state,
            "timeout_secs": 30,
        },
    )
    return data["data"]["call_control_id"]


async def playback_start(ccid: str, audio_url: str) -> None:
    if settings.MOCK_PROVIDERS:
        MOCK_CALLS.get(ccid, {}).setdefault("actions", []).append(("playback", audio_url))
        _mock_emit("call.playback.ended", ccid, {"media_url": audio_url, "status": "completed"})
        return
    await _post(f"/calls/{ccid}/actions/playback_start", {"audio_url": audio_url})


async def speak(ccid: str, text: str) -> None:
    if settings.MOCK_PROVIDERS:
        MOCK_CALLS.get(ccid, {}).setdefault("actions", []).append(("speak", text))
        _mock_emit("call.speak.ended", ccid, {"status": "completed"})
        return
    await _post(
        f"/calls/{ccid}/actions/speak",
        {"payload": text, "voice": settings.TELNYX_SPEAK_VOICE, "language": "en-US"},
    )


async def transcription_start(ccid: str) -> None:
    if settings.MOCK_PROVIDERS:
        call = MOCK_CALLS.get(ccid, {})
        call["transcribing"] = True
        _mock_auto_reply(ccid)
        return
    await _post(
        f"/calls/{ccid}/actions/transcription_start",
        {"transcription_engine": settings.TELNYX_TRANSCRIPTION_ENGINE, "transcription_tracks": "inbound"},
    )


async def listen_again(ccid: str) -> None:
    """Called after we finish speaking: in mock auto mode, the senior replies again."""
    if settings.MOCK_PROVIDERS:
        _mock_auto_reply(ccid)


async def ai_assistant_start(ccid: str, instructions: str, greeting: str) -> None:
    if settings.MOCK_PROVIDERS:
        MOCK_CALLS.get(ccid, {}).setdefault("actions", []).append(("ai_assistant", greeting))
        return
    await _post(
        f"/calls/{ccid}/actions/ai_assistant_start",
        {
            "assistant": {"id": settings.TELNYX_HUGH_ASSISTANT_ID, "instructions": instructions},
            "greeting": greeting,
            "send_message_history_updates": True,
        },
    )


async def hangup(ccid: str) -> None:
    if settings.MOCK_PROVIDERS:
        call = MOCK_CALLS.get(ccid)
        if call and not call.get("hung_up"):
            call["hung_up"] = True
            _mock_emit("call.hangup", ccid, {"hangup_cause": "normal_clearing", "hangup_source": "caller"})
        return
    try:
        await _post(f"/calls/{ccid}/actions/hangup", {})
    except httpx.HTTPStatusError as e:  # already ended
        log.warning("hangup failed: %s", e)


async def send_sms(to: str | None, text: str) -> bool:
    if not to:
        return False
    if settings.MOCK_PROVIDERS:
        SENT_SMS.append({"to": to, "text": text})
        return True
    try:
        await _post(
            "/messages",
            {
                "from": settings.TELNYX_FROM_NUMBER,
                "to": to,
                "text": text,
                "messaging_profile_id": settings.TELNYX_MESSAGING_PROFILE_ID or None,
            },
        )
        return True
    except Exception as e:
        log.error("SMS to %s failed: %s", to, e)
        return False
