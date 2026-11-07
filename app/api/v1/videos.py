"""Video lifecycle: create, upload, stream, likes, comments, ACL, reports."""

from __future__ import annotations

import hashlib
import uuid

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from app.core.config import settings
from app.core.deps import DB, CurrentUser, CurrentUserOptional, Paging
from app.models.moderation import Report, ReportReason, ReportStatus
from app.models.social import Comment, VideoLike
from app.models.user import User
from app.models.video import (
    ModerationStatus,
    Video,
    VideoAccessGrant,
    VideoStatus,
    Visibility,
)
from app.schemas import (
    AccessGrantRequest,
    CommentCreateRequest,
    CommentPublic,
    LikeRequest,
    LikeState,
    Page,
    ReportRequest,
    VideoCard,
    VideoCreateRequest,
    VideoDetail,
    VideoUpdateRequest,
)
from app.services import videos as video_service
from app.services.access import can_manage_video, can_view_video, can_watch_video, is_video_public
from app.services.http_range import parse_range
from app.services.queue import enqueue_video_processing
from app.services.rate_limit import client_ip, rate_limit
from app.services.serializers import comment_public, video_card, video_detail
from app.services.storage import StorageError, build_object_key, get_storage
from app.services.video_formats import ALLOWED_CONTENT_TYPES, sniff_container

router = APIRouter(prefix="/videos", tags=["videos"])

MAX_RANGE_CHUNK = 4 * 1024 * 1024


def _viewer_key(request: Request, user: User | None) -> str:
    if user is not None:
        return f"u:{user.id}"
    ua = request.headers.get("user-agent", "")
    return "a:" + hashlib.sha256(f"{client_ip(request)}|{ua}".encode()).hexdigest()[:32]


async def _get_video(db: DB, video_id: uuid.UUID) -> Video:
    video = await video_service.get_video(db, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    return video


async def _assert_can_view(db: DB, video: Video, user: User | None) -> bool:
    grants = await video_service.get_granted_user_ids(db, video.id) if video.visibility is Visibility.private else None
    if not can_view_video(video, user, granted_user_ids=grants):
        # 404 instead of 403 so private video ids are not confirmed to outsiders.
        raise HTTPException(status_code=404, detail="Video not found")
    return can_watch_video(video, user, granted_user_ids=grants)


def _placeholder_thumbnail(title: str) -> bytes:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360">'
        '<rect width="640" height="360" fill="#202020"/>'
        '<text x="320" y="190" text-anchor="middle" fill="#909090" font-family="Roboto,Arial" '
        f'font-size="28">{title[:40]}</text></svg>'
    ).encode()


# --------------------------------------------------------------------- feed
@router.get("", response_model=Page[VideoCard])
async def list_videos(paging: Paging, db: DB, sort: str = "new"):
    items, total = await video_service.feed(
        db, page=paging.page, page_size=paging.page_size, sort=sort if sort in {"new", "popular"} else "new"
    )
    return Page[VideoCard](
        items=[video_card(v) for v in items],
        total=total,
        page=paging.page,
        page_size=paging.page_size,
        has_more=paging.offset + len(items) < total,
    )


@router.post("", response_model=VideoDetail, status_code=status.HTTP_201_CREATED)
async def create_video(payload: VideoCreateRequest, user: CurrentUser, db: DB):
    video = Video(
        owner_id=user.id,
        title=payload.title,
        description=payload.description,
        visibility=payload.visibility,
        status=VideoStatus.uploading,
        moderation_status=ModerationStatus.visible,
    )
    db.add(video)
    await db.commit()
    await db.refresh(video)
    loaded = await _get_video(db, video.id)
    return video_detail(loaded, is_owner=True, can_watch=False)


