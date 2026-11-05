"""Administrator-only endpoints: roles, bans and the audit log."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func, or_, select

from app.core.deps import AdminUser, DB, Paging
from app.models.moderation import AuditLog
from app.models.user import User, UserRole
from app.schemas import ActiveUpdateRequest, RoleUpdateRequest
from app.services.audit import record_audit
from app.services.rate_limit import client_ip
from app.services.serializers import user_public

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users")
async def list_users(admin: AdminUser, db: DB, paging: Paging, q: str = ""):
    where = []
    if q.strip():
        pattern = f"%{q.strip()}%"
        where.append(or_(User.username.ilike(pattern), User.email.ilike(pattern), User.display_name.ilike(pattern)))
    total = await db.scalar(select(func.count()).select_from(User).where(*where)) or 0
    rows = await db.execute(
        select(User).where(*where).order_by(User.created_at.desc()).offset(paging.offset).limit(paging.page_size)
    )
    users = list(rows.scalars().all())
    return {
        "items": [
            {
                **user_public(u).model_dump(mode="json"),
                "email": u.email,
                "is_active": u.is_active,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in users
        ],
        "total": total,
        "page": paging.page,
        "page_size": paging.page_size,
        "has_more": paging.offset + len(users) < total,
    }


@router.patch("/users/{user_id}/role")
async def change_role(
    user_id: uuid.UUID, payload: RoleUpdateRequest, admin: AdminUser, request: Request, db: DB
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot change your own role")
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    new_role = UserRole(payload.role)
    if target.role is UserRole.admin and new_role is not UserRole.admin:
        admins = (
            await db.scalar(
                select(func.count()).select_from(User).where(User.role == UserRole.admin, User.is_active)
            )
            or 0
        )
        if admins <= 1:
            raise HTTPException(status_code=400, detail="Cannot demote the last active administrator")

    old_role = target.role
    target.role = new_role
    await record_audit(
        db,
        actor=admin,
        action="user.role_changed",
        entity_type="user",
        entity_id=str(target.id),
        meta={"from": old_role.value, "to": new_role.value},
        ip=client_ip(request),
    )
    await db.commit()
    return user_public(target)


@router.patch("/users/{user_id}/active")
async def set_active(
    user_id: uuid.UUID, payload: ActiveUpdateRequest, admin: AdminUser, request: Request, db: DB
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot disable your own account")
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if target.role is UserRole.admin and not payload.is_active:
        admins = (
            await db.scalar(
                select(func.count()).select_from(User).where(User.role == UserRole.admin, User.is_active)
            )
            or 0
        )
        if admins <= 1:
            raise HTTPException(status_code=400, detail="Cannot disable the last active administrator")
    target.is_active = payload.is_active
    await record_audit(
        db,
        actor=admin,
        action="user.active_changed",
        entity_type="user",
        entity_id=str(target.id),
        meta={"is_active": payload.is_active},
        ip=client_ip(request),
    )
    await db.commit()
    return {"id": str(target.id), "is_active": target.is_active}


@router.get("/audit")
async def audit_log(admin: AdminUser, db: DB, paging: Paging):
    total = await db.scalar(select(func.count()).select_from(AuditLog)) or 0
    rows = await db.execute(
        select(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .offset(paging.offset)
        .limit(paging.page_size)
    )
    entries = list(rows.scalars().all())
    return {
        "items": [
            {
                "id": str(e.id),
                "actor_id": str(e.actor_id) if e.actor_id else None,
                "action": e.action,
                "entity_type": e.entity_type,
                "entity_id": e.entity_id,
                "meta": e.meta,
                "ip": e.ip,
                "created_at": e.created_at.isoformat(),
            }
            for e in entries
        ],
        "total": total,
    }
