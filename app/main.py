"""Application factory: middleware, error handling, API and HTML routes."""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.redis import get_redis
from app.core.security import csrf_tokens_match
from app.db.session import engine
from app.services.storage import get_storage
from app.web.routes import router as web_router
from app.web.templating import templates

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("app")

CSRF_EXEMPT = {"/api/v1/auth/login", "/api/v1/auth/register", "/api/v1/auth/refresh"}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_runtime()
    # Object storage may start a few seconds after the app in docker-compose.
    import time

    for attempt in range(30):
        try:
            get_storage().ensure_bucket()
            break
        except Exception as exc:  # pragma: no cover - infra startup
            if attempt == 29:
                logger.error("object storage is not reachable: %s", exc)
                raise
            time.sleep(1)
    yield
    await engine.dispose()
    try:
        await get_redis().aclose()
    except Exception:
        pass


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self'; font-src 'self' data:; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        if settings.cookie_secure:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


class CsrfMiddleware(BaseHTTPMiddleware):
    """Double-submit cookie protection for cookie-authenticated API mutations."""

    async def dispatch(self, request: Request, call_next):
        if (
            request.method in UNSAFE_METHODS
            and request.url.path.startswith("/api/")
            and request.url.path not in CSRF_EXEMPT
            and not request.headers.get("authorization")
        ):
            cookie = request.cookies.get(settings.csrf_cookie_name)
            header = request.headers.get(settings.csrf_header_name)
            if not csrf_tokens_match(cookie, header):
                return JSONResponse(
                    {"detail": "CSRF token missing or invalid"}, status_code=403
                )
        return await call_next(request)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class CacheControlMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers.setdefault("Cache-Control", "public, max-age=604800")
        return response


def create_app() -> FastAPI:
    app = FastAPI(
        title=f"{settings.app_name} API",
        version="1.0.0",
        description=(
            "YouTube-like service: uploads, streaming with Range support, "
            "likes, comments, subscriptions, private videos and moderation."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(CsrfMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(CacheControlMiddleware)

    app.mount("/static", StaticFiles(directory="app/static"), name="static")
    app.include_router(api_router)
    app.include_router(web_router)

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    async def readyz():
        checks: dict[str, str] = {}
        ok = True
        try:
            async with engine.connect() as conn:
                await conn.execute(text("select 1"))
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"error: {exc}"
            ok = False
        try:
            await get_redis().ping()
            checks["redis"] = "ok"
        except Exception as exc:
            checks["redis"] = f"error: {exc}"
            ok = False
        try:
            get_storage().client.head_bucket(Bucket=settings.s3_bucket)
            checks["storage"] = "ok"
        except Exception as exc:
            checks["storage"] = f"error: {exc}"
            ok = False
        return JSONResponse({"status": "ok" if ok else "degraded", "checks": checks}, status_code=200 if ok else 503)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        if request.url.path.startswith("/api/") or request.url.path in {"/openapi.json"}:
            return JSONResponse(
                {"detail": exc.detail},
                status_code=exc.status_code,
                headers=getattr(exc, "headers", None),
            )
        if exc.status_code in (301, 302, 303, 307, 308) and exc.headers and exc.headers.get("location"):
            return RedirectResponse(exc.headers["location"], status_code=exc.status_code)
        template = "error.html"
        return templates.TemplateResponse(
            request,
            template,
            {
                "request": request,
                "user": None,
                "status_code": exc.status_code,
                "message": exc.detail if isinstance(exc.detail, str) else "Что-то пошло не так",
            },
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        if request.url.path.startswith("/api/"):
            first = exc.errors()[0] if exc.errors() else {}
            message = first.get("msg", "Validation error")
            return JSONResponse({"detail": message, "errors": exc.errors()}, status_code=422)
        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "request": request,
                "user": None,
                "status_code": 422,
                "message": "Проверьте введённые данные",
            },
            status_code=422,
        )

    return app


app = create_app()
