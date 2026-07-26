"""Locked queue-file storage for monitored media URLs."""

from __future__ import annotations

import fcntl
import logging
from pathlib import Path

from .file_locks import locked_text_file


class QueueStore:
    """Read and mutate the durable ``urls.txt`` queue under file locks.

    Parameters
    ----------
    urls_file:
        Queue file containing one media URL per line. Blank lines and comments
        beginning with ``#`` are preserved where practical.
    logger:
        Logger used for invalid-line warnings and mutation diagnostics.
    """

    def __init__(self, urls_file: Path, logger: logging.Logger) -> None:
        """Create a queue store for one queue file."""
        self.urls_file = urls_file
        self.logger = logger

    def _read_locked_lines(self, lock_type: int) -> list[tuple[int, str]]:
        """Read non-empty queue lines while holding the requested file lock.

        Parameters
        ----------
        lock_type:
            Shared or exclusive ``fcntl`` lock constant.

        Returns
        -------
        list[tuple[int, str]]
            One-based line number and stripped text for every non-empty line.
        """
        lines: list[tuple[int, str]] = []
        with locked_text_file(self.urls_file, "r", lock_type) as file_handle:
            for line_number, line in enumerate(file_handle, 1):
                stripped = line.strip()
                if stripped:
                    lines.append((line_number, stripped))
        return lines

    def create_sample_file(self) -> None:
        """Create a starter queue file when the configured queue is missing."""
        self.urls_file.parent.mkdir(parents=True, exist_ok=True)
        sample_content = """# Podcast URLs
# Add one web video URL per line. Lines starting with # are comments.
#
# Supported formats:
# - YouTube individual videos: https://www.youtube.com/watch?v=VIDEO_ID
# - YouTube short URLs: https://youtu.be/VIDEO_ID
# - YouTube channels: https://www.youtube.com/@username
# - YouTube playlists: https://www.youtube.com/playlist?list=PLAYLIST_ID
# - Non-YouTube direct videos: https://videos.example.com/watch/episode-1
#
# Examples:
# https://www.youtube.com/watch?v=dQw4w9WgXcQ
# https://www.youtube.com/@examplechannel
# https://www.youtube.com/playlist?list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf
# https://videos.example.com/watch/episode-1
"""
        self.urls_file.write_text(sample_content, encoding="utf-8")
        self.logger.info("Created sample URLs file: %s", self.urls_file)
        self.logger.info("Please add your media URLs and run again.")

    def read_urls(self) -> list[str]:
        """Read valid queue entries and ignore comments and blank lines."""
        from ..media.urls import is_supported_media_url

        if not self.urls_file.exists():
            self.logger.error("URLs file not found: %s", self.urls_file)
            self.create_sample_file()
            return []

        urls: list[str] = []
        for line_num, stripped in self._read_locked_lines(fcntl.LOCK_SH):
            if stripped.startswith("#"):
                continue
            if is_supported_media_url(stripped):
                urls.append(stripped)
            else:
                self.logger.warning("Line %s: Invalid URL: %s", line_num, stripped)

        return urls

    def load_normalized_urls(self) -> list[str]:
        """Return normalized valid queue entries for UI rendering."""
        from ..media.urls import is_supported_media_url
        from ..media.youtube import normalize_youtube_url

        if not self.urls_file.exists():
            return []

        try:
            queue_urls: list[str] = []
            for _line_num, stripped in self._read_locked_lines(fcntl.LOCK_SH):
                if stripped.startswith("#"):
                    continue
                if not is_supported_media_url(stripped):
                    self.logger.warning(
                        "Ignoring invalid queue URL while rendering UI: %s",
                        stripped,
                    )
                    continue
                queue_urls.append(normalize_youtube_url(stripped))
            return queue_urls
        except Exception as exc:  # pragma: no cover - logging error path
            self.logger.warning("Could not read queue URLs: %s", exc)
            return []

    def remove_url(self, url: str) -> bool:
        """Remove one normalized URL from the queue."""
        from ..media.youtube import normalize_youtube_url

        if not self.urls_file.exists():
            return False

        normalized_target = normalize_youtube_url(url.strip())

        try:
            with locked_text_file(self.urls_file, "r+", fcntl.LOCK_EX) as file_handle:
                lines = file_handle.readlines()
                new_lines: list[str] = []
                removed = False

                for line in lines:
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#"):
                        new_lines.append(line)
                        continue

                    normalized_line = normalize_youtube_url(stripped)
                    if normalized_line == normalized_target:
                        removed = True
                        continue

                    new_lines.append(line)

                if removed:
                    file_handle.seek(0)
                    file_handle.writelines(new_lines)
                    file_handle.truncate()
                    self.logger.debug(
                        "Removed monitored URL from queue: %s",
                        normalized_target,
                    )

                return removed
        except Exception as exc:  # pragma: no cover - logging error path
            self.logger.warning("Could not remove monitored URL from queue: %s", exc)
            return False

    def append_urls(self, urls: list[str]) -> int:
        """Append normalized valid URLs while skipping duplicates.

        Parameters
        ----------
        urls:
            Candidate URLs. Blank values, unsupported URLs, and existing
            normalized entries are skipped.

        Returns
        -------
        int
            Number of new URLs written.
        """
        from ..media.urls import is_supported_media_url
        from ..media.youtube import normalize_youtube_url

        if not urls:
            return 0

        self.urls_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.urls_file.exists():
            self.urls_file.touch()

        added = 0
        with locked_text_file(self.urls_file, "a+", fcntl.LOCK_EX) as file_handle:
            file_handle.seek(0)
            existing = set()
            for line in file_handle:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                existing.add(normalize_youtube_url(stripped))

            file_handle.seek(0, 2)
            for raw_url in urls:
                url = raw_url.strip()
                if not url:
                    continue
                if not is_supported_media_url(url):
                    print(f"Skipping invalid URL: {url}")
                    continue

                normalized = normalize_youtube_url(url)
                if normalized in existing:
                    continue

                file_handle.write(f"{normalized}\n")
                existing.add(normalized)
                added += 1

        return added
