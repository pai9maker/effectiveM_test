"""Video aggregate: metadata, processing state, visibility and ACL."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class VideoStatus(str, enum.Enum):
    uploading = "uploading"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class Visibility(str, enum.Enum):
    public = "public"
    unlisted = "unlisted"
    private = "private"


class ModerationStatus(str, enum.Enum):
    visible = "visible"
    hidden = "hidden"
    removed = "removed"


class Video(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "videos"
    __table_args__ = (
        Index("ix_videos_feed", "status", "moderation_status", "visibility", "published_at"),
        Index("ix_videos_owner_created", "owner_id", "created_at"),
        Index(
            "ix_videos_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")

    status: Mapped[VideoStatus] = mapped_column(
        SAEnum(VideoStatus, name="video_status", values_callable=lambda e: [i.value for i in e]),
        default=VideoStatus.uploading,
        server_default=VideoStatus.uploading.value,
        nullable=False,
    )
    visibility: Mapped[Visibility] = mapped_column(
        SAEnum(Visibility, name="video_visibility", values_callable=lambda e: [i.value for i in e]),
        default=Visibility.public,
        server_default=Visibility.public.value,
        nullable=False,
    )
    moderation_status: Mapped[ModerationStatus] = mapped_column(
        SAEnum(
            ModerationStatus,
            name="video_moderation_status",
            values_callable=lambda e: [i.value for i in e],
        ),
        default=ModerationStatus.visible,
        server_default=ModerationStatus.visible.value,
        nullable=False,
    )

    # Object-storage keys. Raw upload is deleted after successful processing.
    raw_key: Mapped[str | None] = mapped_column(String(512))
    playback_key: Mapped[str | None] = mapped_column(String(512))
    thumbnail_key: Mapped[str | None] = mapped_column(String(512))
    source_content_type: Mapped[str | None] = mapped_column(String(100))

    duration_sec: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    width: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    height: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")

    views_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    likes_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    dislikes_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    comments_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(String(500))

    moderated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    moderated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    moderation_reason: Mapped[str | None] = mapped_column(String(500))

    owner = relationship("User", back_populates="videos", foreign_keys=[owner_id])
    grants = relationship("VideoAccessGrant", back_populates="video", cascade="all, delete-orphan")

    @property
    def is_visible_to_public(self) -> bool:
        return (
            self.status is VideoStatus.ready
            and self.moderation_status is ModerationStatus.visible
            and self.visibility in (Visibility.public, Visibility.unlisted)
        )


class VideoAccessGrant(Base):
    """Explicit allow-list for private videos: only the owner decides."""

    __tablename__ = "video_access_grants"
    __table_args__ = (UniqueConstraint("video_id", "user_id", name="uq_video_access"),)

    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    granted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    video = relationship("Video", back_populates="grants")
    user = relationship("User", foreign_keys=[user_id])
