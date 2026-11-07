"""FastAPI dependencies: authentication, RBAC, CSRF and pagination."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import TokenError, decode_token, csrf_tokens_match
from app.db.session import get_db
from app.models.user import User, UserRole
from app.services.rate_limit import client_ip

DB = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user_optional(request: Request, db: DB) -> User | None:
    token: str | None = None
    via = "cookie"

    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        via = "bearer"
    elif settings.access_cookie_name in request.cookies:
        token = request.cookies.get(settings.access_cookie_name)

    request.state.auth_via = via
    if not token:
        return None
    try:
        payload = decode_token(token, "access")
        user_id = uuid.UUID(payload["sub"])
    except (TokenError, ValueError, KeyError):
        return None

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        return None
    return user


CurrentUserOptional = Annotated[User | None, Depends(get_current_user_optional)]


async def get_current_user(user: CurrentUserOptional) -> User:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_csrf(request: Request) -> None:
    """Double-submit cookie check for cookie-authenticated mutations."""
    if getattr(request.state, "auth_via", "cookie") == "bearer":
        return
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    cookie = request.cookies.get(settings.csrf_cookie_name)
    header = request.headers.get(settings.csrf_header_name)
    if not csrf_tokens_match(cookie, header):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token missing or invalid")


async def require_moderator(user: CurrentUser) -> User:
    if user.role not in (UserRole.moderator, UserRole.admin):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Moderator role required")
    return user


async def require_admin(user: CurrentUser) -> User:
    if user.role is not UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator role required")
    return user


ModeratorUser = Annotated[User, Depends(require_moderator)]
AdminUser = Annotated[User, Depends(require_admin)]


class Pagination:
    def __init__(self, page: int = 1, page_size: int = 24) -> None:
        self.page = max(page, 1)
        self.page_size = min(max(page_size, 1), 60)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


Paging = Annotated[Pagination, Depends()]


def request_ip(request: Request) -> str:
    return client_ip(request)
