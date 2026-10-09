"""Fish Audio: voice cloning + text-to-speech (free `s2.1-pro-free` model).

- Clone: POST https://api.fish.audio/model (multipart: type=tts, title, voices=<audio>, train_mode=fast) -> {"_id": ...}
- Speak: POST https://api.fish.audio/v1/tts  (JSON {text, reference_id, format}, header `model: <model>`) -> audio bytes
- Delete: DELETE https://api.fish.audio/model/{id}
Docs: https://docs.fish.audio/features/voice-cloning
"""
import logging

import httpx

from ..config import settings

log = logging.getLogger("voicecircle.fish")
API = "https://api.fish.audio"


class FishError(Exception):
    pass


def _auth() -> dict:
    if not settings.FISH_API_KEY:
        raise FishError("FISH_API_KEY is not set")
    return {"Authorization": f"Bearer {settings.FISH_API_KEY}"}


async def create_voice(name: str, wav_bytes: bytes) -> str:
    """Clone a voice from a sample. Returns the Fish voice (model) id."""
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(
            f"{API}/model",
            headers=_auth(),
            data={"type": "tts", "title": name[:100], "visibility": "private", "train_mode": "fast"},
            files={"voices": ("sample.wav", wav_bytes, "audio/wav")},
        )
    if r.status_code >= 400:
        raise FishError(f"voice creation failed ({r.status_code}): {r.text[:300]}")
    body = r.json()
    voice_id = body.get("_id") or body.get("id")
    if not voice_id:
        raise FishError(f"voice creation returned no id: {str(body)[:300]}")
    return voice_id


async def delete_voice(voice_id: str | None) -> None:
    if not voice_id or not settings.FISH_API_KEY:
        return
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            await c.delete(f"{API}/model/{voice_id}", headers=_auth())
    except httpx.HTTPError as e:  # best effort: never block deleting a member over this
        log.warning("Could not delete Fish voice %s: %s", voice_id, e)


async def synthesize(text: str, voice_id: str | None) -> bytes:
    """Speak `text` in the cloned voice (or Fish's default voice when voice_id is empty). Returns WAV bytes."""
    body = {"text": text[:3000], "format": "wav"}
    if voice_id:
        body["reference_id"] = voice_id
    # Twilio abandons a webhook after ~15s, so don't wait longer than that for audio.
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(
            f"{API}/v1/tts",
            headers={**_auth(), "Content-Type": "application/json", "model": settings.FISH_MODEL},
            json=body,
        )
    if r.status_code >= 400:
        raise FishError(f"synthesis failed ({r.status_code}): {r.text[:300]}")
    if not r.content:
        raise FishError("synthesis returned no audio")
    return r.content