# ------------------------------------------------------------------- upload
@router.post("/{video_id}/file", status_code=status.HTTP_202_ACCEPTED)
async def upload_video_file(
    video_id: uuid.UUID,
    user: CurrentUser,
    db: DB,
    background: BackgroundTasks,
    file: UploadFile = File(...),
):
    video = await _get_video(db, video_id)
    if not can_manage_video(video, user):
        raise HTTPException(status_code=403, detail="You cannot upload to this video")
    if video.status not in (VideoStatus.uploading, VideoStatus.failed):
        raise HTTPException(status_code=409, detail="File already uploaded for this video")

    if file.content_type and file.content_type.split(";")[0] not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported media type")

    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    if size == 0:
        raise HTTPException(status_code=400, detail="Empty file")
    if size > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="File exceeds the upload limit")

    head = file.file.read(64)
    file.file.seek(0)
    container = sniff_container(head)
    if container is None:
        raise HTTPException(status_code=415, detail="File is not a recognised video container")

    key = build_object_key("raw", file.filename or f"upload.{container}", owner_id=str(user.id))
    try:
        get_storage().upload_fileobj(
            key, file.file, content_type=file.content_type or "application/octet-stream"
        )
    except StorageError as exc:
        raise HTTPException(status_code=502, detail="Storage is unavailable") from exc

    if video.raw_key:
        get_storage().delete(video.raw_key)
    video.raw_key = key
    video.size_bytes = size
    video.source_content_type = file.content_type
    video.status = VideoStatus.processing
    video.failure_reason = None
    await db.commit()
    enqueue_video_processing(str(video.id))
    return {"id": str(video.id), "status": video.status.value}


# -------------------------------------------------------------------- stream
def _stream_headers(video: Video, *, extra: dict | None = None) -> dict:
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": "video/mp4",
        "Cache-Control": "public, max-age=3600" if is_video_public(video) else "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if extra:
        headers.update(extra)
    return headers


@router.get("/{video_id}/stream")
async def stream_video(video_id: uuid.UUID, request: Request, db: DB, viewer: CurrentUserOptional):
    video = await _get_video(db, video_id)
    can_watch = await _assert_can_view(db, video, viewer)
    if not can_watch or not video.playback_key:
        raise HTTPException(status_code=409, detail="Video is not ready for playback")

    size = video.size_bytes or 0
    try:
        byte_range = parse_range(request.headers.get("range"), size)
    except ValueError:
        return Response(
            status_code=416,
            headers={"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"},
        )

    if byte_range is not None:
        start, end = byte_range
        storage_range = f"bytes={start}-{end}"
        try:
            obj = get_storage().get_object(video.playback_key, storage_range)
        except StorageError as exc:
            raise HTTPException(status_code=502, detail="Storage is unavailable") from exc
        headers = _stream_headers(
            video,
            extra={
                "Content-Range": f"bytes {start}-{end}/{size}",
                "Content-Length": str(end - start + 1),
            },
        )
        return StreamingResponse(
            _iter_body(obj["Body"]),
            status_code=206,
            media_type="video/mp4",
            headers=headers,
        )

    try:
        obj = get_storage().get_object(video.playback_key)
    except StorageError as exc:
        raise HTTPException(status_code=502, detail="Storage is unavailable") from exc
    headers = _stream_headers(video, extra={"Content-Length": str(size)})
    return StreamingResponse(_iter_body(obj["Body"]), media_type="video/mp4", headers=headers)


@router.head("/{video_id}/stream")
async def head_stream(video_id: uuid.UUID, db: DB, viewer: CurrentUserOptional):
    video = await _get_video(db, video_id)
    can_watch = await _assert_can_view(db, video, viewer)
    if not can_watch:
        raise HTTPException(status_code=409, detail="Video is not ready for playback")
    return Response(
        status_code=200,
        headers=_stream_headers(video, extra={"Content-Length": str(video.size_bytes or 0)}),
    )


def _iter_body(body) -> "object":
    def iterator():
        try:
            while True:
                chunk = body.read(MAX_RANGE_CHUNK)
                if not chunk:
                    break
                yield chunk
        finally:
            body.close()

    return iterator()


@router.get("/{video_id}/thumbnail")
async def video_thumbnail(video_id: uuid.UUID, db: DB, viewer: CurrentUserOptional):
    video = await _get_video(db, video_id)
    await _assert_can_view(db, video, viewer)
    if not video.thumbnail_key:
        return Response(_placeholder_thumbnail(video.title), media_type="image/svg+xml")
    try:
        data = get_storage().get_bytes(video.thumbnail_key)
    except StorageError:
        return Response(_placeholder_thumbnail(video.title), media_type="image/svg+xml")
    return Response(
        data,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "public, max-age=86400" if is_video_public(video) else "private, max-age=3600"
        },
    )


