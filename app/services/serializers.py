"""Serialisers bridging ORM objects to API schemas and template dictionaries."""

from __future__ import annotations

import uuid

from app.models.social import Comment
from app.models.user import User
from app.models.video import Video
from app.schemas import ChannelProfile, CommentPublic, UserPublic, VideoCard, VideoDetail
from app.services import formatting as fmt


def avatar_url(user: User) -> str:
    return f"/api/v1/users/{user.username}/avatar"


def user_public(user: User) -> UserPublic:
    return UserPublic(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        avatar_url=avatar_url(user),
        subscribers_count=user.subscribers_count,
    )


def channel_profile(user: User, *, is_subscribed: bool, videos_count: int) -> ChannelProfile:
    return ChannelProfile(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        avatar_url=avatar_url(user),
        subscribers_count=user.subscribers_count,
        bio=user.bio,
        banner_url=f"/api/v1/users/{user.username}/banner" if user.banner_key else None,
        is_subscribed=is_subscribed,
        videos_count=videos_count,
        created_at=user.created_at,
    )


def video_card(video: Video) -> VideoCard:
    return VideoCard(
        id=video.id,
        title=video.title,
        thumbnail_url=f"/api/v1/videos/{video.id}/thumbnail" if video.thumbnail_key else None,
        duration_sec=video.duration_sec,
        views_count=video.views_count,
        likes_count=video.likes_count,
        published_at=video.published_at,
        created_at=video.created_at,
        status=video.status,
        visibility=video.visibility,
        moderation_status=video.moderation_status,
        owner=user_public(video.owner),
    )


def video_detail(
    video: Video,
    *,
    my_like: int = 0,
    is_owner: bool = False,
    can_watch: bool = True,
    granted_usernames: list[str] | None = None,
) -> VideoDetail:
    base = video_card(video)
    return VideoDetail(
        **base.model_dump(),
        description=video.description,
        comments_count=video.comments_count,
        dislikes_count=video.dislikes_count,
        dislike_value=my_like,
        is_owner=is_owner,
        can_watch=can_watch,
        playback_url=f"/api/v1/videos/{video.id}/stream" if can_watch else None,
        liked=my_like == 1,
        access_granted_usernames=granted_usernames or [],
    )


def comment_public(comment: Comment, *, viewer: User | None = None, replies: list[Comment] | None = None) -> CommentPublic:
    can_delete = False
    if viewer is not None:
        can_delete = comment.author_id == viewer.id or viewer.is_moderator
    author = user_public(comment.author) if comment.author and not comment.is_deleted else None
    return CommentPublic(
        id=comment.id,
        body="" if comment.is_deleted else comment.body,
        created_at=comment.created_at,
        is_deleted=comment.is_deleted,
        author=author,
        replies=[comment_public(r, viewer=viewer) for r in (replies or [])],
        replies_count=len(replies or []),
        can_delete=can_delete,
    )


# --------------------------------------------------------------- UI helpers
def card_dict(video: Video) -> dict:
    """Dictionary consumed by Jinja templates."""
    published = video.published_at or video.created_at
    return {
        "id": str(video.id),
        "title": video.title,
        "description": video.description,
        "owner": video.owner.display_name,
        "owner_username": video.owner.username,
        "thumbnail_url": f"/api/v1/videos/{video.id}/thumbnail" if video.thumbnail_key else None,
        "duration": fmt.duration(video.duration_sec),
        "duration_sec": video.duration_sec,
        "views": fmt.views(video.views_count),
        "views_count": video.views_count,
        "age": fmt.time_ago(published),
        "published_at": published,
        "status": video.status.value,
        "visibility": video.visibility.value,
        "moderation_status": video.moderation_status.value,
        "avatar_url": avatar_url(video.owner),
        "owner_initials": fmt.initials(video.owner.display_name),
        "owner_url": f"/@{video.owner.username}",
        "url": f"/watch/{video.id}",
    }


def comment_dict(comment: Comment, viewer: User | None, replies: list[Comment] | None = None) -> dict:
    can_delete = bool(
        viewer
        and not comment.is_deleted
        and (comment.author_id == viewer.id or viewer.is_moderator)
    )
    return {
        "id": str(comment.id),
        "body": comment.body if not comment.is_deleted else "Комментарий удалён",
        "is_deleted": comment.is_deleted,
        "author_name": comment.author.display_name if comment.author and not comment.is_deleted else "Пользователь",
        "author_username": comment.author.username if comment.author and not comment.is_deleted else "",
        "author_url": f"/@{comment.author.username}" if comment.author and not comment.is_deleted else "#",
        "avatar_url": avatar_url(comment.author) if comment.author and not comment.is_deleted else None,
        "initials": fmt.initials(comment.author.display_name) if comment.author else "?",
        "age": fmt.time_ago(comment.created_at),
        "can_delete": can_delete,
        "replies": [comment_dict(r, viewer) for r in (replies or [])],
        "parent_id": str(comment.parent_id) if comment.parent_id else None,
    }


def uuid_str(value: uuid.UUID | str | None) -> str:
    return str(value) if value else ""
