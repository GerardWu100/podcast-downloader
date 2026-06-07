"""Shared timezone for operator-facing log timestamps."""

from __future__ import annotations

from zoneinfo import ZoneInfo


# Browser-facing activity.log and detailed download.log both use Toronto time so
# Docker UTC defaults do not disagree with the operator's expected local clock.
LOG_TIME_ZONE = ZoneInfo("America/Toronto")