# ---------------------------------------------------------------- metadata
@router.get("/{video_id}", response_model=VideoDetail)
async def get_video(video_id: uuid.UUID, db: DB, viewer: CurrentUserOptional):
    video = await _get_video(db, video_id)
    can_watch = await _assert_can_view(db, video, viewer)
    my_like = await video_service.like_state(db, video.id, viewer)
    granted: list[str] = []
    if viewer is not None and (video.owner_id == viewer.id or viewer.is_admin):
        rows = await db.execute(
            select(User.username)
            .join(VideoAccessGrant, VideoAccessGrant.user_id == User.id)
            .where(VideoAccessGrant.video_id == video.id)
        )
        granted = list(rows.scalars().all())
    return video_detail(
        video,
        my_like=my_like,
        is_owner=bool(viewer and video.owner_id == viewer.id),
        can_watch=can_watch,
        granted_usernames=granted,
    )


@router.patch("/{video_id}", response_model=VideoDetail)
async def update_video(video_id: uuid.UUID, payload: VideoUpdateRequest, user: CurrentUser, db: DB):
    video = await _get_video(db, video_id)
    if not can_manage_video(video, user):
        raise HTTPException(status_code=403, detail="You cannot edit this video")
    if payload.title is not None:
        video.title = " ".join(payload.title.split())
    if payload.description is not None:
        video.description = payload.description
    if payload.visibility is not None:
        video.visibility = payload.visibility
    await db.commit()
    await db.refresh(video)
    return video_detail(video, is_owner=True, can_watch=video.status is VideoStatus.ready)


