"""HTTP Range parsing tests — video seeking depends on correct 206 responses."""

from __future__ import annotations

import pytest

from app.services.http_range import parse_range


def test_no_range_header_means_full_response():
    assert parse_range(None, 1000) is None
    assert parse_range("", 1000) is None


def test_closed_range():
    assert parse_range("bytes=0-499", 1000) == (0, 499)
    assert parse_range("bytes=500-999", 1000) == (500, 999)


def test_open_ended_range():
    assert parse_range("bytes=500-", 1000) == (500, 999)


def test_suffix_range():
    assert parse_range("bytes=-200", 1000) == (800, 999)
    # A suffix longer than the file starts at zero.
    assert parse_range("bytes=-5000", 1000) == (0, 999)


def test_end_is_clamped_to_file_size():
    assert parse_range("bytes=900-100000", 1000) == (900, 999)


def test_unsatisfiable_range_raises():
    with pytest.raises(ValueError):
        parse_range("bytes=1000-", 1000)
    with pytest.raises(ValueError):
        parse_range("bytes=600-500", 1000)


def test_malformed_or_unsupported_ranges_are_ignored():
    assert parse_range("items=0-10", 1000) is None
    assert parse_range("bytes=abc-def", 1000) is None
    assert parse_range("bytes=-", 1000) is None
    assert parse_range("bytes=0-1,5-6", 1000) is None
