"""Server-rendered HTML pages (Jinja2). JS enhances them through the JSON API."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload, selectinload

from app.core.config import settings
from app.core.deps import CurrentUserOptional, DB, Paging
from app.models.moderation import AuditLog, Report, ReportStatus
from app.models.playlist import Playlist, PlaylistItem, PlaylistVisibility
from app.models.user import User
from app.models.video import ModerationStatus, Video, VideoAccessGrant, VideoStatus, Visibility
from app.services import videos as video_service
from app.services.access import can_manage_video, can_view_video, can_watch_video
from app.services.serializers import card_dict, comment_dict, user_public
from app.services.storage import get_storage
from app.web.templating import templates

router = APIRouter(include_in_schema=False)


def _ctx(request: Request, user: User | None, **extra: Any) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "request": request,
        "user": user,
        "csrf_token": request.cookies.get(settings.csrf_cookie_name, ""),
        "current_year": datetime.now(UTC).year,
        "app_name": settings.app_name,
    }
    ctx.update(extra)
    return ctx


def _login_redirect(request: Request) -> RedirectResponse:
    target = request.url.path
    if request.url.query:
        target += "?" + request.url.query
    return RedirectResponse(f"/login?next={target}", status_code=303)


def _cards(videos: list[Video]) -> list[dict]:
    return [card_dict(v) for v in videos]


# --------------------------------------------------------------------- home
@router.get("/")
async def home(request: Request, db: DB, viewer: CurrentUserOptional, sort: str = "new"):
    page = 1
    items, total = await video_service.feed(db, page=page, page_size=24, sort=sort)
    return templates.TemplateResponse(
        request,
        "index.html",
        _ctx(request, viewer, videos=_cards(items), total=total, sort=sort, active="home"),
    )


# -------------------------------------------------------------------- watch
@router.get("/watch/{video_id}")
async def watch(video_id: uuid.UUID, request: Request, db: DB, viewer: CurrentUserOptional):
    video = await video_service.get_video(db, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Видео не найдено")
    grants = (
        await video_service.get_granted_user_ids(db, video.id)
        if video.visibility is Visibility.private
        else None
    )
    if not can_view_video(video, viewer, granted_user_ids=grants):
        raise HTTPException(status_code=404, detail="Видео не найдено")
    can_watch = can_watch_video(video, viewer, granted_user_ids=grants)

    my_like = await video_service.like_state(db, video.id, viewer)
    subscribed = await video_service.is_subscribed(db, viewer, video.owner_id)
    roots, comments_total = await video_service.comment_tree(db, video.id, viewer=viewer, page=1, page_size=20)
    replies = await video_service.replies_for(db, [c.id for c in roots])
    recs = await video_service.recommendations(db, video, limit=12)

    granted_names: list[str] = []
    is_owner = bool(viewer and video.owner_id == viewer.id)
    if is_owner or (viewer and viewer.is_admin):
        rows = await db.execute(
            select(User.username)
            .join(VideoAccessGrant, VideoAccessGrant.user_id == User.id)
            .where(VideoAccessGrant.video_id == video.id)
        )
        granted_names = list(rows.scalars().all())

    my_playlists = []
    if viewer is not None:
        pl_rows = await db.execute(
            select(Playlist).where(Playlist.owner_id == viewer.id).order_by(Playlist.created_at.desc())
        )
        my_playlists = list(pl_rows.scalars().all())

    return templates.TemplateResponse(
        request,
        "watch.html",
        _ctx(
            request,
            viewer,
            video=card_dict(video),
            video_id=str(video.id),
            description=video.description,
            visibility=video.visibility.value,
            owner_subs=video.owner.subscribers_count,
            can_watch=can_watch,
            is_owner=is_owner,
            can_manage=can_manage_video(video, viewer),
            my_like=my_like,
            likes=video.likes_count,
            dislikes=video.dislikes_count,
            subscribed=subscribed,
            comments=[comment_dict(c, viewer, replies.get(c.id, [])) for c in roots],
            comments_total=comments_total,
            recommendations=_cards(recs),
            granted_names=granted_names,
            my_playlists=[{"id": str(p.id), "title": p.title} for p in my_playlists],
            moderation_status=video.moderation_status.value,
            video_status=video.status.value,
            failure_reason=video.failure_reason,
            active="",
        ),
    )


# ------------------------------------------------------------------ channel
@router.get("/@{username}")
async def channel(username: str, request: Request, db: DB, viewer: CurrentUserOptional, tab: str = "videos"):
    owner = await db.scalar(select(User).where(User.username == username))
    if owner is None:
        raise HTTPException(status_code=404, detail="Канал не найден")

    videos, videos_total = await video_service.channel_videos(
        db, owner.id, viewer=viewer, page=1, page_size=24
    )
    subscribed = await video_service.is_subscribed(db, viewer, owner.id)

    pl_rows = await db.execute(
        select(Playlist)
        .options(selectinload(Playlist.items))
        .where(
            Playlist.owner_id == owner.id,
            Playlist.visibility != PlaylistVisibility.private
            if not (viewer and (viewer.id == owner.id or viewer.is_admin))
            else True,
        )
        .order_by(Playlist.created_at.desc())
        .limit(12)
    )
    playlists = list(pl_rows.scalars().all())

    return templates.TemplateResponse(
        request,
        "channel.html",
        _ctx(
            request,
            viewer,
            channel=owner,
            channel_public=user_public(owner),
            videos=_cards(videos),
            videos_total=videos_total,
            playlists=playlists,
            subscribed=subscribed,
            is_owner=bool(viewer and viewer.id == owner.id),
            tab=tab,
            active="",
        ),
    )


# ------------------------------------------------------------------- search
@router.get("/results")
async def results(request: Request, db: DB, viewer: CurrentUserOptional, search_query: str = "", page: int = 1):
    query = search_query.strip()[:200]
    videos: list[Video] = []
    total = 0
    channels: list[User] = []
    if query:
        videos, total = await video_service.search_videos(db, query, page=max(page, 1), page_size=20)
        channels = await video_service.search_channels(db, query, limit=4)
    return templates.TemplateResponse(
        request,
        "search.html",
        _ctx(
            request,
            viewer,
            query=query,
            videos=_cards(videos),
            channels=[user_public(u) for u in channels],
            total=total,
            page=max(page, 1),
            active="",
        ),
    )


# ------------------------------------------------------------------- upload
@router.get("/upload")
async def upload_page(request: Request, db: DB, viewer: CurrentUserOptional):
    if viewer is None:
        return _login_redirect(request)
    pl_rows = await db.execute(
        select(Playlist).where(Playlist.owner_id == viewer.id).order_by(Playlist.created_at.desc())
    )
    return templates.TemplateResponse(
        request,
        "upload.html",
        _ctx(
            request,
            viewer,
            playlists=[{"id": str(p.id), "title": p.title} for p in pl_rows.scalars().all()],
            max_upload_mb=settings.max_upload_bytes // (1024 * 1024),
            active="upload",
        ),
    )


# ------------------------------------------------------------------- studio
@router.get("/studio")
async def studio(request: Request, db: DB, viewer: CurrentUserOptional):
    if viewer is None:
        return _login_redirect(request)
    rows = await db.execute(
        select(Video)
        .where(Video.owner_id == viewer.id)
        .order_by(Video.created_at.desc())
        .limit(200)
    )
    own = list(rows.scalars().all())
    pl_rows = await db.execute(
        select(Playlist)
        .options(selectinload(Playlist.items))
        .where(Playlist.owner_id == viewer.id)
        .order_by(Playlist.created_at.desc())
    )
    return templates.TemplateResponse(
        request,
        "studio.html",
        _ctx(
            request,
            viewer,
            videos=[
                {
                    **card_dict(v),
                    "video_status": v.status.value,
                    "moderation": v.moderation_status.value,
                    "created": v.created_at,
                }
                for v in own
            ],
            playlists=list(pl_rows.scalars().all()),
            active="studio",
        ),
    )


# ------------------------------------------------------------------ library
@router.get("/subscriptions")
async def subscriptions_page(request: Request, db: DB, viewer: CurrentUserOptional):
    if viewer is None:
        return _login_redirect(request)
    items = await video_service.followed_videos(db, viewer)
    return templates.TemplateResponse(
        request,
        "library.html",
        _ctx(request, viewer, title="Подписки", videos=_cards(items), empty_text="Вы ещё ни на кого не подписаны", active="subscriptions"),
    )


@router.get("/history")
async def history_page(request: Request, db: DB, viewer: CurrentUserOptional):
    if viewer is None:
        return _login_redirect(request)
    items = await video_service.history_for(db, viewer)
    return templates.TemplateResponse(
        request,
        "library.html",
        _ctx(request, viewer, title="История просмотров", videos=_cards(items), empty_text="Вы ещё не смотрели видео", active="history"),
    )


@router.get("/liked")
async def liked_page(request: Request, db: DB, viewer: CurrentUserOptional):
    if viewer is None:
        return _login_redirect(request)
    items = await video_service.liked_videos(db, viewer)
    return templates.TemplateResponse(
        request,
        "library.html",
        _ctx(request, viewer, title="Понравившиеся видео", videos=_cards(items), empty_text="Пока нет видео, которым вы поставили лайк", active="liked"),
    )


# ----------------------------------------------------------------- playlist
@router.get("/playlist/{playlist_id}")
async def playlist_page(playlist_id: uuid.UUID, request: Request, db: DB, viewer: CurrentUserOptional):
    playlist = await db.scalar(select(Playlist).where(Playlist.id == playlist_id))
    if playlist is None:
        raise HTTPException(status_code=404, detail="Плейлист не найден")
    if playlist.visibility is PlaylistVisibility.private and (
        viewer is None or playlist.owner_id != viewer.id
    ):
        raise HTTPException(status_code=404, detail="Плейлист не найден")
    rows = await db.execute(
        select(Video, PlaylistItem.position)
        .join(PlaylistItem, PlaylistItem.video_id == Video.id)
        .options(joinedload(Video.owner))
        .where(PlaylistItem.playlist_id == playlist.id)
        .order_by(PlaylistItem.position)
    )
    pairs = [(row[0], row[1]) for row in rows.unique().all()]
    videos = []
    for video, _position in pairs:
        if can_view_video(video, viewer):
            videos.append(card_dict(video))
    owner = await db.get(User, playlist.owner_id)
    return templates.TemplateResponse(
        request,
        "playlist.html",
        _ctx(
            request,
            viewer,
            playlist=playlist,
            owner=owner,
            videos=videos,
            is_owner=bool(viewer and playlist.owner_id == viewer.id),
            active="",
        ),
    )


# --------------------------------------------------------------- moderation
@router.get("/moderation")
async def moderation_page(request: Request, db: DB, viewer: CurrentUserOptional, status_filter: str = "open"):
    if viewer is None:
        return _login_redirect(request)
    if not viewer.is_moderator:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    try:
        report_status = ReportStatus(status_filter)
    except ValueError:
        report_status = ReportStatus.open

    rows = await db.execute(
        select(Report, Video, User)
        .join(Video, Video.id == Report.video_id)
        .join(User, User.id == Report.reporter_id)
        .where(Report.status == report_status)
        .order_by(Report.created_at.asc())
        .limit(100)
    )
    reports = [
        {
            "id": str(report.id),
            "reason": report.reason.value,
            "details": report.details,
            "created": report.created_at,
            "reporter": reporter.username,
            "video": card_dict(video),
        }
        for report, video, reporter in rows.all()
    ]
    open_count = await db.scalar(
        select(func.count()).select_from(Report).where(Report.status == ReportStatus.open)
    )
    hidden_count = await db.scalar(
        select(func.count()).select_from(Video).where(Video.moderation_status == ModerationStatus.hidden)
    )
    removed_count = await db.scalar(
        select(func.count()).select_from(Video).where(Video.moderation_status == ModerationStatus.removed)
    )
    return templates.TemplateResponse(
        request,
        "moderation.html",
        _ctx(
            request,
            viewer,
            reports=reports,
            status_filter=report_status.value,
            stats={"open": open_count, "hidden": hidden_count, "removed": removed_count},
            active="moderation",
        ),
    )


# -------------------------------------------------------------------- admin
@router.get("/admin")
async def admin_page(request: Request, db: DB, viewer: CurrentUserOptional):
    if viewer is None:
        return _login_redirect(request)
    if not viewer.is_admin:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    rows = await db.execute(select(User).order_by(User.created_at.desc()).limit(200))
    users = list(rows.scalars().all())
    audit_rows = await db.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(50))
    return templates.TemplateResponse(
        request,
        "admin.html",
        _ctx(
            request,
            viewer,
            users=users,
            audit=list(audit_rows.scalars().all()),
            active="admin",
        ),
    )


# --------------------------------------------------------------------- auth
@router.get("/login")
async def login_page(request: Request, viewer: CurrentUserOptional):
    if viewer is not None:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        _ctx(request, None, next=request.query_params.get("next", "/"), mode="login"),
    )


@router.get("/register")
async def register_page(request: Request, viewer: CurrentUserOptional):
    if viewer is not None:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request,
        "register.html",
        _ctx(request, None, next=request.query_params.get("next", "/"), mode="register"),
    )
