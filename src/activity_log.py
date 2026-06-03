"""Concise activity-log helpers for the browser UI."""

from __future__ import annotations

from pathlib import Path

from .state.activity_store import (
    DEFAULT_ACTIVITY_LINE_COUNT,
    ActivityLogStore,
)


ACTIVITY_LOG_NAME = "activity.log"


def activity_log_file_for(full_log_file: Path) -> Path:
    """Return the concise activity log path for a full diagnostic log path.

    Parameters
    ----------
    full_log_file:
        Path to the existing full runtime log, usually ``download.log``.

    Returns
    -------
    pathlib.Path
        Path to ``activity.log`` in the same directory as ``full_log_file``.
    """
    return full_log_file.parent / ACTIVITY_LOG_NAME


def write_activity_event(activity_log_file: Path, message: str) -> None:
    """Append one timestamped user-facing activity event.

    Parameters
    ----------
    activity_log_file:
        Destination log file for concise browser activity.
    message:
        Plain-language event text. Callers should avoid raw command output and
        other diagnostic detail so the webpage stays easy to scan.
    """
    ActivityLogStore(activity_log_file).write_event(message)


def read_activity_log_tail(
    activity_log_file: Path,
    line_count: int = DEFAULT_ACTIVITY_LINE_COUNT,
) -> str:
    """Return the most recent concise activity entries for the browser.

    Parameters
    ----------
    activity_log_file:
        Concise activity log file.
    line_count:
        Maximum number of lines to return.

    Returns
    -------
    str
        Tail text for display in the UI, or a short empty-state message when
        there is no activity file yet.
    """
    return ActivityLogStore(activity_log_file).read_tail(line_count)
