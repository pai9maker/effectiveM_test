"""Object-level authorization rules for videos.

Centralised here so the API, the HTML pages and the streaming proxy cannot
drift apart. The rules are intentionally explicit:

* owner and administrators always see their/any video;
* moderators see videos hidden by moderation (they must be able to review them)
  but *not* other people's private videos;
* private videos are visible to the owner and to users explicitly allow-listed
  by the owner, and to nobody else;
* public/unlisted videos must be fully processed and not hidden/removed.
"""

from __future__ import annotations

import uuid

from app.models.user import User, UserRole
from app.models.video import ModerationStatus, Video, VideoStatus, Visibility


def is_staff(user: User | None) -> bool:
    return bool(user and user.role in (UserRole.moderator, UserRole.admin))


def can_view_video(video: Video, user: User | None, *, granted_user_ids: set[uuid.UUID] | None = None) -> bool:
    if user is not None:
        if video.owner_id == user.id:
            return True
        if user.role is UserRole.admin:
            return True
        if is_staff(user) and video.moderation_status is not ModerationStatus.visible:
            return True
        if video.visibility is Visibility.private:
            return bool(granted_user_ids and user.id in granted_user_ids)
        if video.moderation_status is not ModerationStatus.visible:
            return False
    if video.moderation_status is not ModerationStatus.visible:
        return False
    return video.visibility in (Visibility.public, Visibility.unlisted)


def can_watch_video(video: Video, user: User | None, *, granted_user_ids: set[uuid.UUID] | None = None) -> bool:
    return video.status is VideoStatus.ready and can_view_video(video, user, granted_user_ids=granted_user_ids)


def can_manage_video(video: Video, user: User | None) -> bool:
    if user is None:
        return False
    return video.owner_id == user.id or user.role is UserRole.admin


def is_video_public(video: Video) -> bool:
    return (
        video.status is VideoStatus.ready
        and video.visibility is Visibility.public
        and video.moderation_status is ModerationStatus.visible
    )
