"""Locked concise activity-log storage for the browser UI."""

from __future__ import annotations

import fcntl
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .file_locks import locked_text_file


DEFAULT_ACTIVITY_LINE_COUNT = 100
NO_ACTIVITY_MESSAGE = "No activity yet."
NO_DOWNLOAD_LOG_MESSAGE = "No log entries yet."
ACTIVITY_LOG_TIME_ZONE = ZoneInfo("America/Toronto")


class ActivityLogStore:
    """Append and tail-read concise activity events under file locks."""

    def __init__(self, activity_log_file: Path) -> None:
        """Create an activity store for one ``activity.log`` file."""
        self.activity_log_file = activity_log_file

    def write_event(self, message: str) -> None:
        """Append one timestamped user-facing activity event."""
        timestamp = datetime.now(ACTIVITY_LOG_TIME_ZONE).strftime("%Y-%m-%d %H:%M:%S")
        with locked_text_file(
            self.activity_log_file,
            "a",
            fcntl.LOCK_EX,
        ) as file_handle:
            file_handle.write(f"[{timestamp}] {message.strip()}\n")

    def read_tail(
        self,
        line_count: int = DEFAULT_ACTIVITY_LINE_COUNT,
        *,
        empty_message: str = NO_ACTIVITY_MESSAGE,
    ) -> str:
        """Return the most recent log lines for browser display."""
        if not self.activity_log_file.exists():
            return empty_message

        with locked_text_file(
            self.activity_log_file,
            "r",
            fcntl.LOCK_SH,
        ) as file_handle:
            lines = file_handle.read().splitlines()
        if not lines:
            return empty_message

        return "\n".join(lines[-line_count:])
