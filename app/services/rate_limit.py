"""Fixed-window rate limiting backed by Redis.

Fail-open by design: an unavailable Redis must not take the whole site down,
but every failure is logged so it is visible in operations.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, Request, status

from app.core.config import settings
from app.core.redis import get_redis

logger = logging.getLogger(__name__)


def client_ip(request: Request) -> str:
    """Trust ``X-Forwarded-For`` only for the first hop (nginx sets it)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def enforce_rate_limit(bucket: str, identity: str, limit: int, window: int | None = None) -> None:
    window = window or settings.rate_limit_window_sec
    key = f"rl:{bucket}:{identity}"
    try:
        redis = get_redis()
        current = await redis.incr(key)
        if current == 1:
            await redis.expire(key, window)
        if current > limit:
            ttl = await redis.ttl(key)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests, slow down",
                headers={"Retry-After": str(max(ttl, 1))},
            )
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - redis outage
        logger.warning("rate limiter unavailable (%s): %s", bucket, exc)


async def rate_limit(request: Request, bucket: str, limit: int, *, identity: str | None = None) -> None:
    await enforce_rate_limit(bucket, identity or client_ip(request), limit)
