"""S3-compatible object storage adapter (MinIO in docker-compose).

All media is private in the bucket: playback, thumbnails and avatars are proxied
through the application, which enforces access rules before touching storage.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from functools import lru_cache
from typing import BinaryIO

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from app.core.config import settings

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1024 * 1024  # 1 MiB streaming chunks


class StorageError(RuntimeError):
    pass


class Storage:
    def __init__(self) -> None:
        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            use_ssl=settings.s3_use_ssl,
            config=BotoConfig(
                signature_version="s3v4",
                s3={"addressing_style": settings.s3_addressing_style},
                retries={"max_attempts": 5, "mode": "standard"},
                connect_timeout=5,
                read_timeout=60,
            ),
        )

    # ------------------------------------------------------------------ bucket
    def ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            try:
                self.client.create_bucket(Bucket=self.bucket)
                logger.info("created bucket %s", self.bucket)
            except ClientError as exc:  # pragma: no cover - infra failure
                raise StorageError(f"cannot create bucket {self.bucket}: {exc}") from exc

    # ------------------------------------------------------------------ write
    def upload_fileobj(
        self, key: str, fileobj: BinaryIO, *, content_type: str = "application/octet-stream"
    ) -> int:
        try:
            self.client.upload_fileobj(
                fileobj,
                self.bucket,
                key,
                ExtraArgs={"ContentType": content_type},
                Config=TransferConfig(
                    multipart_threshold=settings.upload_chunk_size,
                    multipart_chunksize=settings.upload_chunk_size,
                    max_concurrency=4,
                ),
            )
        except ClientError as exc:
            raise StorageError(f"upload failed: {exc}") from exc
        return self.size(key)

    def put_bytes(self, key: str, data: bytes, *, content_type: str) -> None:
        try:
            self.client.put_object(
                Bucket=self.bucket, Key=key, Body=data, ContentType=content_type
            )
        except ClientError as exc:
            raise StorageError(f"put failed: {exc}") from exc

    def download_to(self, key: str, path: str) -> int:
        try:
            self.client.download_file(self.bucket, key, path)
        except ClientError as exc:
            raise StorageError(f"download failed: {exc}") from exc
        return os.path.getsize(path)

    # ------------------------------------------------------------------- read
    def size(self, key: str) -> int:
        try:
            return int(self.client.head_object(Bucket=self.bucket, Key=key)["ContentLength"])
        except ClientError as exc:
            raise StorageError(f"head failed: {exc}") from exc

    def get_object(self, key: str, byte_range: str | None = None) -> dict:
        kwargs = {"Bucket": self.bucket, "Key": key}
        if byte_range:
            kwargs["Range"] = byte_range
        try:
            return self.client.get_object(**kwargs)
        except ClientError as exc:
            raise StorageError(f"get failed: {exc}") from exc

    def get_bytes(self, key: str) -> bytes:
        obj = self.get_object(key)
        return obj["Body"].read()

    def iter_chunks(self, key: str, byte_range: str | None = None) -> Iterator[bytes]:
        obj = self.get_object(key, byte_range)
        body = obj["Body"]
        try:
            while True:
                chunk = body.read(CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk
        finally:
            body.close()

    # ----------------------------------------------------------------- delete
    def delete(self, key: str | None) -> None:
        if not key:
            return
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:  # deletion is best-effort
            logger.warning("cannot delete %s: %s", key, exc)

    def presigned_get(self, key: str, expires_in: int = 3600) -> str:  # pragma: no cover
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires_in
        )


@lru_cache
def get_storage() -> Storage:
    return Storage()


def build_object_key(prefix: str, filename: str, *, owner_id: str) -> str:
    """Deterministic, collision-free key layout: prefix/owner/xx/hash.ext"""
    import hashlib
    import uuid

    digest = hashlib.sha256(f"{uuid.uuid4()}-{filename}".encode()).hexdigest()
    ext = os.path.splitext(filename)[1].lower()[:10] or ".bin"
    return f"{prefix}/{owner_id}/{digest[:2]}/{digest}{ext}"
