"""Celery application for background media processing."""

from __future__ import annotations

from celery import Celery

from app.core.config import settings

broker = settings.celery_broker_url or settings.redis_url
backend = settings.celery_result_backend or settings.redis_url

celery_app = Celery("effective_tube", broker=broker, backend=backend, include=["app.workers.tasks"])
celery_app.conf.update(
    task_default_queue="video",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=3600,
    task_soft_time_limit=3300,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    result_expires=3600,
    timezone="UTC",
)
