"""Session cookies and refresh-token rotation."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Request, Response

from app.core.config import settings
from app.core.redis import get_redis
from app.core.security import TokenError, create_token, decode_token, new_csrf_token
from app.models.user import User

logger = logging.getLogger(__name__)

REFRESH_PREFIX = "refresh:"


def _refresh_ttl() -> timedelta:
    return timedelta(days=settings.refresh_token_ttl_days)


async def issue_session(response: Response, user: User) -> None:
    """Create access + refresh tokens, store the refresh JTI allow-list entry."""
    access, _, access_exp = create_token(
        subject=str(user.id),
        role=user.role.value,
        token_type="access",
        ttl=timedelta(minutes=settings.access_token_ttl_minutes),
    )
    refresh, refresh_jti, _ = create_token(
        subject=str(user.id),
        role=user.role.value,
        token_type="refresh",
        ttl=_refresh_ttl(),
    )
    try:
        await get_redis().set(
            f"{REFRESH_PREFIX}{refresh_jti}", str(user.id), ex=int(_refresh_ttl().total_seconds())
        )
    except Exception as exc:  # pragma: no cover - redis outage
        logger.warning("cannot persist refresh token: %s", exc)

    _set_cookie(response, settings.access_cookie_name, access, access_exp)
    _set_cookie(response, settings.refresh_cookie_name, refresh, datetime.now(UTC) + _refresh_ttl())
    _set_cookie(
        response,
        settings.csrf_cookie_name,
        new_csrf_token(),
        datetime.now(UTC) + _refresh_ttl(),
        http_only=False,
    )


def _set_cookie(response: Response, name: str, value: str, expires: datetime, *, http_only: bool = True) -> None:
    response.set_cookie(
        name,
        value,
        expires=expires,
        httponly=http_only,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )


async def rotate_refresh(request: Request, response: Response, user: User) -> bool:
    """Invalidate the presented refresh token and issue a brand-new session."""
    token = request.cookies.get(settings.refresh_cookie_name)
    if not token:
        return False
    try:
        payload = decode_token(token, "refresh")
    except TokenError:
        return False
    jti = payload.get("jti", "")
    try:
        stored = await get_redis().get(f"{REFRESH_PREFIX}{jti}")
        if stored is None:
            # Re-use of an unknown/revoked token: force a fresh login everywhere.
            await clear_session(response)
            return False
        await get_redis().delete(f"{REFRESH_PREFIX}{jti}")
    except Exception as exc:  # pragma: no cover - redis outage
        logger.warning("refresh allow-list unavailable: %s", exc)
    await issue_session(response, user)
    return True


async def clear_session(response: Response, request: Request | None = None) -> None:
    if request is not None:
        token = request.cookies.get(settings.refresh_cookie_name)
        if token:
            try:
                payload = jwt.decode(token, options={"verify_signature": False})
                jti = payload.get("jti")
                if jti:
                    await get_redis().delete(f"{REFRESH_PREFIX}{jti}")
            except Exception:
                pass
    for name in (
        settings.access_cookie_name,
        settings.refresh_cookie_name,
        settings.csrf_cookie_name,
    ):
        response.delete_cookie(name, path="/")
