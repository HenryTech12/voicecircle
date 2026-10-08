"""Resemble AI client (voice clone, TTS, identity, deepfake detection) with mock mode.

Docs used:
- Create voice (rapid clone from a dataset URL): POST https://app.resemble.ai/api/v2/voices
  {name, dataset_url}  (Business plan for API voice creation)
- Synthesize: POST https://f.cluster.resemble.ai/synthesize {voice_uuid, data, output_format}
  -> {audio_content: base64}
- Identity create: POST https://app.resemble.ai/api/v2/identity (multipart name + audio)
- Identity search: POST https://app.resemble.ai/api/v2/identity/search {url}
  -> {item: {<identity_id>: {name, distance}}}
- Detect: POST https://app.resemble.ai/api/v2/detect (multipart file) then
  GET /api/v2/detect/{uuid} until status is terminal; metrics.aggregated_score, metrics.label
"""
import asyncio
import base64
import logging
import uuid
from pathlib import Path

import httpx

from ..config import settings
from . import audio

log = logging.getLogger("voicecircle.resemble")
APP = "https://app.resemble.ai/api/v2"
SYNTH = "https://f.cluster.resemble.ai/synthesize"


class ResembleError(Exception):
    pass


def _h(json_body: bool = True) -> dict:
    h = {"Authorization": f"Bearer {settings.RESEMBLE_API_KEY}"}
    if json_body:
        h["Content-Type"] = "application/json"
    return h


# Mock registry of hashes of audio we generated, so mock detection can recognise clones.
def _registry() -> Path:
    p = Path(settings.STORAGE_DIR).resolve() / "_mock_generated_hashes.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _register_generated(data: bytes) -> None:
    with _registry().open("a") as f:
        f.write(audio.sha256(data) + "\n")


def _is_generated(data: bytes) -> bool:
    p = _registry()
    return p.exists() and audio.sha256(data) in p.read_text().split()


# ------------------------------------------------------------------------------------


async def create_voice(name: str, sample_url: str) -> str:
    """Create a rapid voice clone. Returns the Resemble voice UUID."""
    if settings.MOCK_PROVIDERS:
        return f"mock-voice-{uuid.uuid4().hex[:10]}"
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{APP}/voices", headers=_h(), json={"name": name, "dataset_url": sample_url})
        if r.status_code >= 400:
            raise ResembleError(f"voice creation failed ({r.status_code}): {r.text[:300]}")
        body = r.json()
        item = body.get("item") or body
        voice_uuid = item.get("uuid")
        if not voice_uuid:
            raise ResembleError(f"voice creation returned no uuid: {body}")
        return voice_uuid


async def delete_voice(voice_uuid: str | None) -> None:
    if not voice_uuid or settings.MOCK_PROVIDERS:
        return
    async with httpx.AsyncClient(timeout=30) as c:
        await c.delete(f"{APP}/voices/{voice_uuid}", headers=_h())


async def create_identity(name: str, wav_bytes: bytes) -> str:
    """Enroll a speaker for verification. Returns identity UUID."""
    if settings.MOCK_PROVIDERS:
        return f"mock-identity-{uuid.uuid4().hex[:10]}"
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(
            f"{APP}/identity",
            headers=_h(json_body=False),
            data={"name": name},
            files={"audio": ("sample.wav", wav_bytes, "audio/wav")},
        )
        if r.status_code >= 400:
            raise ResembleError(f"identity creation failed ({r.status_code}): {r.text[:300]}")
        body = r.json()
        item = body.get("item") or body
        return item["uuid"]


async def delete_identity(identity_id: str | None) -> None:
    if not identity_id or settings.MOCK_PROVIDERS:
        return
    async with httpx.AsyncClient(timeout=30) as c:
        await c.delete(f"{APP}/identity/{identity_id}", headers=_h())


async def synthesize(text: str, voice_uuid: str | None) -> bytes:
    """Text to speech in the given (cloned) voice. Returns WAV bytes."""
    if settings.MOCK_PROVIDERS or not voice_uuid:
        if not settings.MOCK_PROVIDERS and not voice_uuid:
            raise ResembleError("no voice uuid")
        data = audio.tone_wav(seconds=min(3.0, 0.4 + len(text) / 60), seed_text=f"{voice_uuid}:{text}")
        _register_generated(data)
        return data
    body = {"voice_uuid": voice_uuid, "data": text[:3000], "output_format": "wav", "sample_rate": 8000}
    if settings.RESEMBLE_PROJECT_UUID:
        body["project_uuid"] = settings.RESEMBLE_PROJECT_UUID
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(SYNTH, headers=_h(), json=body)
        if r.status_code >= 400:
            raise ResembleError(f"synthesis failed ({r.status_code}): {r.text[:300]}")
        content = r.json().get("audio_content")
        if not content:
            raise ResembleError("synthesis returned no audio")
        return base64.b64decode(content)


async def detect_synthetic(wav_bytes: bytes, filename: str = "clip.wav") -> float:
    """Probability (0..1) that the audio is AI-generated."""
    if settings.MOCK_PROVIDERS:
        name = filename.lower()
        if _is_generated(wav_bytes) or any(k in name for k in ("fake", "clone", "synthetic", "ai-", "deepfake")):
            return 0.93
        if "unsure" in name:
            return settings.DETECT_FAKE_THRESHOLD
        return 0.07
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(
            f"{APP}/detect", headers=_h(json_body=False), files={"file": (filename, wav_bytes, "audio/wav")}
        )
        if r.status_code >= 400:
            raise ResembleError(f"detect failed ({r.status_code}): {r.text[:300]}")
        item = r.json().get("item") or {}
        det_uuid = item.get("uuid")
        for _ in range(40):  # up to ~60 s
            status = (item.get("status") or "").lower()
            metrics = item.get("metrics") or {}
            if status in ("completed", "complete", "finished", "success") or metrics.get("aggregated_score"):
                return _score_from_metrics(metrics)
            if status in ("failed", "error"):
                raise ResembleError(f"detect failed: {item.get('error_message') or status}")
            await asyncio.sleep(1.5)
            g = await c.get(f"{APP}/detect/{det_uuid}", headers=_h())
            item = g.json().get("item") or {}
        raise ResembleError("detect timed out")


def _score_from_metrics(metrics: dict) -> float:
    try:
        score = float(metrics.get("aggregated_score"))
    except (TypeError, ValueError):
        scores = [float(s) for s in metrics.get("score", []) if s is not None]
        score = sum(scores) / len(scores) if scores else 0.5
    return max(0.0, min(1.0, score))


async def verify_speaker(identity_id: str | None, audio_url: str, filename: str = "") -> float | None:
    """Similarity (0..1) between the clip and the enrolled identity. None if unknown."""
    if not identity_id:
        return None
    if settings.MOCK_PROVIDERS:
        name = filename.lower()
        if any(k in name for k in ("stranger", "other", "notthem", "not-them")):
            return 0.18
        return 0.91
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{APP}/identity/search", headers=_h(), json={"url": audio_url})
        if r.status_code >= 400:
            raise ResembleError(f"identity search failed ({r.status_code}): {r.text[:300]}")
        matches = (r.json().get("item") or {})
        m = matches.get(identity_id)
        if not m:
            return 0.0
        d = float(m.get("distance", 1.0))
        return max(0.0, min(1.0, 1.0 - d)) if settings.IDENTITY_DISTANCE_LOWER_IS_BETTER else max(0.0, min(1.0, d))
