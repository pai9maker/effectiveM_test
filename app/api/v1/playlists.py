"""User playlists (including channel "Playlists" tab)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import joinedload, selectinload

from app.core.deps import DB, CurrentUser, CurrentUserOptional
from app.models.playlist import Playlist, PlaylistItem, PlaylistVisibility
from app.models.user import User
from app.models.video import Video
from app.schemas import (
    Page,
    PlaylistCreateRequest,
    PlaylistDetail,
    PlaylistItemRequest,
    PlaylistPublic,
    PlaylistUpdateRequest,
    VideoCard,
)
from app.services import videos as video_service
from app.services.serializers import user_public, video_card

router = APIRouter(tags=["playlists"])


def _public(playlist: Playlist, items_count: int) -> PlaylistPublic:
    return PlaylistPublic(
        id=playlist.id,
        title=playlist.title,
        description=playlist.description,
        visibility=playlist.visibility.value,
        owner=user_public(playlist.owner),
        items_count=items_count,
        created_at=playlist.created_at,
    )


async def _count(db, playlist_id: uuid.UUID) -> int:
    return (
        await db.scalar(
            select(func.count()).select_from(PlaylistItem).where(PlaylistItem.playlist_id == playlist_id)
        )
        or 0
    )


async def _load(db, playlist_id: uuid.UUID) -> Playlist:
    playlist = await db.scalar(
        select(Playlist)
        .options(joinedload(Playlist.owner), selectinload(Playlist.items))
        .where(Playlist.id == playlist_id)
    )
    if playlist is None:
        raise HTTPException(status_code=404, detail="Playlist not found")
    return playlist


@router.post("/playlists", response_model=PlaylistPublic, status_code=status.HTTP_201_CREATED)
async def create_playlist(payload: PlaylistCreateRequest, user: CurrentUser, db: DB):
    playlist = Playlist(
        owner_id=user.id,
        title=payload.title,
        description=payload.description,
        visibility=PlaylistVisibility(payload.visibility),
    )
    db.add(playlist)
    await db.commit()
    await db.refresh(playlist)
    playlist = await _load(db, playlist.id)
    return _public(playlist, 0)


@router.get("/playlists/{playlist_id}", response_model=PlaylistDetail)
async def get_playlist(playlist_id: uuid.UUID, db: DB, viewer: CurrentUserOptional):
    playlist = await _load(db, playlist_id)
    if playlist.visibility is PlaylistVisibility.private and (
        viewer is None or playlist.owner_id != viewer.id
    ):
        raise HTTPException(status_code=404, detail="Playlist not found")

    ids = [item.video_id for item in playlist.items]
    videos = await video_service.videos_by_ids(db, ids)
    visible: list[VideoCard] = []
    for item in playlist.items:
        video = videos.get(item.video_id)
        if video is None:
            continue
        grants = (
            await video_service.get_granted_user_ids(db, video.id)
            if video.visibility.value == "private"
            else None
        )
        from app.services.access import can_view_video

        if can_view_video(video, viewer, granted_user_ids=grants):
            visible.append(video_card(video))
    base = _public(playlist, len(playlist.items))
    return PlaylistDetail(**base.model_dump(), videos=visible)


@router.patch("/playlists/{playlist_id}", response_model=PlaylistPublic)
async def update_playlist(
    playlist_id: uuid.UUID, payload: PlaylistUpdateRequest, user: CurrentUser, db: DB
):
    playlist = await _load(db, playlist_id)
    if playlist.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the owner can edit this playlist")
    if payload.title is not None:
        playlist.title = " ".join(payload.title.split())
    if payload.description is not None:
        playlist.description = payload.description
    if payload.visibility is not None:
        playlist.visibility = PlaylistVisibility(payload.visibility)
    await db.commit()
    return _public(playlist, len(playlist.items))


@router.delete("/playlists/{playlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_playlist(playlist_id: uuid.UUID, user: CurrentUser, db: DB):
    playlist = await _load(db, playlist_id)
    if playlist.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the owner can delete this playlist")
    await db.delete(playlist)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/playlists/{playlist_id}/items", status_code=status.HTTP_204_NO_CONTENT)
async def add_item(playlist_id: uuid.UUID, payload: PlaylistItemRequest, user: CurrentUser, db: DB):
    playlist = await _load(db, playlist_id)
    if playlist.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the owner can edit this playlist")
    video = await db.get(Video, payload.video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")

    max_position = (
        await db.scalar(
            select(func.max(PlaylistItem.position)).where(PlaylistItem.playlist_id == playlist.id)
        )
        or 0
    )
    existing = await db.scalar(
        select(PlaylistItem).where(
            PlaylistItem.playlist_id == playlist.id, PlaylistItem.video_id == video.id
        )
    )
    if existing is None:
        db.add(PlaylistItem(playlist_id=playlist.id, video_id=video.id, position=max_position + 1))
        await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/playlists/{playlist_id}/items/{video_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_item(playlist_id: uuid.UUID, video_id: uuid.UUID, user: CurrentUser, db: DB):
    playlist = await _load(db, playlist_id)
    if playlist.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the owner can edit this playlist")
    await db.execute(
        delete(PlaylistItem).where(
            PlaylistItem.playlist_id == playlist.id, PlaylistItem.video_id == video_id
        )
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/users/{username}/playlists", response_model=Page[PlaylistPublic])
async def channel_playlists(
    username: str, db: DB, viewer: CurrentUserOptional, page: int = 1, page_size: int = 12
):
    owner = await db.scalar(select(User).where(User.username == username))
    if owner is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    page = max(page, 1)
    page_size = min(max(page_size, 1), 50)
    where = [Playlist.owner_id == owner.id]
    if viewer is None or (viewer.id != owner.id and not viewer.is_admin):
        where.append(Playlist.visibility != PlaylistVisibility.private)
    total = await db.scalar(select(func.count()).select_from(Playlist).where(*where)) or 0
    rows = await db.execute(
        select(Playlist)
        .options(joinedload(Playlist.owner), selectinload(Playlist.items))
        .where(*where)
        .order_by(Playlist.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    playlists = list(rows.unique().scalars().all())
    return Page[PlaylistPublic](
        items=[_public(p, len(p.items)) for p in playlists],
        total=total,
        page=page,
        page_size=page_size,
        has_more=page * page_size < total,
    )


@router.get("/me/playlists", response_model=list[PlaylistPublic])
async def my_playlists(user: CurrentUser, db: DB):
    rows = await db.execute(
        select(Playlist)
        .options(joinedload(Playlist.owner), selectinload(Playlist.items))
        .where(Playlist.owner_id == user.id)
        .order_by(Playlist.created_at.desc())
    )
    playlists = list(rows.unique().scalars().all())
    return [_public(p, len(p.items)) for p in playlists]
