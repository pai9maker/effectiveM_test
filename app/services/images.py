"""Small image helpers: generated SVG avatars and magic-byte sniffing."""

from __future__ import annotations

import hashlib
from html import escape

PALETTE = [
    ("#e53935", "#8e0000"),
    ("#1e88e5", "#0d47a1"),
    ("#43a047", "#1b5e20"),
    ("#fb8c00", "#e65100"),
    ("#8e24aa", "#4a148c"),
    ("#00acc1", "#006064"),
    ("#3949ab", "#1a237e"),
    ("#7cb342", "#33691e"),
]


def svg_avatar(seed: str, label: str) -> bytes:
    digest = hashlib.sha256(seed.encode()).digest()
    start, end = PALETTE[digest[0] % len(PALETTE)]
    text = escape((label or seed or "?")[:2].upper())
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160" viewBox="0 0 160 160">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0%" stop-color="{start}"/><stop offset="100%" stop-color="{end}"/>
</linearGradient></defs>
<rect width="160" height="160" rx="80" fill="url(#g)"/>
<text x="80" y="80" dy="0.35em" text-anchor="middle" fill="#fff"
 font-family="Roboto, Arial, sans-serif" font-size="64" font-weight="600">{text}</text>
</svg>"""
    return svg.encode()


def detect_image_type(data: bytes) -> tuple[str, str] | None:
    """Return ``(content_type, extension)`` based on magic bytes."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return None


MAX_IMAGE_BYTES = 4 * 1024 * 1024
