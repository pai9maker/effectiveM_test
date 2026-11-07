"""Channel profiles, subscriptions, avatars and profile editing."""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.deps import DB, CurrentUser, CurrentUserOptional
from app.models.social import Subscription
from app.models.user import User
from app.models.video import ModerationStatus, Video, VideoStatus, Visibility
from app.schemas import ChannelProfile, Page, UpdateProfileRequest, UserPublic, VideoCard
from app.services import videos as video_service
from app.services.images import MAX_IMAGE_BYTES, detect_image_type, svg_avatar
from app.services.serializers import channel_profile, user_public, video_card
from app.services.storage import build_object_key, get_storage

router = APIRouter(tags=["channels"])


async def _get_channel(db: DB, username: str) -> User:
    user = await db.scalar(select(User).where(User.username == username))
    if user is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    return user


async def _visible_videos_count(db: DB, channel_id) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(Video)
            .where(
                Video.owner_id == channel_id,
                Video.status == VideoStatus.ready,
                Video.visibility == Visibility.public,
                Video.moderation_status == ModerationStatus.visible,
            )
        )
        or 0
    )


@router.get("/users/{username}", response_model=ChannelProfile)
async def get_channel(username: str, db: DB, viewer: CurrentUserOptional):
    channel = await _get_channel(db, username)
    return channel_profile(
        channel,
        is_subscribed=await video_service.is_subscribed(db, viewer, channel.id),
        videos_count=await _visible_videos_count(db, channel.id),
    )


@router.get("/users/{username}/videos", response_model=Page[VideoCard])
async def channel_videos(username: str, db: DB, viewer: CurrentUserOptional, page: int = 1, page_size: int = 24):
    channel = await _get_channel(db, username)
    items, total = await video_service.channel_videos(
        db, channel.id, viewer=viewer, page=max(page, 1), page_size=min(max(page_size, 1), 60)
    )
    page = max(page, 1)
    return Page[VideoCard](
        items=[video_card(v) for v in items],
        total=total,
        page=page,
        page_size=page_size,
        has_more=page * page_size < total,
    )


@router.get("/users/{username}/avatar")
async def get_avatar(username: str, db: DB):
    user = await _get_channel(db, username)
    if user.avatar_key:
        try:
            data = get_storage().get_bytes(user.avatar_key)
            content_type, _ = detect_image_type(data) or ("image/jpeg", "")
            return Response(
                data,
                media_type=content_type,
                headers={"Cache-Control": "public, max-age=86400"},
            )
        except Exception:
            pass
    return Response(
        svg_avatar(user.username, user.display_name),
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/users/{username}/banner")
async def get_banner(username: str, db: DB):
    user = await _get_channel(db, username)
    if not user.banner_key:
        raise HTTPException(status_code=404, detail="No banner")
    data = get_storage().get_bytes(user.banner_key)
    content_type, _ = detect_image_type(data) or ("image/jpeg", "")
    return Response(data, media_type=content_type, headers={"Cache-Control": "public, max-age=86400"})


@router.patch("/users/me", response_model=UserPublic)
async def update_me(payload: UpdateProfileRequest, user: CurrentUser, db: DB):
    if payload.display_name is not None:
        name = payload.display_name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="display_name must not be empty")
        user.display_name = name
    if payload.bio is not None:
        user.bio = payload.bio.strip()
    await db.commit()
    return user_public(user)


@router.post("/users/me/avatar", response_model=UserPublic)
async def upload_avatar(user: CurrentUser, db: DB, file: UploadFile = File(...)):
    data = await file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Avatar is too large (max 4 MB)")
    detected = detect_image_type(data)
    if detected is None:
        raise HTTPException(status_code=415, detail="Only JPEG, PNG or WebP images are allowed")
    content_type, ext = detected
    key = build_object_key("avatars", f"avatar{ext}", owner_id=str(user.id))
    get_storage().put_bytes(key, data, content_type=content_type)
    if user.avatar_key:
        get_storage().delete(user.avatar_key)
    user.avatar_key = key
    await db.commit()
    return user_public(user)


@router.post("/channels/{username}/subscribe", status_code=status.HTTP_204_NO_CONTENT)
async def subscribe(username: str, user: CurrentUser, db: DB):
    channel = await _get_channel(db, username)
    if channel.id == user.id:
        raise HTTPException(status_code=400, detail="You cannot subscribe to yourself")
    result = await db.execute(
        pg_insert(Subscription)
        .values(subscriber_id=user.id, channel_id=channel.id)
        .on_conflict_do_nothing()
    )
    if result.rowcount:
        await db.execute(
            update(User).where(User.id == channel.id).values(subscribers_count=User.subscribers_count + 1)
        )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/channels/{username}/subscribe", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe(username: str, user: CurrentUser, db: DB):
    channel = await _get_channel(db, username)
    from sqlalchemy import delete

    result = await db.execute(
        delete(Subscription).where(
            Subscription.subscriber_id == user.id, Subscription.channel_id == channel.id
        )
    )
    if result.rowcount:
        await db.execute(
            update(User)
            .where(User.id == channel.id, User.subscribers_count > 0)
            .values(subscribers_count=User.subscribers_count - 1)
        )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