@router.delete("/{video_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_video(video_id: uuid.UUID, user: CurrentUser, db: DB):
    video = await _get_video(db, video_id)
    if not can_manage_video(video, user):
        raise HTTPException(status_code=403, detail="You cannot delete this video")
    for key in (video.playback_key, video.thumbnail_key, video.raw_key):
        get_storage().delete(key)
    await db.delete(video)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------- views
@router.post("/{video_id}/view")
async def register_view(video_id: uuid.UUID, request: Request, db: DB, viewer: CurrentUserOptional):
    video = await _get_video(db, video_id)
    await _assert_can_view(db, video, viewer)
    counted = await video_service.record_view(db, video, _viewer_key(request, viewer), viewer)
    refreshed = await db.get(Video, video.id)
    return {"counted": counted, "views": refreshed.views_count if refreshed else video.views_count}


# ------------------------------------------------------------------- likes
@router.put("/{video_id}/like", response_model=LikeState)
async def like_video(video_id: uuid.UUID, payload: LikeRequest, user: CurrentUser, db: DB):
    video = await _get_video(db, video_id)
    await _assert_can_view(db, video, user)

    existing = await db.get(VideoLike, (user.id, video.id))
    old = existing.value if existing else 0
    new = payload.value
    if old != new:
        if new == 0:
            await db.delete(existing)
        elif existing is None:
            db.add(VideoLike(user_id=user.id, video_id=video.id, value=new))
        else:
            existing.value = new
        like_delta = (1 if new == 1 else 0) - (1 if old == 1 else 0)
        dislike_delta = (1 if new == -1 else 0) - (1 if old == -1 else 0)
        await db.execute(
            update(Video)
            .where(Video.id == video.id)
            .values(
                likes_count=func.greatest(Video.likes_count + like_delta, 0),
                dislikes_count=func.greatest(Video.dislikes_count + dislike_delta, 0),
            )
        )
        await db.commit()
    updated = await db.get(Video, video.id)
    assert updated is not None
    return LikeState(likes=updated.likes_count, dislikes=updated.dislikes_count, my_value=new)


# ---------------------------------------------------------------- comments
@router.get("/{video_id}/comments", response_model=Page[CommentPublic])
async def list_comments(video_id: uuid.UUID, paging: Paging, db: DB, viewer: CurrentUserOptional):
    video = await _get_video(db, video_id)
    await _assert_can_view(db, video, viewer)
    roots, total = await video_service.comment_tree(
        db, video.id, viewer=viewer, page=paging.page, page_size=paging.page_size
    )
    replies = await video_service.replies_for(db, [c.id for c in roots])
    return Page[CommentPublic](
        items=[comment_public(c, viewer=viewer, replies=replies.get(c.id, [])) for c in roots],
        total=total,
        page=paging.page,
        page_size=paging.page_size,
        has_more=paging.offset + len(roots) < total,
    )


@router.post("/{video_id}/comments", response_model=CommentPublic, status_code=status.HTTP_201_CREATED)
async def create_comment(
    video_id: uuid.UUID, payload: CommentCreateRequest, request: Request, user: CurrentUser, db: DB
):
    await rate_limit(request, "comment", settings.rate_limit_comment, identity=str(user.id))
    video = await _get_video(db, video_id)
    can_watch = await _assert_can_view(db, video, user)
    if not can_watch:
        raise HTTPException(status_code=409, detail="Comments are available only for ready videos")

    parent = None
    if payload.parent_id is not None:
        parent = await db.get(Comment, payload.parent_id)
        if parent is None or parent.video_id != video.id:
            raise HTTPException(status_code=422, detail="Parent comment not found")
        if parent.parent_id is not None:
            raise HTTPException(status_code=422, detail="Only one level of replies is supported")

    comment = Comment(video_id=video.id, author_id=user.id, parent_id=payload.parent_id, body=payload.body)
    db.add(comment)
    await db.execute(
        update(Video).where(Video.id == video.id).values(comments_count=Video.comments_count + 1)
    )
    await db.commit()
    await db.refresh(comment)
    comment = await db.scalar(
        select(Comment).options(joinedload(Comment.author)).where(Comment.id == comment.id)
    )
    return comment_public(comment, viewer=user)


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(comment_id: uuid.UUID, user: CurrentUser, db: DB):
    comment = await db.get(Comment, comment_id)
    if comment is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    video = await db.get(Video, comment.video_id)
    is_video_owner = video is not None and video.owner_id == user.id
    if comment.author_id != user.id and not is_video_owner and not user.is_moderator:
        raise HTTPException(status_code=403, detail="You cannot delete this comment")
    if not comment.is_deleted:
        comment.is_deleted = True
        comment.body = ""
        await db.execute(
            update(Video)
            .where(Video.id == comment.video_id)
            .values(comments_count=func.greatest(Video.comments_count - 1, 0))
        )
        await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------- private ACL
@router.get("/{video_id}/access", response_model=list[str])
async def list_access(video_id: uuid.UUID, user: CurrentUser, db: DB):
    video = await _get_video(db, video_id)
    if video.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Only the owner can manage access")
    rows = await db.execute(
        select(User.username)
        .join(VideoAccessGrant, VideoAccessGrant.user_id == User.id)
        .where(VideoAccessGrant.video_id == video.id)
        .order_by(User.username)
    )
    return list(rows.scalars().all())


@router.post("/{video_id}/access", status_code=status.HTTP_204_NO_CONTENT)
async def grant_access(video_id: uuid.UUID, payload: AccessGrantRequest, user: CurrentUser, db: DB):
    video = await _get_video(db, video_id)
    if video.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the owner can manage access")
    target = await db.scalar(select(User).where(User.username == payload.username))
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == user.id:
        raise HTTPException(status_code=400, detail="The owner already has access")
    db.add(VideoAccessGrant(video_id=video.id, user_id=target.id, granted_by_id=user.id))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{video_id}/access/{username}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_access(video_id: uuid.UUID, username: str, user: CurrentUser, db: DB):
    video = await _get_video(db, video_id)
    if video.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the owner can manage access")
    target = await db.scalar(select(User).where(User.username == username))
    if target is not None:
        await db.execute(
            delete(VideoAccessGrant).where(
                VideoAccessGrant.video_id == video.id, VideoAccessGrant.user_id == target.id
            )
        )
        await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ----------------------------------------------------------------- reports
@router.post("/{video_id}/report", status_code=status.HTTP_201_CREATED)
async def report_video(video_id: uuid.UUID, payload: ReportRequest, request: Request, user: CurrentUser, db: DB):
    await rate_limit(request, "report", 10, identity=str(user.id))
    video = await _get_video(db, video_id)
    await _assert_can_view(db, video, user)
    if video.owner_id == user.id:
        raise HTTPException(status_code=400, detail="You cannot report your own video")
    try:
        reason = ReportReason(payload.reason)
    except ValueError:
        raise HTTPException(status_code=422, detail="Unknown report reason") from None
    existing = await db.scalar(
        select(Report.id).where(
            Report.video_id == video.id,
            Report.reporter_id == user.id,
            Report.status == ReportStatus.open,
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="You already reported this video")
    report = Report(
        reporter_id=user.id, video_id=video.id, reason=reason, details=payload.details.strip()
    )
    db.add(report)
    await db.commit()
    return {"id": str(report.id), "status": report.status.value}


@router.get("/{video_id}/recommendations", response_model=list[VideoCard])
async def recommendations(video_id: uuid.UUID, db: DB, viewer: CurrentUserOptional):
    video = await _get_video(db, video_id)
    await _assert_can_view(db, video, viewer)
    items = await video_service.recommendations(db, video, limit=12)
    return [video_card(v) for v in items]
