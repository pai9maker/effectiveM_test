"""Users, channels and the role model."""

from __future__ import annotations

import enum

from sqlalchemy import Boolean, CheckConstraint, Enum as SAEnum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class UserRole(str, enum.Enum):
    user = "user"
    moderator = "moderator"
    admin = "admin"


ROLE_RANK: dict[str, int] = {"user": 0, "moderator": 1, "admin": 2}


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("char_length(username) >= 3", name="ck_users_username_len"),
        CheckConstraint("subscribers_count >= 0", name="ck_users_subs_non_negative"),
    )

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    avatar_key: Mapped[str | None] = mapped_column(String(512))
    banner_key: Mapped[str | None] = mapped_column(String(512))
    bio: Mapped[str] = mapped_column(Text, default="", server_default="")
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role", values_callable=lambda e: [i.value for i in e]),
        default=UserRole.user,
        server_default=UserRole.user.value,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    subscribers_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    videos = relationship(
        "Video",
        back_populates="owner",
        cascade="all, delete-orphan",
        foreign_keys="Video.owner_id",
    )

    @property
    def is_moderator(self) -> bool:
        return ROLE_RANK.get(self.role.value, 0) >= ROLE_RANK["moderator"]

    @property
    def is_admin(self) -> bool:
        return self.role is UserRole.admin
