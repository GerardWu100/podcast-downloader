"""Locked concise activity-log storage for the browser UI."""

from __future__ import annotations

import fcntl
from datetime import datetime
from pathlib import Path

from ..log_timezone import LOG_TIME_ZONE, OPERATOR_LOG_TIMESTAMP_FORMAT
from .file_locks import locked_text_file


DEFAULT_ACTIVITY_LINE_COUNT = 100
NO_ACTIVITY_MESSAGE = "No activity yet."
NO_DOWNLOAD_LOG_MESSAGE = "No log entries yet."
ACTIVITY_LOG_NAME = "activity.log"


def activity_log_file_for(full_log_file: Path) -> Path:
    """Return concise activity-log path beside the diagnostic log."""
    return full_log_file.parent / ACTIVITY_LOG_NAME


def read_activity_log_tail(
    activity_log_file: Path,
    line_count: int = DEFAULT_ACTIVITY_LINE_COUNT,
) -> str:
    """Return recent concise activity entries through ``ActivityLogStore``."""
    return ActivityLogStore(activity_log_file).read_tail(line_count)


def read_download_log_tail(
    download_log_file: Path,
    line_count: int = DEFAULT_ACTIVITY_LINE_COUNT,
) -> str:
    """Return recent diagnostic entries through ``ActivityLogStore``."""
    return ActivityLogStore(download_log_file).read_tail(
        line_count,
        empty_message=NO_DOWNLOAD_LOG_MESSAGE,
    )


class ActivityLogStore:
    """Append and tail-read concise activity events under file locks."""

    def __init__(self, activity_log_file: Path) -> None:
        """Create an activity store for one ``activity.log`` file."""
        self.activity_log_file = activity_log_file

    def write_event(self, message: str) -> None:
        """Append one timestamped user-facing activity event."""
        timestamp = datetime.now(LOG_TIME_ZONE).strftime(OPERATOR_LOG_TIMESTAMP_FORMAT)
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
