"""Twilio Programmable Voice + Messaging adapter, with a mock implementation.

The call engine (services/calls.py) is event-driven: it reacts to events such as
``call.answered``, ``call.speak.ended``, ``call.transcription`` and ``call.hangup`` and
issues actions (play audio, speak, listen, hang up).

Twilio works the other way round: on each step Twilio calls our webhook and we reply
with TwiML. This adapter bridges the two:

* Webhook handlers (routers/system.py) open a TwiML context with ``twiml_context(sid)``,
  turn the Twilio request into an engine event and run the engine.
* While the context is open, ``playback_start`` / ``speak`` / ``transcription_start`` /
  ``listen_again`` / ``hangup`` append verbs instead of calling an API.
* Because Twilio plays audio and then moves on by itself, the handler feeds the engine a
  synthetic ``call.speak.ended`` after it speaks, which makes it ask for a ``<Gather>``
  (listen) or ``<Hangup>``. ``render_twiml`` turns the verbs into the XML response.
* Outside a webhook (e.g. the user cancels a call) actions use the REST API.

Twilio endpoints used:
- Create call:  POST /2010-04-01/Accounts/{Sid}/Calls.json  (To, From, Url, StatusCallback)
- Update call:  POST /2010-04-01/Accounts/{Sid}/Calls/{CallSid}.json  (Status=completed | Twiml)
- Send SMS:     POST /2010-04-01/Accounts/{Sid}/Messages.json  (To, Body, From | MessagingServiceSid)
- Webhooks are signed: X-Twilio-Signature = base64(HMAC-SHA1(auth_token, url + sorted k+v of POST params)).
"""
import base64
import contextvars
import hashlib
import hmac
import json
import logging
import uuid
from contextlib import contextmanager
from urllib.parse import urlencode, quote
from xml.sax.saxutils import escape, quoteattr

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import settings
from . import events

log = logging.getLogger("voicecircle.twilio")
API = "https://api.twilio.com/2010-04-01"
FINAL_STATUSES = {"completed", "busy", "failed", "no-answer", "canceled"}

# --- state helpers (carried in webhook URLs) --------------------------------------------


def encode_state(state: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(state, separators=(",", ":")).encode()).decode()


def decode_state(value: str | None) -> dict:
    if not value:
        return {}
    try:
        return json.loads(base64.urlsafe_b64decode(value.encode()).decode())
    except Exception:
        return {}


def webhook_url(kind: str, state: str, **extra: str | int) -> str:
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    q = f"state={quote(state)}" + "".join(f"&{k}={quote(str(v))}" for k, v in extra.items())
    return f"{base}/api/v1/webhooks/twilio/{kind}?{q}"


# --- webhook signature ----------------------------------------------------------------


def compute_signature(url: str, params: dict[str, str], token: str | None = None) -> str:
    token = token if token is not None else settings.TWILIO_AUTH_TOKEN
    data = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    return base64.b64encode(hmac.new(token.encode(), data.encode(), hashlib.sha1).digest()).decode()


def verify_signature(url: str, params: dict[str, str], signature: str | None) -> bool:
    if not settings.TWILIO_AUTH_TOKEN or not signature:
        return False
    return hmac.compare_digest(compute_signature(url, params), signature)


# --- TwiML context ----------------------------------------------------------------------

_twiml: contextvars.ContextVar[dict | None] = contextvars.ContextVar("twiml", default=None)


@contextmanager
def twiml_context(call_sid: str):
    ctx = {"sid": call_sid, "verbs": []}
    token = _twiml.set(ctx)
    try:
        yield ctx
    finally:
        _twiml.reset(token)


def _ctx(call_sid: str) -> dict | None:
    c = _twiml.get()
    return c if c and c["sid"] == call_sid else None


def needs_followup(verbs: list[tuple]) -> bool:
    """True when the engine spoke but hasn't yet said whether to listen or hang up."""
    return bool(verbs) and verbs[-1][0] in ("play", "say")


