"""Auth and access-control dependencies."""
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import jwt
from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import Circle, CircleMember, User, get_session
from .errors import APIError, forbidden, not_found

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
            if settings.SUPABASE_JWT_SECRET:
                return jwt.decode(
                    token, settings.SUPABASE_JWT_SECRET, algorithms=["HS256"], audience="authenticated"
                )
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
    except jwt.PyJWTError:
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
        user = User(id=user_id, email=email)
        session.add(user)
        await session.commit()
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
