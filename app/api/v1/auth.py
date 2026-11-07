"""Registration, login, refresh and logout."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import or_, select

from app.core.config import settings
from app.core.deps import DB, CurrentUser
from app.core.security import hash_password, needs_rehash, verify_password
from app.models.user import User, UserRole
from app.schemas import LoginRequest, RegisterRequest, UserPublic
from app.services.rate_limit import rate_limit
from app.services.serializers import user_public
from app.services.session import clear_session, issue_session, rotate_refresh

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, request: Request, response: Response, db: DB):
    await rate_limit(request, "register", settings.rate_limit_register)
    existing = await db.scalar(
        select(User).where(
            or_(User.email == payload.email.lower(), User.username == payload.username)
        )
    )
    if existing is not None:
        field = "email" if existing.email == payload.email.lower() else "username"
        raise HTTPException(status_code=409, detail=f"User with this {field} already exists")

    user = User(
        email=payload.email.lower(),
        username=payload.username,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
        role=UserRole.user,
    )
    db.add(user)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=409, detail="User already exists") from None
    await db.refresh(user)
    await issue_session(response, user)
    return user_public(user)


@router.post("/login", response_model=UserPublic)
async def login(payload: LoginRequest, request: Request, response: Response, db: DB):
    await rate_limit(request, "login-ip", settings.rate_limit_login)
    await rate_limit(request, "login-user", settings.rate_limit_login * 3, identity=payload.login.lower())

    identity = payload.login.strip().lower()
    user = await db.scalar(
        select(User).where(or_(User.email == identity, User.username == payload.login.strip()))
    )
    # Constant-ish work for unknown users keeps user enumeration timing harder.
    password_hash = user.password_hash if user else hash_password("dummy-password-value")
    valid = verify_password(payload.password, password_hash) and user is not None
    if not valid or user is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
        await db.commit()

    await issue_session(response, user)
    return user_public(user)


@router.post("/refresh", response_model=UserPublic)
async def refresh(request: Request, response: Response, db: DB):
    from app.core.security import TokenError, decode_token

    token = request.cookies.get(settings.refresh_cookie_name)
    if not token:
        raise HTTPException(status_code=401, detail="No session")
    try:
        payload = decode_token(token, "refresh")
    except TokenError:
        raise HTTPException(status_code=401, detail="Invalid session") from None
    user = await db.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        await clear_session(response)
        raise HTTPException(status_code=401, detail="Invalid session")
    if not await rotate_refresh(request, response, user):
        raise HTTPException(status_code=401, detail="Session expired")
    return user_public(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response):
    await clear_session(response, request)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserPublic)
async def me(user: CurrentUser):
    return user_public(user)
