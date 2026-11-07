"""Search over video titles and channel names."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.core.deps import DB, CurrentUserOptional, Paging
from app.models.social import Subscription
from app.schemas import UserPublic, VideoCard
from app.services import videos as video_service
from app.services.serializers import user_public, video_card

router = APIRouter(tags=["search"])


@router.get("/search")
async def search(q: str, paging: Paging, db: DB, viewer: CurrentUserOptional, type: str = "all"):
    query = q.strip()[:200]
    if not query:
        return {"query": query, "videos": [], "channels": [], "total": 0, "page": paging.page}

    videos: list[VideoCard] = []
    channels: list[UserPublic] = []
    total = 0

    if type in {"all", "video"}:
        items, total = await video_service.search_videos(
            db, query, page=paging.page, page_size=paging.page_size
        )
        videos = [video_card(v) for v in items]
    if type in {"all", "channel"}:
        found = await video_service.search_channels(db, query, limit=5)
        channels = [user_public(u) for u in found]

    result = {
        "query": query,
        "videos": [v.model_dump(mode="json") for v in videos],
        "channels": [c.model_dump(mode="json") for c in channels],
        "total": total,
        "page": paging.page,
        "page_size": paging.page_size,
        "has_more": paging.offset + len(videos) < total,
    }
    if viewer is not None:
        followed = await db.execute(
            select(Subscription.channel_id).where(Subscription.subscriber_id == viewer.id)
        )
        result["subscribed_channel_ids"] = [str(cid) for cid in followed.scalars().all()]
    return result
