"""Pydantic schemas shared by API and server-rendered pages."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.user import UserRole
from app.models.video import ModerationStatus, VideoStatus, Visibility

T = TypeVar("T")

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,40}$")
RESERVED_USERNAMES = {
    "admin",
    "administrator",
    "api",
    "auth",
    "login",
    "logout",
    "register",
    "moderation",
    "moderator",
    "root",
    "search",
    "settings",
    "studio",
    "support",
    "upload",
    "watch",
    "www",
}


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    has_more: bool


# ---------------------------------------------------------------- users/auth
class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    display_name: str
    role: UserRole = UserRole.user
    avatar_url: str | None = None
    subscribers_count: int = 0


class ChannelProfile(UserPublic):
    bio: str = ""
    banner_url: str | None = None
    is_subscribed: bool = False
    videos_count: int = 0
    created_at: datetime | None = None


class RegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=40)
    display_name: str = Field(default="", max_length=80)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("username")
    @classmethod
    def _username(cls, value: str) -> str:
        value = value.strip()
        if not USERNAME_RE.match(value):
            raise ValueError("username may contain letters, digits, dot, dash and underscore")
        if value.lower() in RESERVED_USERNAMES:
            raise ValueError("this username is reserved")
        return value

    @field_validator("password")
    @classmethod
    def _password(cls, value: str) -> str:
        if value.isdigit() or value.isalpha():
            raise ValueError("password must contain letters and digits")
        return value

    @field_validator("display_name")
    @classmethod
    def _display_name(cls, value: str, info):
        value = value.strip()
        return value or info.data.get("username", "")


class LoginRequest(BaseModel):
    login: str = Field(min_length=3, max_length=255, description="email or username")
    password: str = Field(min_length=1, max_length=128)


class UpdateProfileRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=80)
    bio: str | None = Field(default=None, max_length=1000)


# -------------------------------------------------------------------- videos
class VideoCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    visibility: Visibility = Visibility.public

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("title must not be blank")
        return value


class VideoUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    visibility: Visibility | None = None


class VideoCard(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    thumbnail_url: str | None = None
    duration_sec: float = 0
    views_count: int = 0
    likes_count: int = 0
    published_at: datetime | None = None
    created_at: datetime | None = None
    status: VideoStatus = VideoStatus.ready
    visibility: Visibility = Visibility.public
    moderation_status: ModerationStatus = ModerationStatus.visible
    owner: UserPublic


class VideoDetail(VideoCard):
    description: str = ""
    comments_count: int = 0
    dislikes_count: int = 0
    dislike_value: int = 0
    is_owner: bool = False
    can_watch: bool = True
    playback_url: str | None = None
    liked: bool = False
    saved: bool = False
    access_granted_usernames: list[str] = Field(default_factory=list)


class AccessGrantRequest(BaseModel):
    username: str = Field(min_length=3, max_length=40)


class ReportRequest(BaseModel):
    reason: str = Field(default="other", max_length=32)
    details: str = Field(default="", max_length=2000)


# ------------------------------------------------------------------- social
class CommentCreateRequest(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    parent_id: uuid.UUID | None = None

    @field_validator("body")
    @classmethod
    def _body(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("comment must not be empty")
        return value


class CommentPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    body: str
    created_at: datetime
    is_deleted: bool = False
    author: UserPublic | None = None
    replies: list["CommentPublic"] = Field(default_factory=list)
    replies_count: int = 0
    can_delete: bool = False


class LikeRequest(BaseModel):
    value: int = Field(ge=-1, le=1)


class LikeState(BaseModel):
    likes: int
    dislikes: int
    my_value: int


# ---------------------------------------------------------------- playlists
class PlaylistCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    description: str = Field(default="", max_length=1500)
    visibility: str = Field(default="public", pattern="^(public|unlisted|private)$")

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("title must not be blank")
        return value


class PlaylistUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=1500)
    visibility: str | None = Field(default=None, pattern="^(public|unlisted|private)$")


class PlaylistItemRequest(BaseModel):
    video_id: uuid.UUID


class PlaylistPublic(BaseModel):
    id: uuid.UUID
    title: str
    description: str = ""
    visibility: str = "public"
    owner: UserPublic
    items_count: int = 0
    created_at: datetime | None = None


class PlaylistDetail(PlaylistPublic):
    videos: list[VideoCard] = Field(default_factory=list)


# --------------------------------------------------------------- moderation
class ResolveReportRequest(BaseModel):
    action: str = Field(pattern="^(dismiss|hide|remove)$")
    note: str = Field(default="", max_length=1000)


class ModerateVideoRequest(BaseModel):
    action: str = Field(pattern="^(hide|restore|remove)$")
    note: str = Field(default="", max_length=1000)


class RoleUpdateRequest(BaseModel):
    role: str = Field(pattern="^(user|moderator|admin)$")


class ActiveUpdateRequest(BaseModel):
    is_active: bool
