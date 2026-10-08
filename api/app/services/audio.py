"""Audio helpers: upload validation, ffmpeg conversion to WAV, mock audio generation."""
import asyncio
import hashlib
import io
import math
import shutil
import struct
import wave

from ..config import settings
from ..errors import APIError

ALLOWED_EXT = {"wav", "mp3", "m4a", "webm", "ogg", "mp4", "aac", "flac"}


def validate_upload(filename: str | None, data: bytes) -> str:
    ext = (filename or "").rsplit(".", 1)[-1].lower() if filename and "." in filename else ""
    if ext not in ALLOWED_EXT:
        raise APIError(415, "unsupported_media", f"Please upload an audio file ({', '.join(sorted(ALLOWED_EXT))}).")
    if len(data) == 0:
        raise APIError(400, "empty_file", "The uploaded file is empty.")
    if len(data) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise APIError(413, "file_too_large", f"Files must be under {settings.MAX_UPLOAD_MB} MB.")
    return ext


async def to_wav(data: bytes, ext: str) -> tuple[bytes, str]:
    """Convert any audio to 16-bit mono WAV with ffmpeg. Falls back to the original bytes."""
    if ext == "wav" or not shutil.which("ffmpeg"):
        return data, ext
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
            "-ac", "1", "-ar", "22050", "-f", "wav", "pipe:1",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(proc.communicate(data), timeout=60)
        if proc.returncode == 0 and out:
            return out, "wav"
    except Exception:
        pass
    return data, ext


def tone_wav(seconds: float = 1.0, freq: float = 440.0, seed_text: str = "") -> bytes:
    """Small valid WAV used as mock synthesized speech. seed_text makes bytes unique."""
    rate = 8000
    n = int(rate * seconds)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        offset = int(hashlib.sha256(seed_text.encode()).hexdigest()[:4], 16) % 200
        frames = b"".join(
            struct.pack("<h", int(6000 * math.sin(2 * math.pi * (freq + offset) * i / rate))) for i in range(n)
        )
        w.writeframes(frames)
    return buf.getvalue()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
