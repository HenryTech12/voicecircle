"""File storage: local disk (dev) or Supabase Storage (prod). Files are private; access
is through short-lived signed URLs."""
import logging
import mimetypes
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import jwt

from ..config import settings
from ..errors import APIError

log = logging.getLogger("voicecircle.storage")

BUCKETS = ("voice-samples", "call-audio", "detection-uploads")


def _root() -> Path:
    p = Path(settings.STORAGE_DIR).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe_local_path(path: str) -> Path:
    root = _root()
    full = (root / path).resolve()
    if root not in full.parents:
        raise ValueError("invalid storage path")
    return full


def _sb_headers() -> dict:
    key = settings.SUPABASE_SERVICE_ROLE_KEY
    # New-style secret keys (sb_secret_...) are not JWTs: sending them as a Bearer token is rejected
    # with a 400, so they go in the apikey header only.
    if key.startswith("sb_"):
        return {"apikey": key}
    return {"Authorization": f"Bearer {key}", "apikey": key}


def _sb_error(r: httpx.Response) -> APIError:
    body = r.text[:300]
    log.error("Supabase Storage %s %s -> %s %s", r.request.method, r.request.url.path, r.status_code, body)
    return APIError(502, "storage_error", f"File storage failed ({r.status_code}): {body}")


async def ensure_buckets() -> None:
    """Create the private buckets in Supabase Storage if they don't exist yet (no-op for local disk)."""
    if settings.STORAGE_BACKEND != "supabase":
        return
    async with httpx.AsyncClient(timeout=30) as c:
        for b in BUCKETS:
            await _create_bucket(c, b)


async def _create_bucket(c: httpx.AsyncClient, bucket: str) -> None:
    try:
        r = await c.post(
            f"{settings.SUPABASE_URL}/storage/v1/bucket",
            headers=_sb_headers(),
            json={"id": bucket, "name": bucket, "public": False},
        )
        if r.status_code in (200, 201):
            log.warning("Created Supabase storage bucket %s", bucket)
        elif r.status_code == 409 or "already exists" in r.text.lower():
            pass
        else:
            log.error("Could not create bucket %s: %s %s", bucket, r.status_code, r.text[:300])
    except httpx.HTTPError as e:
        log.error("Could not reach Supabase Storage to create bucket %s: %s", bucket, e)


async def save(bucket: str, data: bytes, ext: str, name: str | None = None) -> str:
    """Store bytes; returns a storage path like 'call-audio/ab12.wav'."""
    if bucket not in BUCKETS:
        raise ValueError(f"unknown bucket {bucket}")
    ext = ext.lstrip(".") or "bin"
    key = f"{name or uuid.uuid4().hex}.{ext}"
    path = f"{bucket}/{key}"
    if settings.STORAGE_BACKEND == "supabase":
        ctype = mimetypes.guess_type(key)[0] or "application/octet-stream"
        async with httpx.AsyncClient(timeout=60) as c:
            for attempt in (1, 2):
                r = await c.post(
                    f"{settings.SUPABASE_URL}/storage/v1/object/{path}",
                    headers={**_sb_headers(), "Content-Type": ctype, "x-upsert": "true"},
                    content=data,
                )
                if r.is_success:
                    break
                if attempt == 1 and "bucket not found" in r.text.lower():
                    await _create_bucket(c, bucket)
                    continue
                raise _sb_error(r)
    else:
        full = _safe_local_path(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(data)
    return path


async def read(path: str) -> bytes:
    if settings.STORAGE_BACKEND == "supabase":
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.get(f"{settings.SUPABASE_URL}/storage/v1/object/{path}", headers=_sb_headers())
            if not r.is_success:
                raise _sb_error(r)
            return r.content
    return _safe_local_path(path).read_bytes()


async def delete(path: str | None) -> None:
    if not path:
        return
    if settings.STORAGE_BACKEND == "supabase":
        bucket, key = path.split("/", 1)
        async with httpx.AsyncClient(timeout=30) as c:
            await c.request(
                "DELETE",
                f"{settings.SUPABASE_URL}/storage/v1/object/{bucket}",
                headers=_sb_headers(),
                json={"prefixes": [key]},
            )
        return
    try:
        _safe_local_path(path).unlink(missing_ok=True)
    except ValueError:
        pass


async def signed_url(path: str, ttl: int | None = None) -> str:
    """A URL that third parties (Twilio, Resemble) or the browser can fetch."""
    ttl = ttl or settings.MEDIA_URL_TTL_SECONDS
    if settings.STORAGE_BACKEND == "supabase":
        bucket, key = path.split("/", 1)
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"{settings.SUPABASE_URL}/storage/v1/object/sign/{bucket}/{key}",
                headers=_sb_headers(),
                json={"expiresIn": ttl},
            )
            if not r.is_success:
                raise _sb_error(r)
            return f"{settings.SUPABASE_URL}/storage/v1{r.json()['signedURL']}"
    token = jwt.encode(
        {"p": path, "exp": datetime.now(timezone.utc) + timedelta(seconds=ttl), "typ": "media"},
        settings.LOCAL_JWT_SECRET,
        algorithm="HS256",
    )
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/api/v1/media/{token}"


def resolve_media_token(token: str) -> Path:
    claims = jwt.decode(token, settings.LOCAL_JWT_SECRET, algorithms=["HS256"])
    if claims.get("typ") != "media":
        raise jwt.InvalidTokenError("wrong token type")
    return _safe_local_path(claims["p"])
