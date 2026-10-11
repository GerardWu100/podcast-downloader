"""Count failed download attempts per video so dead videos stop being retried.

A deleted, private, or members-only video fails on every run. Without a
count, it stays queued forever and sends a failure alert each time, which
teaches the operator to ignore alerts. The service reads these counts to drop a
video after ``max_download_attempts`` failures.

File format: one JSON object mapping a normalized video URL to the number of
counted failures, for example ``{"https://www.youtube.com/watch?v=abc": 1}``.
A successful download or a drop removes the entry, except for channel and
playlist videos that were dropped: their entry stays so later runs skip them.
"""

from __future__ import annotations

import fcntl
import json
from pathlib import Path

from .file_locks import locked_text_file

FAILED_DOWNLOADS_FILE_NAME = "failed_downloads.json"


class FailedDownloadStore:
    """Read and update per-video failure counts under a cross-process lock.

    Parameters
    ----------
    failures_file:
        JSON file holding the counts.
    """

    def __init__(self, failures_file: Path) -> None:
        self.failures_file = failures_file

    @property
    def _lock_file(self) -> Path:
        """Return the stable sibling lock path for the replaceable counts file."""
        return self.failures_file.with_name(f"{self.failures_file.name}.lock")

    def _read_unlocked(self) -> dict[str, int]:
        """Read the counts, treating an absent or damaged file as empty."""
        if not self.failures_file.exists():
            return {}
        try:
            raw_counts = json.loads(self.failures_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw_counts, dict):
            return {}
        return {
            str(video_url): count
            for video_url, count in raw_counts.items()
            if isinstance(count, int) and count > 0
        }

    def _write_unlocked(self, counts: dict[str, int]) -> None:
        """Replace the counts file atomically."""
        self.failures_file.parent.mkdir(parents=True, exist_ok=True)
        temporary_file = self.failures_file.with_name(f".{self.failures_file.name}.tmp")
        temporary_file.write_text(
            json.dumps(counts, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary_file.replace(self.failures_file)

    def load(self) -> dict[str, int]:
        """Return every video's counted failures."""
        with locked_text_file(self._lock_file, "a+", fcntl.LOCK_SH):
            return self._read_unlocked()

    def record_failure(self, video_url: str) -> int:
        """Add one failure for a video and return its new total."""
        with locked_text_file(self._lock_file, "a+", fcntl.LOCK_EX):
            counts = self._read_unlocked()
            counts[video_url] = counts.get(video_url, 0) + 1
            self._write_unlocked(counts)
            return counts[video_url]

    def clear(self, video_url: str) -> None:
        """Forget a video's failures, for example after it downloads."""
        with locked_text_file(self._lock_file, "a+", fcntl.LOCK_EX):
            counts = self._read_unlocked()
            if counts.pop(video_url, None) is not None:
                self._write_unlocked(counts)
