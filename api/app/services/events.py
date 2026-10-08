"""Event bus for call events.

Live mode: Twilio webhooks (POST /webhooks/twilio/*) are turned into events and handled inline
so the engine's actions can be returned as TwiML.
Mock mode: the mock Twilio client emits events here. With MOCK_EVENT_DELAY > 0 a single
worker processes them in order with a delay (feels like a real call). With
MOCK_EVENT_DELAY == 0 events are queued and processed when flush() is called (tests).
"""
import asyncio
import logging
import uuid
from typing import Awaitable, Callable

from ..config import settings

log = logging.getLogger("voicecircle.events")

Handler = Callable[[dict], Awaitable[None]]
_handler: Handler | None = None
_inline_queue: list[dict] = []
_draining = False
_queue: asyncio.Queue | None = None
_worker: asyncio.Task | None = None


def set_handler(fn: Handler) -> None:
    global _handler
    _handler = fn


def make_event(event_type: str, payload: dict) -> dict:
    return {
        "data": {
            "record_type": "event",
            "id": f"mock-{uuid.uuid4()}",
            "event_type": event_type,
            "payload": payload,
        }
    }


async def _process(event: dict) -> None:
    if _handler is None:
        return
    try:
        await _handler(event)
    except Exception:  # never kill the worker
        log.exception("event handler failed for %s", event.get("data", {}).get("event_type"))


async def _run_worker() -> None:
    assert _queue is not None
    while True:
        delay, event = await _queue.get()
        await asyncio.sleep(delay)
        await _process(event)
        await flush()


def emit(event: dict, delay: float | None = None) -> None:
    global _queue, _worker
    d = settings.MOCK_EVENT_DELAY if delay is None else delay
    if settings.MOCK_EVENT_DELAY <= 0:
        _inline_queue.append(event)
        return
    if _queue is None:
        _queue = asyncio.Queue()
    if _worker is None or _worker.done():
        _worker = asyncio.get_running_loop().create_task(_run_worker())
    _queue.put_nowait((d, event))


async def flush() -> None:
    """Process queued inline events (and any they emit) until the queue is empty."""
    global _draining
    if _draining:
        return
    _draining = True
    try:
        while _inline_queue:
            await _process(_inline_queue.pop(0))
    finally:
        _draining = False


def pending() -> int:
    return len(_inline_queue) + (_queue.qsize() if _queue else 0)
