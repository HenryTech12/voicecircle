"""Voice cloning / text-to-speech facade. VOICE_PROVIDER picks Fish Audio (default, free tier) or Resemble.
Deepfake detection and speaker matching always use Resemble (see resemble.py)."""
from ..config import settings
from . import fish, resemble


def _use_fish() -> bool:
    return settings.VOICE_PROVIDER == "fish" and not settings.MOCK_PROVIDERS


async def create_voice(name: str, wav_bytes: bytes, sample_url: str) -> str:
    if _use_fish():
        return await fish.create_voice(name, wav_bytes)
    return await resemble.create_voice(name, sample_url)


async def delete_voice(voice_id: str | None) -> None:
    if _use_fish():
        await fish.delete_voice(voice_id)
    else:
        await resemble.delete_voice(voice_id)


async def synthesize(text: str, voice_id: str | None) -> bytes:
    if _use_fish():
        return await fish.synthesize(text, voice_id)
    return await resemble.synthesize(text, voice_id)
