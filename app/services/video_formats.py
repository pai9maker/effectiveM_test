"""Fast container sniffing used before accepting an upload (ffprobe is the final judge)."""

from __future__ import annotations

ALLOWED_CONTENT_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/webm",
    "video/x-matroska",
    "video/x-msvideo",
    "application/octet-stream",
}


def sniff_container(head: bytes) -> str | None:
    """Best-effort container detection from the first bytes of the file."""
    if len(head) >= 12 and head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in {b"qt  ", b"qt\x20\x20"}:
            return "mov"
        return "mp4"
    if head.startswith(b"\x1aE\xdf\xa3"):
        return "webm"
    if head.startswith(b"RIFF") and head[8:12] == b"AVI ":
        return "avi"
    return None
