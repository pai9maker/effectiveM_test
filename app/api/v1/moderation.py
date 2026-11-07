"""Moderation queue, video hiding and moderation statistics."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.core.deps import DB, ModeratorUser, Paging
from app.models.moderation import Report, ReportStatus
from app.models.video import ModerationStatus, Video
from app.schemas import ModerateVideoRequest, ResolveReportRequest
from app.services.audit import record_audit
from app.services.rate_limit import client_ip
from app.services.serializers import video_detail

router = APIRouter(prefix="/moderation", tags=["moderation"])


@router.get("/reports")
async def list_reports(moderator: ModeratorUser, db: DB, paging: Paging, status_filter: str = "open"):
    try:
        report_status = ReportStatus(status_filter)
    except ValueError:
        raise HTTPException(status_code=422, detail="Unknown status filter") from None
    total = (
        await db.scalar(
            select(func.count()).select_from(Report).where(Report.status == report_status)
        )
        or 0
    )
    rows = await db.execute(
        select(Report)
        .options(
            joinedload(Report.video).joinedload(Video.owner),
            joinedload(Report.reporter),
        )
        .where(Report.status == report_status)
        .order_by(Report.created_at.asc())
        .offset(paging.offset)
        .limit(paging.page_size)
    )
    reports = list(rows.unique().scalars().all())
    return {
        "items": [
            {
                "id": str(r.id),
                "reason": r.reason.value,
                "details": r.details,
                "status": r.status.value,
                "created_at": r.created_at.isoformat(),
                "reporter": r.reporter.username,
                "video": video_detail(r.video).model_dump(mode="json") if r.video else None,
            }
            for r in reports
        ],
        "total": total,
        "page": paging.page,
        "page_size": paging.page_size,
        "has_more": paging.offset + len(reports) < total,
    }


@router.post("/reports/{report_id}/resolve", status_code=status.HTTP_200_OK)
async def resolve_report(
    report_id: uuid.UUID,
    payload: ResolveReportRequest,
    moderator: ModeratorUser,
    request: Request,
    db: DB,
):
    report = await db.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if report.status not in (ReportStatus.open, ReportStatus.reviewed):
        raise HTTPException(status_code=409, detail="Report is already resolved")

    video = await db.get(Video, report.video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")

    if payload.action == "dismiss":
        report.status = ReportStatus.dismissed
    else:
        new_state = ModerationStatus.hidden if payload.action == "hide" else ModerationStatus.removed
        video.moderation_status = new_state
        video.moderated_by_id = moderator.id
        video.moderated_at = datetime.now(UTC)
        video.moderation_reason = payload.note or f"report:{report.reason.value}"
        report.status = ReportStatus.actioned

    report.resolved_by_id = moderator.id
    report.resolved_at = datetime.now(UTC)
    report.resolution_note = payload.note
    await record_audit(
        db,
        actor=moderator,
        action=f"report.{payload.action}",
        entity_type="report",
        entity_id=str(report.id),
        meta={"video_id": str(video.id), "note": payload.note},
        ip=client_ip(request),
    )
    await db.commit()
    return {"id": str(report.id), "status": report.status.value, "video_status": video.moderation_status.value}


@router.post("/videos/{video_id}/moderate")
async def moderate_video(
    video_id: uuid.UUID,
    payload: ModerateVideoRequest,
    moderator: ModeratorUser,
    request: Request,
    db: DB,
):
    video = await db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    mapping = {
        "hide": ModerationStatus.hidden,
        "restore": ModerationStatus.visible,
        "remove": ModerationStatus.removed,
    }
    video.moderation_status = mapping[payload.action]
    video.moderated_by_id = moderator.id
    video.moderated_at = datetime.now(UTC)
    video.moderation_reason = payload.note
    await record_audit(
        db,
        actor=moderator,
        action=f"video.{payload.action}",
        entity_type="video",
        entity_id=str(video.id),
        meta={"note": payload.note},
        ip=client_ip(request),
    )
    await db.commit()
    return {"id": str(video.id), "moderation_status": video.moderation_status.value}


@router.get("/stats")
async def moderation_stats(moderator: ModeratorUser, db: DB):
    since = datetime.now(UTC) - timedelta(days=7)
    open_reports = (
        await db.scalar(select(func.count()).select_from(Report).where(Report.status == ReportStatus.open))
        or 0
    )
    hidden = (
        await db.scalar(
            select(func.count()).select_from(Video).where(Video.moderation_status == ModerationStatus.hidden)
        )
        or 0
    )
    removed = (
        await db.scalar(
            select(func.count()).select_from(Video).where(Video.moderation_status == ModerationStatus.removed)
        )
        or 0
    )
    recent = (
        await db.scalar(
            select(func.count())
            .select_from(Report)
            .where(Report.created_at >= since)
        )
        or 0
    )
    by_reason = await db.execute(
        select(Report.reason, func.count())
        .where(Report.created_at >= since)
        .group_by(Report.reason)
        .order_by(func.count().desc())
    )
    return {
        "open_reports": open_reports,
        "hidden_videos": hidden,
        "removed_videos": removed,
        "reports_last_7d": recent,
        "by_reason": [{"reason": r.value, "count": c} for r, c in by_reason.all()],
    }
