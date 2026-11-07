"""Application configuration loaded from environment variables.

All settings are validated by pydantic-settings; the app refuses to boot in
production with an insecure default secret key (see ``validate_runtime``).
"""

from __future__ import annotations

import logging
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- App ---
    app_name: str = "EffectiveTube"
    env: str = "dev"
    debug: bool = False
    base_url: str = "http://localhost:8081"

    # --- Security ---
    secret_key: str = "dev-insecure-secret-change-me"
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 14
    cookie_secure: bool = False
    cookie_samesite: str = "lax"
    access_cookie_name: str = "et_access"
    refresh_cookie_name: str = "et_refresh"
    csrf_cookie_name: str = "et_csrf"
    csrf_header_name: str = "X-CSRF-Token"

    # --- Persistence ---
    database_url: str = "postgresql+asyncpg://app:app@localhost:5432/app"
    sync_database_url: str = "postgresql+psycopg://app:app@localhost:5432/app"
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- Object storage ---
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "media"
    s3_region: str = "us-east-1"
    s3_use_ssl: bool = False
    s3_addressing_style: str = "path"

    # --- Uploads / processing ---
    max_upload_bytes: int = 2 * 1024 * 1024 * 1024
    max_video_duration_sec: int = 4 * 3600
    upload_chunk_size: int = 8 * 1024 * 1024
    transcode_target_height: int = 720
    thumbnail_second: float = 2.0

    # --- Rate limits (requests / window seconds) ---
    rate_limit_login: int = 10
    rate_limit_register: int = 5
    rate_limit_upload: int = 20
    rate_limit_comment: int = 30
    rate_limit_window_sec: int = 60

    # --- Demo ---
    demo_password: str = "DemoPass123!"

    # --- Background jobs ---
    celery_always_eager: bool = False
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None

    @field_validator("cookie_samesite")
    @classmethod
    def _check_samesite(cls, value: str) -> str:
        allowed = {"lax", "strict", "none"}
        if value.lower() not in allowed:
            raise ValueError(f"cookie_samesite must be one of {sorted(allowed)}")
        return value.lower()

    @property
    def is_production(self) -> bool:
        return self.env.lower() in {"prod", "production"}

    def validate_runtime(self) -> None:
        """Fail fast on an insecure secret, warn about weaker, deployment-specific settings.

        ``SECRET_KEY`` is a hard requirement everywhere: a predictable signing key
        lets anybody mint valid sessions. ``COOKIE_SECURE`` and the database URL are
        deployment decisions (a plain-HTTP demo is legitimate), so they only warn.
        """
        if not self.is_production:
            return
        if "change-me" in self.secret_key or len(self.secret_key) < 32:
            raise RuntimeError(
                "Unsafe production configuration: SECRET_KEY must be a random value "
                "of at least 32 characters (run ./deploy.sh or openssl rand -hex 32)"
            )
        if not self.cookie_secure:
            logger.warning(
                "COOKIE_SECURE=false: session cookies will be sent over plain HTTP. "
                "Set COOKIE_SECURE=true when serving EffectiveTube over HTTPS."
            )
        if self.database_url.startswith("postgresql+asyncpg://app:app@localhost"):
            logger.warning("DATABASE_URL still points at the local demo database")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