def render_twiml(verbs: list[tuple], gather_action: str) -> str:
    out: list[str] = []
    ended = False
    for v in verbs:
        if v[0] == "play":
            out.append(f"<Play>{escape(v[1])}</Play>")
        elif v[0] == "say":
            out.append(
                f"<Say voice={quoteattr(settings.TWILIO_SAY_VOICE)} language={quoteattr(settings.TWILIO_SPEECH_LANGUAGE)}>"
                f"{escape(v[1])}</Say>"
            )
        elif v[0] == "hangup":
            out.append("<Hangup/>")
            ended = True
            break
        elif v[0] == "gather":
            out.append(gather_xml(gather_action))
            ended = True
            break
    if not ended:
        out.append(gather_xml(gather_action))
    return '<?xml version="1.0" encoding="UTF-8"?><Response>' + "".join(out) + "</Response>"


def gather_xml(action: str) -> str:
    return (
        f'<Gather input="speech" method="POST" action={quoteattr(action)} speechTimeout="auto" '
        f'timeout="{settings.TWILIO_GATHER_TIMEOUT}" language={quoteattr(settings.TWILIO_SPEECH_LANGUAGE)} '
        f'actionOnEmptyResult="true"/>'
    )


def empty_twiml() -> str:
    return '<?xml version="1.0" encoding="UTF-8"?><Response/>'


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


def _mock_emit(event_type: str, sid: str, extra: dict | None = None, delay: float | None = None) -> None:
    call = MOCK_CALLS.get(sid, {})
    payload = {
        "call_control_id": sid,
        "client_state": call.get("client_state"),
        "from": settings.TWILIO_FROM_NUMBER or "+15550000000",
        "to": call.get("to"),
        **(extra or {}),
    }
    events.emit(events.make_event(event_type, payload), delay)


def mock_say(sid: str, text: str) -> bool:
    """Simulate the senior speaking (dev simulator / tests)."""
    call = MOCK_CALLS.get(sid)
    if not call or call.get("hung_up"):
        return False
    _mock_emit(
        "call.transcription",
        sid,
        {"transcription_data": {"transcript": text, "is_final": True, "confidence": 0.95}},
        delay=0.2 if settings.MOCK_EVENT_DELAY > 0 else 0,
    )
    return True


def mock_hangup_by_senior(sid: str) -> bool:
    call = MOCK_CALLS.get(sid)
    if not call or call.get("hung_up"):
        return False
    call["hung_up"] = True
    _mock_emit("call.hangup", sid, {"hangup_source": "callee", "call_status": "completed"}, delay=0.2)
    return True


def _mock_auto_reply(sid: str) -> None:
    call = MOCK_CALLS.get(sid)
    if not call or not settings.MOCK_AUTO_SENIOR or call.get("hung_up"):
        return
    kind = decode_state(call.get("client_state")).get("kind", "practice")
    lines = AUTO_SENIOR_LINES.get(kind, AUTO_SENIOR_LINES["practice"])
    idx = call.get("auto_idx", 0)
    if idx < len(lines):
        call["auto_idx"] = idx + 1
        mock_say(sid, lines[idx])


# --- REST client ------------------------------------------------------------------------


