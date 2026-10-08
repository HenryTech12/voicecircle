"""Auth and access-control dependencies."""
import logging
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import jwt
from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import Circle, CircleMember, User, get_session
from .errors import APIError, forbidden, not_found

log = logging.getLogger("voicecircle.auth")

LOCAL_ISSUER = "voicecircle-local"


def create_local_token(user_id: str, email: str, hours: int = 72) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "aud": "authenticated",
        "iss": LOCAL_ISSUER,
        "iat": now,
        "exp": now + timedelta(hours=hours),
    }
    return jwt.encode(payload, settings.LOCAL_JWT_SECRET, algorithm="HS256")


@lru_cache
def _jwks_client() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/.well-known/jwks.json")


def decode_token(token: str) -> dict:
    try:
        if settings.AUTH_MODE == "supabase":
            alg = jwt.get_unverified_header(token).get("alg", "")
            if alg == "HS256":
                if not settings.SUPABASE_JWT_SECRET:
                    log.warning("Supabase token is HS256 but SUPABASE_JWT_SECRET is not set")
                    raise APIError(401, "invalid_token", "Invalid authentication token")
                return jwt.decode(
                    token, settings.SUPABASE_JWT_SECRET, algorithms=["HS256"], audience="authenticated"
                )
            # Newer Supabase projects sign with asymmetric keys (ES256/RS256) published via JWKS.
            key = _jwks_client().get_signing_key_from_jwt(token).key
            return jwt.decode(token, key, algorithms=["RS256", "ES256"], audience="authenticated")
        return jwt.decode(
            token,
            settings.LOCAL_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
            issuer=LOCAL_ISSUER,
        )
    except jwt.ExpiredSignatureError:
        raise APIError(401, "token_expired", "Your session has expired. Please sign in again.")
    except jwt.PyJWTError as e:
        # Log the real reason (wrong secret, wrong audience, wrong auth mode...) so it shows in Render logs.
        log.warning("Token rejected (AUTH_MODE=%s): %s: %s", settings.AUTH_MODE, type(e).__name__, e)
        raise APIError(401, "invalid_token", "Invalid authentication token")


async def get_current_user(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise APIError(401, "unauthorized", "Missing bearer token")
    claims = decode_token(authorization.split(" ", 1)[1].strip())
    user_id = claims.get("sub")
    email = claims.get("email") or f"{user_id}@unknown.local"
    if not user_id:
        raise APIError(401, "invalid_token", "Token has no subject")
    user = await session.get(User, user_id)
    if user is None:
        # The same email may already exist under another id (e.g. AUTH_MODE switched, or two first
        # requests racing). Reuse that row instead of crashing on the unique email constraint.
        user = (await session.execute(select(User).where(User.email == email))).scalar()
    if user is None:
        user = User(id=user_id, email=email)
        session.add(user)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            user = await session.get(User, user_id) or (
                await session.execute(select(User).where(User.email == email))
            ).scalar()
            if user is None:
                raise
    return user


async def ensure_member(session: AsyncSession, circle_id: str, user: User) -> Circle:
    circle = await session.get(Circle, circle_id)
    if circle is None:
        raise not_found("Circle")
    res = await session.execute(
        select(CircleMember.id).where(CircleMember.circle_id == circle_id, CircleMember.user_id == user.id)
    )
    if circle.owner_id != user.id and res.first() is None:
        raise forbidden()
    return circle


async def get_member_checked(session: AsyncSession, member_id: str, user: User) -> CircleMember:
    member = await session.get(CircleMember, member_id)
    if member is None:
        raise not_found("Member")
    await ensure_member(session, member.circle_id, user)
    return member
