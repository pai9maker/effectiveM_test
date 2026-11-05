"""Task enqueueing facade (Celery in production, synchronous in tests/eager mode)."""

from __future__ import annotations

from app.core.config import settings


def enqueue_video_processing(video_id: str) -> None:
    from app.workers.tasks import process_video

    if settings.celery_always_eager:
        process_video.apply(args=[video_id])
    else:
        process_video.delay(video_id)
