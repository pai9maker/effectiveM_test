"""Jinja2 environment shared by all HTML pages."""

from __future__ import annotations

from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from app.core.config import settings
from app.services import formatting as fmt

ICONS: dict[str, str] = {
    "menu": '<path d="M3 6h18M3 12h18M3 18h18"/>',
    "home": '<path d="M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1h-5v-6H10v6H5a1 1 0 0 1-1-1z"/>',
    "shorts": '<path d="M14.5 3.5 9 10h4l-3 10 8-11h-4l3-5.5z"/>',
    "subscriptions": '<path d="M4 7h16M6 3h12M5 11h14v9a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1z"/><path d="m10 14 4 2.5-4 2.5z"/>',
    "library": '<path d="M4 5h10v14H4zM16 5h4v14h-4z"/><path d="M6 8h6M6 12h6"/>',
    "history": '<path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/><path d="M12 7v5l3 2"/>',
    "liked": '<path d="M7 10v11H4a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1z"/><path d="m7 10 4-8a2 2 0 0 1 2 2v4h6a2 2 0 0 1 2 2.3l-1.4 8A2 2 0 0 1 17.6 20H7"/>',
    "videos": '<path d="m10 8 6 4-6 4z"/><rect x="3" y="4" width="18" height="16" rx="2"/>',
    "upload": '<path d="M12 16V4m0 0-4 4m4-4 4 4"/><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-4.3-4.3"/>',
    "bell": '<path d="M6 9a6 6 0 1 1 12 0c0 5 2 6 2 6H4s2-1 2-6"/><path d="M10 20a2 2 0 0 0 4 0"/>',
    "like": '<path d="M7 10v11H4a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1z"/><path d="m7 10 4-8a2 2 0 0 1 2 2v4h6a2 2 0 0 1 2 2.3l-1.4 8A2 2 0 0 1 17.6 20H7"/>',
    "dislike": '<path d="M17 14V3h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1z"/><path d="m17 14-4 8a2 2 0 0 1-2-2v-4H5a2 2 0 0 1-2-2.3l1.4-8A2 2 0 0 1 6.4 4H17"/>',
    "share": '<path d="M4 12v7a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-7"/><path d="M12 16V3m0 0-4 4m4-4 4 4"/>',
    "save": '<path d="M6 4h12a1 1 0 0 1 1 1v16l-7-4-7 4V5a1 1 0 0 1 1-1z"/>',
    "more": '<circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/>',
    "play": '<path d="M8 5.5v13l11-6.5z"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "trash": '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>',
    "edit": '<path d="m4 16 1-4L16 1l4 4L9 16z"/><path d="M14 3l4 4"/><path d="M4 20h16"/>',
    "eye": '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "flag": '<path d="M5 21V4h9l-1 3h7l-2 5 2 5h-8l-1-3H5"/>',
    "check": '<path d="m4 12 5 5 11-11"/>',
    "x": '<path d="M5 5l14 14M19 5 5 19"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    "shield": '<path d="M12 3 20 6v6c0 5-3.4 8.2-8 9-4.6-.8-8-4-8-9V6z"/><path d="m9 12 2 2 4-4"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 5a3.5 3.5 0 0 1 0 7M18 14a6 6 0 0 1 3.5 6"/>',
    "logout": '<path d="M15 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4"/><path d="M10 16l-4-4 4-4M6 12h10"/>',
    "lock": '<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
    "film": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>',
    "chart": '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
}

templates = Jinja2Templates(directory="app/templates")

templates.env.globals.update(
    app_name=settings.app_name,
    ICONS=ICONS,
    svg_icon=lambda name: Markup(
        f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" '
        f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS.get(name, "")}</svg>'
    ),
    youtube_play=Markup(
        '<svg viewBox="0 0 90 20" class="logo-wordmark" aria-hidden="true">'
        '<path fill="#FF0000" d="M27.97 3.12A3.6 3.6 0 0 0 25.4.55C23.2 0 14 0 14 0S4.8 0 2.6.55A3.6 3.6 0 0 0 .03 3.12 37.6 37.6 0 0 0 0 10a37.6 37.6 0 0 0 .03 6.88 3.6 3.6 0 0 0 2.57 2.57C4.8 20 14 20 14 20s9.2 0 11.4-.55a3.6 3.6 0 0 0 2.57-2.57A37.6 37.6 0 0 0 28 10a37.6 37.6 0 0 0-.03-6.88z"/>'
        '<path fill="#fff" d="M11.2 14.29 18.47 10l-7.27-4.29z"/>'
        "</svg>"
    ),
)

templates.env.filters.update(
    duration=fmt.duration,
    views=fmt.views,
    subscribers=fmt.subscribers,
    comments_count=fmt.comments,
    videos_count=fmt.videos,
    compact=fmt.compact_number,
    time_ago=fmt.time_ago,
    date_ru=fmt.date_ru,
    initials=fmt.initials,
    plural=fmt.plural,
)
