"""Shared timezone and timestamp formats for operator-facing time values."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

# Browser-facing activity.log and detailed download.log both use Toronto time so
# Docker UTC defaults do not disagree with the operator's expected local clock.
LOG_TIME_ZONE = ZoneInfo("America/Toronto")
OPERATOR_LOG_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M"


def local_now() -> datetime:
    """Return the current time on the operator's clock.

    Every module that needs "now" for a person to read goes through this, so
    the project has one clock rather than a mix of local time and UTC.
    """
    return datetime.now(LOG_TIME_ZONE)
