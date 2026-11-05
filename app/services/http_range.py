"""HTTP Range parsing for video streaming."""

from __future__ import annotations

import re

_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Return an inclusive ``(start, end)`` tuple or ``None`` when no Range given.

    Raises ``ValueError`` for syntactically valid but unsatisfiable ranges.
    """
    if not header:
        return None
    match = _RANGE_RE.match(header.strip())
    if not match:
        return None
    start_raw, end_raw = match.groups()
    if start_raw == "" and end_raw == "":
        return None
    if start_raw == "":
        suffix = int(end_raw)
        if suffix <= 0:
            raise ValueError("invalid range")
        start = max(size - suffix, 0)
        end = size - 1
    else:
        start = int(start_raw)
        end = int(end_raw) if end_raw else size - 1
    if start >= size or start > end:
        raise ValueError("range not satisfiable")
    return start, min(end, size - 1)