@retry(
    stop=stop_after_attempt(3), wait=wait_exponential(min=0.5, max=4), reraise=True,
    retry=retry_if_exception_type(httpx.TransportError),  # never retry a request Twilio accepted
)
async def _post(path: str, data: dict | list) -> dict:
    sid = settings.TWILIO_ACCOUNT_SID
    async with httpx.AsyncClient(timeout=20, auth=(sid, settings.TWILIO_AUTH_TOKEN)) as c:
        # `data` may be a list of (key, value) pairs so keys can repeat (e.g. StatusCallbackEvent). Recent httpx
        # versions treat a non-dict `data=` as a raw sync stream, which crashes an AsyncClient, so encode it here.
        r = await c.post(
            f"{API}/Accounts/{sid}{path}",
            content=urlencode(data),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if r.status_code >= 400:
            log.error("Twilio %s failed: %s %s", path, r.status_code, r.text[:500])
        r.raise_for_status()
        return r.json()


async def dial(to: str, client_state: dict) -> str:
    """Place an outbound call. Returns the Twilio CallSid."""
    state = encode_state(client_state)
    if settings.MOCK_PROVIDERS:
        sid = f"CAmock{uuid.uuid4().hex[:26]}"
        MOCK_CALLS[sid] = {"to": to, "client_state": state, "transcribing": False, "hung_up": False, "actions": []}
        _mock_emit("call.initiated", sid)
        _mock_emit("call.answered", sid)
        return sid
    data = await _post(
        "/Calls.json",
        [
            ("To", to),
            ("From", settings.TWILIO_FROM_NUMBER),
            ("Url", webhook_url("voice", state)),
            ("Method", "POST"),
            ("StatusCallback", webhook_url("status", state)),
            ("StatusCallbackMethod", "POST"),
            ("StatusCallbackEvent", "completed"),
            ("Timeout", "30"),
        ],
    )
    return data["sid"]


async def _update_call(sid: str, twiml: str) -> None:
    try:
        await _post(f"/Calls/{sid}.json", {"Twiml": twiml})
    except httpx.HTTPStatusError as e:  # call already over
        log.warning("call update failed: %s", e)


async def playback_start(sid: str, audio_url: str) -> None:
    if settings.MOCK_PROVIDERS:
        MOCK_CALLS.get(sid, {}).setdefault("actions", []).append(("playback", audio_url))
        _mock_emit("call.playback.ended", sid, {"media_url": audio_url, "status": "completed"})
        return
    if c := _ctx(sid):
        c["verbs"].append(("play", audio_url))
    else:
        await _update_call(sid, render_twiml([("play", audio_url), ("hangup",)], ""))


async def speak(sid: str, text: str) -> None:
    if settings.MOCK_PROVIDERS:
        MOCK_CALLS.get(sid, {}).setdefault("actions", []).append(("speak", text))
        _mock_emit("call.speak.ended", sid, {"status": "completed"})
        return
    if c := _ctx(sid):
        c["verbs"].append(("say", text))
    else:
        await _update_call(sid, render_twiml([("say", text), ("hangup",)], ""))


async def transcription_start(sid: str) -> None:
    """Start listening to the senior (a speech <Gather> on Twilio)."""
    if settings.MOCK_PROVIDERS:
        MOCK_CALLS.get(sid, {})["transcribing"] = True
        _mock_auto_reply(sid)
        return
    if c := _ctx(sid):
        c["verbs"].append(("gather",))


async def listen_again(sid: str) -> None:
    if settings.MOCK_PROVIDERS:
        _mock_auto_reply(sid)
        return
    if c := _ctx(sid):
        c["verbs"].append(("gather",))


async def hangup(sid: str) -> None:
    if settings.MOCK_PROVIDERS:
        call = MOCK_CALLS.get(sid)
        if call and not call.get("hung_up"):
            call["hung_up"] = True
            _mock_emit("call.hangup", sid, {"hangup_source": "caller", "call_status": "completed"})
        return
    if c := _ctx(sid):
        c["verbs"].append(("hangup",))
        return
    try:
        await _post(f"/Calls/{sid}.json", {"Status": "completed"})
    except httpx.HTTPStatusError as e:  # already ended
        log.warning("hangup failed: %s", e)


async def send_sms(to: str | None, text: str) -> bool:
    if not to:
        return False
    if settings.MOCK_PROVIDERS:
        SENT_SMS.append({"to": to, "text": text})
        return True
    body = {"To": to, "Body": text}
    if settings.TWILIO_MESSAGING_SERVICE_SID:
        body["MessagingServiceSid"] = settings.TWILIO_MESSAGING_SERVICE_SID
    else:
        body["From"] = settings.TWILIO_FROM_NUMBER
    try:
        await _post("/Messages.json", body)
        return True
    except Exception as e:
        log.error("SMS to %s failed: %s", to, e)
        return False
