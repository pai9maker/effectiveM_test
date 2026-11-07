"""Input validation and Russian UI formatting."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.models.user import UserRole
from app.schemas import (
    CommentCreateRequest,
    RegisterRequest,
    VideoCreateRequest,
    VideoUpdateRequest,
)
from app.services import formatting as fmt


def test_register_normalises_username_and_display_name():
    payload = RegisterRequest(
        email="User@Example.com",
        username="  good_user  ",
        display_name="   ",
        password="SuperSecret123",
    )
    assert payload.username == "good_user"
    assert payload.display_name == "good_user"


@pytest.mark.parametrize("username", ["ab", "has space", "админ", "-starts-with-dash-" * 4])
def test_register_rejects_bad_usernames(username):
    with pytest.raises(ValidationError):
        RegisterRequest(
            email="user@example.com",
            username=username,
            password="SuperSecret123",
        )


@pytest.mark.parametrize("username", ["admin", "Moderator", "api", "upload"])
def test_register_rejects_reserved_usernames(username):
    with pytest.raises(ValidationError):
        RegisterRequest(
            email="user@example.com",
            username=username,
            password="SuperSecret123",
        )


@pytest.mark.parametrize("password", ["short", "onlyletters", "1234567890123"])
def test_register_rejects_weak_passwords(password):
    with pytest.raises(ValidationError):
        RegisterRequest(
            email="user@example.com",
            username="someone",
            password=password,
        )


def test_video_title_is_normalised_and_blank_rejected():
    payload = VideoCreateRequest(title="  Hello   world \n")
    assert payload.title == "Hello world"
    with pytest.raises(ValidationError):
        VideoCreateRequest(title="   ")
    with pytest.raises(ValidationError):
        VideoCreateRequest(title="x" * 201)


def test_video_update_allows_partial_payloads():
    payload = VideoUpdateRequest(visibility=None, title="New title")
    assert payload.title == "New title"
    assert payload.visibility is None


def test_comment_body_is_trimmed_and_blank_rejected():
    assert CommentCreateRequest(body="  hi there  ").body == "hi there"
    with pytest.raises(ValidationError):
        CommentCreateRequest(body="   ")
    with pytest.raises(ValidationError):
        CommentCreateRequest(body="x" * 2001)


def test_user_role_ranks():
    from app.models.user import ROLE_RANK

    assert ROLE_RANK["user"] < ROLE_RANK["moderator"] < ROLE_RANK["admin"]
    assert UserRole("moderator") is UserRole.moderator


def test_russian_plurals():
    assert fmt.plural(1, "просмотр", "просмотра", "просмотров") == "просмотр"
    assert fmt.plural(2, "просмотр", "просмотра", "просмотров") == "просмотра"
    assert fmt.plural(5, "просмотр", "просмотра", "просмотров") == "просмотров"
    assert fmt.plural(11, "просмотр", "просмотра", "просмотров") == "просмотров"
    assert fmt.plural(21, "просмотр", "просмотра", "просмотров") == "просмотр"


def test_compact_numbers():
    assert fmt.compact_number(999) == "999"
    assert fmt.compact_number(1_500) == "1,5 тыс."
    assert fmt.compact_number(2_000_000) == "2 млн"


def test_duration_formatting():
    assert fmt.duration(0) == "0:00"
    assert fmt.duration(65) == "1:05"
    assert fmt.duration(3725) == "1:02:05"


def test_time_ago_is_human_readable():
    now = datetime.now(UTC)
    assert fmt.time_ago(now) == "только что"
    assert fmt.time_ago(now - timedelta(minutes=5)) == "5 минут назад"
    assert fmt.time_ago(now - timedelta(hours=2)) == "2 часа назад"
    assert fmt.time_ago(now - timedelta(days=3)) == "3 дня назад"
    assert fmt.time_ago(now - timedelta(days=60)) == "2 месяца назад"


def test_uuid_helpers_are_stable():
    assert fmt.initials("Иван Зритель") == "ИЗ"
    assert fmt.initials("techlab") == "T"
    assert fmt.date_ru(datetime(2026, 11, 7, tzinfo=UTC)) == "07.11.2026"
