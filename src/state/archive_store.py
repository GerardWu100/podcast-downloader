"""Locked archive storage for expanded channel and playlist video URLs."""

from __future__ import annotations

import fcntl
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .file_locks import LockedLineFile, locked_line_file


class LockedDownloadedUrlArchive:
    """Exclusive archive transaction for check-download-write flows.

    The archive records expanded channel and playlist items that completed
    successfully. Holding one exclusive lock across duplicate detection and the
    eventual success append prevents two downloader processes from doing the
    same expanded item at the same time.
    """

    def __init__(self, archive_lines: LockedLineFile) -> None:
        """Create a transaction around an already locked archive file."""
        self.archive_lines = archive_lines
        self._urls = self._read_urls()

    def _read_urls(self) -> set[str]:
        """Read normalized archive URLs from the locked file."""
        from ..media.youtube import normalize_youtube_url

        return {normalize_youtube_url(entry) for entry in self.archive_lines.entries()}

    def contains(self, url: str) -> bool:
        """Return whether a normalized URL is already archived."""
        from ..media.youtube import normalize_youtube_url

        normalized = normalize_youtube_url(url.strip())
        return normalized in self._urls

    def append_success(self, url: str) -> bool:
        """Append a successful normalized URL once."""
        from ..media.youtube import normalize_youtube_url

        normalized = normalize_youtube_url(url.strip())
        if normalized in self._urls:
            return False

        self.archive_lines.append_line(normalized)
        self._urls.add(normalized)
        return True

    def remove(self, url: str) -> bool:
        """Remove one normalized URL from the archive transaction."""
        from ..media.youtube import normalize_youtube_url

        normalized = normalize_youtube_url(url.strip())
        if normalized not in self._urls:
            return False

        self._urls.remove(normalized)
        self.archive_lines.rewrite_lines(sorted(self._urls))
        return True


class ArchiveStore:
    """Read, append, and claim archived expanded URLs under file locks."""

    def __init__(self, archive_file: Path, logger: logging.Logger) -> None:
        """Create an archive store for one ``downloaded_urls.txt`` file."""
        self.archive_file = archive_file
        self.logger = logger

    @contextmanager
    def locked_transaction(self) -> Iterator[LockedDownloadedUrlArchive]:
        """Hold an exclusive archive lock for a full transaction."""
        with locked_line_file(
            self.archive_file,
            "r+",
            fcntl.LOCK_EX,
        ) as archive_lines:
            yield LockedDownloadedUrlArchive(archive_lines)

    def load(self) -> set[str]:
        """Read normalized archived URLs while holding a shared lock."""
        from ..media.youtube import normalize_youtube_url

        if not self.archive_file.exists():
            return set()

        try:
            with locked_line_file(
                self.archive_file,
                "r",
                fcntl.LOCK_SH,
            ) as archive_lines:
                return {
                    normalize_youtube_url(entry) for entry in archive_lines.entries()
                }
        except Exception as exc:  # pragma: no cover - logging error path
            self.logger.warning("Could not read downloaded URL archive: %s", exc)
            return set()

    def append(self, url: str) -> bool:
        """Append one normalized URL under an exclusive lock."""
        try:
            with self.locked_transaction() as archive:
                return archive.append_success(url)
        except Exception as exc:  # pragma: no cover - logging error path
            self.logger.error("Could not save downloaded URL: %s", exc)
            return False

    def remove(self, url: str) -> bool:
        """Remove one normalized URL from the archive under an exclusive lock."""
        try:
            with self.locked_transaction() as archive:
                return archive.remove(url)
        except Exception as exc:  # pragma: no cover - logging error path
            self.logger.error("Could not remove downloaded URL: %s", exc)
            return False
