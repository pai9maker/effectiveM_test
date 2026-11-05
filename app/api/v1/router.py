from fastapi import APIRouter

from app.api.v1 import admin, auth, channels, moderation, playlists, search, videos

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(channels.router)
api_router.include_router(videos.router)
api_router.include_router(playlists.router)
api_router.include_router(moderation.router)
api_router.include_router(admin.router)
api_router.include_router(search.router)
