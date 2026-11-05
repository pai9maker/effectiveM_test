"""Background video pipeline: validate -> transcode -> thumbnail -> publish.

The worker is synchronous (Celery), talks to PostgreSQL through psycopg and to
S3 through boto3. ffmpeg/ffprobe do the heavy lifting.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.models.video import Video, VideoStatus
from app.services.storage import StorageError, build_object_key, get_storage
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
SyncSession = sessionmaker(engine, expire_on_commit=False)


class ProcessingError(RuntimeError):
    pass


def _ffprobe(path: str) -> dict:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                path,
            ],
            capture_output=True,
            check=True,
            timeout=120,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ProcessingError("ffprobe could not read the file") from exc
    try:
        return json.loads(result.stdout or b"{}")
    except json.JSONDecodeError as exc:
        raise ProcessingError("ffprobe returned invalid JSON") from exc


def _run(cmd: list[str], timeout: int = 3000) -> None:
    try:
        subprocess.run(cmd, capture_output=True, check=True, timeout=timeout)
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or b"")[-2000:].decode("utf-8", "replace")
        raise ProcessingError(f"ffmpeg failed: {stderr}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ProcessingError("ffmpeg timed out") from exc


def _transcode(source: str, target: str, probe: dict) -> None:
    streams = probe.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise ProcessingError("file has no video stream")

    height = int(video.get("height") or 0)
    codec = video.get("codec_name")
    audio_codec = (audio or {}).get("codec_name")
    safe_to_remux = (
        codec == "h264"
        and (audio is None or audio_codec == "aac")
        and height <= settings.transcode_target_height
        and os.path.splitext(source)[1].lower() in {".mp4", ".mov", ".m4v"}
    )
    if safe_to_remux:
        _run(["ffmpeg", "-y", "-i", source, "-c", "copy", "-movflags", "+faststart", target])
        return

    scale = f"scale=-2:'min({settings.transcode_target_height},ih)'"
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        source,
        "-vf",
        scale,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
    ]
    if audio is not None:
        cmd += ["-c:a", "aac", "-b:a", "128k", "-ac", "2"]
    else:
        cmd += ["-an"]
    cmd.append(target)
    _run(cmd)


def _make_thumbnail(source: str, target: str, duration: float) -> None:
    ts = min(max(settings.thumbnail_second, 0), max(duration / 2, 0)) if duration else 0
    _run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{ts:.2f}",
            "-i",
            source,
            "-frames:v",
            "1",
            "-vf",
            "scale=640:-2",
            "-q:v",
            "3",
            target,
        ],
        timeout=120,
    )


def _process(db: Session, video: Video) -> None:
    storage = get_storage()
    if not video.raw_key:
        raise ProcessingError("no source file uploaded")

    workdir = tempfile.mkdtemp(prefix="et-process-")
    source_path = os.path.join(workdir, "source")
    playback_path = os.path.join(workdir, "playback.mp4")
    thumb_path = os.path.join(workdir, "thumb.jpg")
    try:
        storage.download_to(video.raw_key, source_path)
        probe = _ffprobe(source_path)
        streams = probe.get("streams", [])
        duration = float(probe.get("format", {}).get("duration") or 0)
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        if video_stream is None:
            raise ProcessingError("file has no video stream")
        if duration <= 0:
            raise ProcessingError("file has zero duration")
        if duration > settings.max_video_duration_sec:
            raise ProcessingError(
                f"video is longer than the {settings.max_video_duration_sec // 3600} h limit"
            )

        _transcode(source_path, playback_path, probe)
        _make_thumbnail(playback_path, thumb_path, duration)

        playback_key = build_object_key("videos", "playback.mp4", owner_id=str(video.owner_id))
        thumb_key = build_object_key("thumbnails", "thumb.jpg", owner_id=str(video.owner_id))
        with open(playback_path, "rb") as fh:
            storage.upload_fileobj(playback_key, fh, content_type="video/mp4")
        with open(thumb_path, "rb") as fh:
            storage.upload_fileobj(thumb_key, fh, content_type="image/jpeg")

        video.playback_key = playback_key
        video.thumbnail_key = thumb_key
        video.size_bytes = os.path.getsize(playback_path)
        video.duration_sec = duration
        video.width = int(video_stream.get("width") or 0)
        video.height = int(video_stream.get("height") or 0)
        video.status = VideoStatus.ready
        video.processed_at = datetime.now(UTC)
        video.published_at = video.published_at or datetime.now(UTC)
        video.failure_reason = None
        db.commit()

        storage.delete(video.raw_key)
        video.raw_key = None
        db.commit()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


@celery_app.task(bind=True, name="videos.process", max_retries=2, default_retry_delay=30)
def process_video(self, video_id: str):
    with SyncSession() as db:
        video = db.get(Video, uuid.UUID(video_id))
        if video is None:
            logger.warning("video %s disappeared before processing", video_id)
            return {"status": "missing"}

        video.status = VideoStatus.processing
        db.commit()

        try:
            _process(db, video)
            logger.info("video %s processed", video_id)
            return {"status": "ready", "video_id": video_id}
        except (ProcessingError, StorageError) as exc:
            db.rollback()
            video = db.get(Video, uuid.UUID(video_id))
            if video is not None:
                video.status = VideoStatus.failed
                video.failure_reason = str(exc)[:500]
                db.commit()
            logger.warning("video %s failed: %s", video_id, exc)
            return {"status": "failed", "error": str(exc)}
        except Exception as exc:  # pragma: no cover - unexpected
            db.rollback()
            logger.exception("unexpected error while processing %s", video_id)
            video = db.get(Video, uuid.UUID(video_id))
            if video is not None:
                video.status = VideoStatus.failed
                video.failure_reason = "internal processing error"
                db.commit()
            if self.request.retries < self.max_retries:
                raise self.retry(exc=exc) from exc
            raise
