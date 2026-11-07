"""End-to-end smoke test against a running EffectiveTube deployment.

Skipped by default. Run after ``./deploy.sh``:

    ET_SMOKE_URL=http://localhost:8081 pytest -m integration
"""

from __future__ import annotations

import os

import httpx
import pytest

BASE_URL = os.environ.get("ET_SMOKE_URL", "").rstrip("/")
DEMO_PASSWORD = os.environ.get("ET_DEMO_PASSWORD", "DemoPass123!")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not BASE_URL, reason="set ET_SMOKE_URL to run integration tests"),
]


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=20.0, follow_redirects=False) as http:
        yield http


def test_health_and_docs_are_reachable(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    ready = client.get("/readyz")
    assert ready.status_code == 200, ready.text
    assert ready.json()["checks"] == {"database": "ok", "redis": "ok", "storage": "ok"}
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").json()["info"]["title"].startswith("EffectiveTube")


def test_home_and_search_render(client):
    assert client.get("/").status_code == 200
    assert client.get("/results", params={"search_query": "FastAPI"}).status_code == 200


def test_anonymous_private_video_is_404(client):
    video_id = os.environ.get("ET_PRIVATE_VIDEO_ID")
    if not video_id:
        pytest.skip("set ET_PRIVATE_VIDEO_ID to check private visibility")
    assert client.get(f"/api/v1/videos/{video_id}").status_code == 404


def test_viewer_can_like_and_comment(client):
    login = client.post(
        "/api/v1/auth/login",
        json={"login": "viewer", "password": DEMO_PASSWORD},
    )
    if login.status_code == 401:
        pytest.skip("demo data is not seeded")
    assert login.status_code == 200
    assert login.json()["username"] == "viewer"

    feed = client.get("/api/v1/videos", params={"page_size": 1}).json()
    assert feed["items"], "feed is empty"
    video_id = feed["items"][0]["id"]

    headers = {"X-CSRF-Token": client.cookies.get("et_csrf", "")}

    like = client.put(f"/api/v1/videos/{video_id}/like", json={"value": 1}, headers=headers)
    assert like.status_code == 200
    assert like.json()["my_value"] == 1

    comment = client.post(
        f"/api/v1/videos/{video_id}/comments",
        json={"body": "Smoke test comment"},
        headers=headers,
    )
    assert comment.status_code == 201
    assert comment.json()["body"] == "Smoke test comment"

    # Cleanup keeps repeated runs from piling up comments.
    client.delete(f"/api/v1/videos/comments/{comment.json()['id']}", headers=headers)

    # A regular user is not allowed into the moderation queue.
    assert client.get("/moderation").status_code == 403
    assert client.post("/api/v1/videos", json={"title": "x"}, headers={}).status_code == 403


def test_stream_supports_range_requests(client):
    feed = client.get("/api/v1/videos", params={"page_size": 1}).json()
    if not feed["items"] or feed["items"][0]["status"] != "ready":
        pytest.skip("no processed video in the feed")
    video_id = feed["items"][0]["id"]
    response = client.get(
        f"/api/v1/videos/{video_id}/stream",
        headers={"Range": "bytes=0-1023"},
    )
    assert response.status_code == 206
    assert len(response.content) == 1024
    assert response.headers["content-range"].startswith("bytes 0-1023/")


def test_logout_clears_session_cookies(client):
    login = client.post(
        "/api/v1/auth/login",
        json={"login": "viewer", "password": DEMO_PASSWORD},
    )
    if login.status_code == 401:
        pytest.skip("demo data is not seeded")
    assert login.status_code == 200

    csrf = client.cookies.get("et_csrf", "")
    logout = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert logout.status_code == 204
    set_cookie = "\n".join(logout.headers.get_list("set-cookie"))
    assert "et_access=" in set_cookie and "Max-Age=0" in set_cookie
    assert "et_refresh=" in set_cookie and "et_csrf=" in set_cookie
