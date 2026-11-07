"""Object-level authorization is the security core of EffectiveTube.

These tests pin the visibility matrix down without touching a database: the
rules live in a pure function so they can be verified exhaustively.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.user import User, UserRole
from app.models.video import ModerationStatus, Video, VideoStatus, Visibility
from app.services.access import (
    can_manage_video,
    can_view_video,
    can_watch_video,
    is_video_public,
)


def make_user(role: UserRole = UserRole.user) -> User:
    return User(id=uuid.uuid4(), username=f"u-{uuid.uuid4().hex[:8]}", role=role)


def make_video(
    owner: User,
    *,
    visibility: Visibility = Visibility.public,
    moderation: ModerationStatus = ModerationStatus.visible,
    status: VideoStatus = VideoStatus.ready,
) -> Video:
    return Video(
        id=uuid.uuid4(),
        owner_id=owner.id,
        title="Test video",
        visibility=visibility,
        moderation_status=moderation,
        status=status,
        owner=owner,
    )


@pytest.fixture()
def owner() -> User:
    return make_user()


@pytest.fixture()
def stranger() -> User:
    return make_user()


@pytest.fixture()
def moderator() -> User:
    return make_user(UserRole.moderator)


@pytest.fixture()
def admin() -> User:
    return make_user(UserRole.admin)


def test_public_ready_video_is_visible_to_everyone(owner, stranger):
    video = make_video(owner)
    assert can_view_video(video, None)
    assert can_view_video(video, stranger)
    assert can_watch_video(video, stranger)


def test_unlisted_video_is_visible_but_not_public(owner):
    video = make_video(owner, visibility=Visibility.unlisted)
    assert can_view_video(video, None)
    assert not is_video_public(video)


def test_private_video_is_hidden_from_strangers(owner, stranger):
    video = make_video(owner, visibility=Visibility.private)
    assert not can_view_video(video, None)
    assert not can_view_video(video, stranger)
    assert not can_watch_video(video, stranger)


def test_private_video_is_visible_to_owner_and_granted_users(owner, stranger):
    video = make_video(owner, visibility=Visibility.private)
    assert can_view_video(video, owner)
    assert can_watch_video(video, owner)
    assert can_view_video(video, stranger, granted_user_ids={stranger.id})
    assert can_watch_video(video, stranger, granted_user_ids={stranger.id})
    other = make_user()
    assert not can_view_video(video, stranger, granted_user_ids={other.id})


def test_private_video_is_visible_to_admin_but_not_to_moderator(owner, admin, moderator, stranger):
    video = make_video(owner, visibility=Visibility.private)
    assert can_view_video(video, admin)
    # Moderators moderate content, they do not get access to private videos.
    assert not can_view_video(video, moderator)
    assert not can_view_video(video, moderator, granted_user_ids={stranger.id})


def test_hidden_video_is_visible_to_owner_moderator_and_admin(owner, moderator, admin, stranger):
    video = make_video(owner, moderation=ModerationStatus.hidden)
    assert can_view_video(video, owner)
    assert can_view_video(video, moderator)
    assert can_view_video(video, admin)
    assert not can_view_video(video, stranger)
    assert not can_view_video(video, None)


def test_removed_video_stays_visible_to_staff_only(owner, moderator, stranger):
    video = make_video(owner, moderation=ModerationStatus.removed)
    assert can_view_video(video, moderator)
    assert not can_view_video(video, stranger)


def test_hidden_public_video_is_not_public(owner):
    video = make_video(owner, moderation=ModerationStatus.hidden)
    assert not is_video_public(video)


def test_unprocessed_video_cannot_be_watched(owner):
    video = make_video(owner, status=VideoStatus.processing)
    assert can_view_video(video, owner)
    assert not can_watch_video(video, owner)
    assert not is_video_public(video)


def test_manage_rights_belong_to_owner_and_admin(owner, stranger, admin, moderator):
    video = make_video(owner)
    assert can_manage_video(video, owner)
    assert can_manage_video(video, admin)
    assert not can_manage_video(video, moderator)
    assert not can_manage_video(video, stranger)
    assert not can_manage_video(video, None)
