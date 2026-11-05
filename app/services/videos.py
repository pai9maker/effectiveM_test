"""Read/query services shared by the JSON API and the HTML pages."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Select, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core.redis import get_redis
from app.models.social import Comment, Subscription, VideoLike, ViewEvent, WatchHistory
from app.models.user import User
from app.models.video import ModerationStatus, Video, VideoAccessGrant, VideoStatus, Visibility

PUBLIC_FILTER = (
    Video.status == VideoStatus.ready,
    Video.moderation_status == ModerationStatus.visible,
    Video.visibility == Visibility.public,
)


def _base_query() -> Select:
    return select(Video).options(joinedload(Video.owner))


async def get_video(db: AsyncSession, video_id: uuid.UUID) -> Video | None:
    result = await db.execute(_base_query().where(Video.id == video_id))
    return result.unique().scalar_one_or_none()


async def get_granted_user_ids(db: AsyncSession, video_id: uuid.UUID) -> set[uuid.UUID]:
    rows = await db.execute(
        select(VideoAccessGrant.user_id).where(VideoAccessGrant.video_id == video_id)
    )
    return set(rows.scalars().all())


async def feed(
    db: AsyncSession, *, page: int = 1, page_size: int = 24, sort: str = "new"
) -> tuple[list[Video], int]:
    total = await db.scalar(select(func.count()).select_from(Video).where(*PUBLIC_FILTER)) or 0
    order = (
        Video.views_count.desc(), Video.published_at.desc()
    ) if sort == "popular" else (
        Video.published_at.desc().nullslast(),
        Video.created_at.desc(),
    )
    rows = await db.execute(
        _base_query()
        .where(*PUBLIC_FILTER)
        .order_by(*order)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(rows.unique().scalars().all()), total


async def search_videos(
    db: AsyncSession, query: str, *, page: int = 1, page_size: int = 24
) -> tuple[list[Video], int]:
    term = query.strip()
    if not term:
        return [], 0
    pattern = f"%{term}%"
    where = (*PUBLIC_FILTER, Video.title.ilike(pattern))
    total = await db.scalar(select(func.count()).select_from(Video).where(*where)) or 0
    similarity = func.similarity(Video.title, term)
    rows = await db.execute(
        _base_query()
        .where(*where)
        .order_by(similarity.desc(), Video.views_count.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(rows.unique().scalars().all()), total


async def channel_videos(
    db: AsyncSession,
    owner_id: uuid.UUID,
    *,
    viewer: User | None,
    page: int = 1,
    page_size: int = 24,
) -> tuple[list[Video], int]:
    is_owner_or_staff = viewer is not None and (viewer.id == owner_id or viewer.is_moderator)
    where = [Video.owner_id == owner_id, Video.status == VideoStatus.ready]
    if not is_owner_or_staff:
        where += [
            Video.visibility == Visibility.public,
            Video.moderation_status == ModerationStatus.visible,
        ]
    total = await db.scalar(select(func.count()).select_from(Video).where(*where)) or 0
    rows = await db.execute(
        _base_query()
        .where(*where)
        .order_by(Video.published_at.desc().nullslast(), Video.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(rows.unique().scalars().all()), total


async def recommendations(
    db: AsyncSession, video: Video, *, limit: int = 12
) -> list[Video]:
    rows = await db.execute(
        _base_query()
        .where(*PUBLIC_FILTER, Video.id != video.id)
        .order_by((Video.owner_id == video.owner_id).desc(), Video.views_count.desc())
        .limit(limit)
    )
    return list(rows.unique().scalars().all())


async def most_viewed(db: AsyncSession, *, limit: int = 12) -> list[Video]:
    rows = await db.execute(
        _base_query().where(*PUBLIC_FILTER).order_by(Video.views_count.desc()).limit(limit)
    )
    return list(rows.unique().scalars().all())


async def videos_by_ids(db: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, Video]:
    if not ids:
        return {}
    rows = await db.execute(_base_query().where(Video.id.in_(ids)))
    return {v.id: v for v in rows.unique().scalars().all()}


# ------------------------------------------------------------------ comments
async def comment_tree(
    db: AsyncSession, video_id: uuid.UUID, *, viewer: User | None, page: int = 1, page_size: int = 20
) -> tuple[list[Comment], int]:
    total = (
        await db.scalar(
            select(func.count())
            .select_from(Comment)
            .where(Comment.video_id == video_id, Comment.parent_id.is_(None))
        )
        or 0
    )
    rows = await db.execute(
        select(Comment)
        .options(joinedload(Comment.author))
        .where(Comment.video_id == video_id, Comment.parent_id.is_(None))
        .order_by(Comment.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    roots = list(rows.unique().scalars().all())
    if not roots:
        return [], total
    replies = await db.execute(
        select(Comment)
        .options(joinedload(Comment.author))
        .where(Comment.parent_id.in_([c.id for c in roots]))
        .order_by(Comment.created_at.asc())
    )
    by_parent: dict[uuid.UUID, list[Comment]] = {}
    for reply in replies.unique().scalars().all():
        by_parent.setdefault(reply.parent_id, []).append(reply)  # type: ignore[arg-type]
    for root in roots:
        root.__dict__["replies"] = by_parent.get(root.id, [])
    return roots, total


async def replies_for(db: AsyncSession, parent_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Comment]]:
    if not parent_ids:
        return {}
    rows = await db.execute(
        select(Comment)
        .options(joinedload(Comment.author))
        .where(Comment.parent_id.in_(parent_ids))
        .order_by(Comment.created_at.asc())
    )
    out: dict[uuid.UUID, list[Comment]] = {}
    for reply in rows.unique().scalars().all():
        out.setdefault(reply.parent_id, []).append(reply)  # type: ignore[arg-type]
    return out


# --------------------------------------------------------------- interactions
async def like_state(db: AsyncSession, video_id: uuid.UUID, user: User | None) -> int:
    if user is None:
        return 0
    value = await db.scalar(
        select(VideoLike.value).where(VideoLike.video_id == video_id, VideoLike.user_id == user.id)
    )
    return int(value) if value is not None else 0


async def is_subscribed(db: AsyncSession, subscriber: User | None, channel_id: uuid.UUID) -> bool:
    if subscriber is None:
        return False
    found = await db.scalar(
        select(Subscription.subscriber_id).where(
            Subscription.subscriber_id == subscriber.id, Subscription.channel_id == channel_id
        )
    )
    return found is not None


async def subscriber_count(db: AsyncSession, channel_id: uuid.UUID) -> int:
    return (
        await db.scalar(
            select(func.count()).select_from(Subscription).where(Subscription.channel_id == channel_id)
        )
        or 0
    )


async def record_view(db: AsyncSession, video: Video, viewer_key: str, user: User | None) -> bool:
    """Idempotent view registration: one view per viewer per video per 6 hours."""
    redis_key = f"view:{video.id}:{viewer_key}"
    try:
        first = await get_redis().set(redis_key, "1", ex=6 * 3600, nx=True)
        if not first:
            return False
    except Exception:
        first = True  # Redis down: still count, ledger dedupes
    bucket = datetime.now(UTC).strftime("%Y-%m-%dT%H")
    try:
        await db.execute(
            text(
                "INSERT INTO view_events (video_id, viewer_key, bucket) "
                "VALUES (:video_id, :viewer_key, :bucket) ON CONFLICT DO NOTHING"
            ),
            {"video_id": str(video.id), "viewer_key": viewer_key, "bucket": bucket},
        )
        await db.execute(
            update(Video).where(Video.id == video.id).values(views_count=Video.views_count + 1)
        )
    except Exception:
        await db.rollback()
        return False
    if user is not None:
        await upsert_history(db, user.id, video.id)
    await db.commit()
    return True


async def upsert_history(db: AsyncSession, user_id: uuid.UUID, video_id: uuid.UUID) -> None:
    await db.execute(
        text(
            "INSERT INTO watch_history (user_id, video_id, watched_at) "
            "VALUES (:u, :v, now()) ON CONFLICT (user_id, video_id) "
            "DO UPDATE SET watched_at = now()"
        ),
        {"u": str(user_id), "v": str(video_id)},
    )


async def history_for(db: AsyncSession, user: User, *, limit: int = 60) -> list[Video]:
    rows = await db.execute(
        select(Video)
        .join(WatchHistory, WatchHistory.video_id == Video.id)
        .options(joinedload(Video.owner))
        .where(WatchHistory.user_id == user.id, *PUBLIC_FILTER)
        .order_by(WatchHistory.watched_at.desc())
        .limit(limit)
    )
    return list(rows.unique().scalars().all())


async def liked_videos(db: AsyncSession, user: User, *, page: int = 1, page_size: int = 24) -> list[Video]:
    rows = await db.execute(
        _base_query()
        .join(VideoLike, VideoLike.video_id == Video.id)
        .where(VideoLike.user_id == user.id, VideoLike.value == 1, *PUBLIC_FILTER)
        .order_by(VideoLike.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(rows.unique().scalars().all())


async def followed_videos(db: AsyncSession, user: User, *, limit: int = 48) -> list[Video]:
    rows = await db.execute(
        _base_query()
        .join(Subscription, Subscription.channel_id == Video.owner_id)
        .where(Subscription.subscriber_id == user.id, *PUBLIC_FILTER)
        .order_by(Video.published_at.desc().nullslast())
        .limit(limit)
    )
    return list(rows.unique().scalars().all())


async def search_channels(db: AsyncSession, query: str, *, limit: int = 5) -> list[User]:
    rows = await db.execute(
        select(User)
        .where(or_(User.username.ilike(f"%{query}%"), User.display_name.ilike(f"%{query}%")))
        .order_by(User.subscribers_count.desc())
        .limit(limit)
    )
    return list(rows.scalars().all())


async def playlist_videos(db: AsyncSession, playlist_id: uuid.UUID) -> list[tuple[Video, int]]:
    from app.models.playlist import PlaylistItem

    rows = await db.execute(
        select(Video, PlaylistItem.position)
        .join(PlaylistItem, PlaylistItem.video_id == Video.id)
        .options(joinedload(Video.owner))
        .where(PlaylistItem.playlist_id == playlist_id)
        .order_by(PlaylistItem.position)
    )
    return [(row[0], row[1]) for row in rows.unique().all()]
