"""Playlists owned by users/channels."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PlaylistVisibility(str, enum.Enum):
    public = "public"
    unlisted = "unlisted"
    private = "private"


class Playlist(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "playlists"
    __table_args__ = (Index("ix_playlists_owner", "owner_id", "created_at"),)

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    visibility: Mapped[PlaylistVisibility] = mapped_column(
        SAEnum(
            PlaylistVisibility,
            name="playlist_visibility",
            values_callable=lambda e: [i.value for i in e],
        ),
        default=PlaylistVisibility.public,
        server_default=PlaylistVisibility.public.value,
        nullable=False,
    )

    items = relationship(
        "PlaylistItem",
        back_populates="playlist",
        cascade="all, delete-orphan",
        order_by="PlaylistItem.position",
    )


class PlaylistItem(Base):
    __tablename__ = "playlist_items"
    __table_args__ = (
        UniqueConstraint("playlist_id", "video_id", name="uq_playlist_video"),
        Index("ix_playlist_items_order", "playlist_id", "position"),
    )

    playlist_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("playlists.id", ondelete="CASCADE"), primary_key=True
    )
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    playlist = relationship("Playlist", back_populates="items")
    video = relationship("Video")
