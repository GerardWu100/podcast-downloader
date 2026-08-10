"""Store the short activity feed shown in the browser UI."""

from __future__ import annotations

import fcntl
import os
from datetime import datetime
from pathlib import Path

from ..log_timezone import LOG_TIME_ZONE, OPERATOR_LOG_TIMESTAMP_FORMAT
from .file_locks import locked_line_file, locked_text_file

DEFAULT_ACTIVITY_LINE_COUNT = 100
# Read a bounded final window so polling a large download.log stays cheap.
TAIL_READ_BYTES = 256 * 1024
NO_ACTIVITY_MESSAGE = "No activity yet."
NO_DOWNLOAD_LOG_MESSAGE = "No log entries yet."
ACTIVITY_LOG_NAME = "activity.log"


def activity_log_file_for(full_log_file: Path) -> Path:
    """Return concise activity-log path beside the diagnostic log."""
    return full_log_file.parent / ACTIVITY_LOG_NAME


class ActivityLogStore:
    """Append and tail-read concise activity events under file locks."""

    def __init__(self, activity_log_file: Path) -> None:
        """Create an activity store for one ``activity.log`` file."""
        self.activity_log_file = activity_log_file

    def write_event(self, message: str) -> None:
        """Append one timestamped user-facing activity event."""
        timestamp = datetime.now(LOG_TIME_ZONE).strftime(OPERATOR_LOG_TIMESTAMP_FORMAT)
        with locked_line_file(
            self.activity_log_file,
            "a+",
            fcntl.LOCK_EX,
        ) as activity_lines:
            activity_lines.append_line(f"[{timestamp}] {message.strip()}")

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
            # Read only the final window. The browser polls every 15 seconds,
            # so reading a multi-megabyte log from the beginning is wasteful.
            # `pread` reads bytes at an offset without moving the file handle.
            descriptor = file_handle.fileno()
            file_size = os.fstat(descriptor).st_size
            read_offset = max(0, file_size - TAIL_READ_BYTES)
            raw_tail = os.pread(descriptor, file_size - read_offset, read_offset)

        # The window can start in the middle of a character, so replace any
        # incomplete leading bytes instead of failing.
        text_tail = raw_tail.decode("utf-8", errors="replace")
        lines = text_tail.splitlines()
        # The window can also start in the middle of a line; drop that partial
        # line so the browser receives complete entries only.
        if read_offset > 0 and lines:
            lines = lines[1:]
        if not lines:
            return empty_message

        return "\n".join(lines[-line_count:])
