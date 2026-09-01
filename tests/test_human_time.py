"""Tests for the plain-language time wording shown to the operator."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from src.human_time import format_clock_time, format_time_ago, format_time_until
from src.log_timezone import LOG_TIME_ZONE


def _toronto(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """Return one Toronto-local instant, the clock the interface uses."""
    return datetime(year, month, day, hour, minute, tzinfo=LOG_TIME_ZONE)


def test_clock_time_is_written_the_same_way_as_the_logs() -> None:
    """The status row and the activity log must agree on how a time looks."""
    assert format_clock_time(_toronto(2026, 9, 3, 6, 0)) == "2026-09-03 06:00"


@pytest.mark.parametrize(
    ("elapsed", "expected"),
    [
        (timedelta(seconds=20), "just now"),
        (timedelta(minutes=1), "1 minute ago"),
        (timedelta(minutes=42), "42 minutes ago"),
        (timedelta(hours=1, minutes=5), "1 hour ago"),
        (timedelta(hours=41), "41 hours ago"),
    ],
)
def test_time_ago_wording(elapsed: timedelta, expected: str) -> None:
    """The status line reports age in plain words, rounded down."""
    now = _toronto(2026, 9, 3, 13, 0)

    assert format_time_ago(now - elapsed, now) == expected


@pytest.mark.parametrize(
    ("remaining", "expected"),
    [
        (timedelta(seconds=20), "now"),
        (timedelta(minutes=30), "in 30 minutes"),
        (timedelta(hours=41), "in 41 hours"),
    ],
)
def test_time_until_wording(remaining: timedelta, expected: str) -> None:
    """The status line reports the wait the same way it reports the age."""
    now = _toronto(2026, 9, 3, 13, 0)

    assert format_time_until(now + remaining, now) == expected
