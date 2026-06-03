"""Locked archive storage for expanded channel and playlist video URLs."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import logging
from pathlib import Path
from typing import Iterator, TextIO

from .file_locks import locked_text_file


class LockedDownloadedUrlArchive:
    """Exclusive archive transaction for check-download-write flows.

    The archive records expanded channel and playlist items that completed
    successfully. Holding one exclusive lock across duplicate detection and the
    eventual success append prevents two downloader processes from doing the
    same expanded item at the same time.
    """

    def __init__(self, file_handle: TextIO) -> None:
        """Create a transaction around an already locked file handle."""
        self.file_handle = file_handle
        self._urls = self._read_urls()

    def _read_urls(self) -> set[str]:
        """Read normalized archive URLs from the locked handle."""
        from ..url_utils import normalize_youtube_url

        self.file_handle.seek(0)
        return {
            normalize_youtube_url(line.strip())
            for line in self.file_handle
            if line.strip()
        }

    def contains(self, url: str) -> bool:
        """Return whether a normalized URL is already archived."""
        from ..url_utils import normalize_youtube_url

        normalized = normalize_youtube_url(url.strip())
        return normalized in self._urls

    def append_success(self, url: str) -> bool:
        """Append a successful normalized URL once."""
        from ..url_utils import normalize_youtube_url

        normalized = normalize_youtube_url(url.strip())
        if normalized in self._urls:
            return False

        self.file_handle.seek(0, 2)
        self.file_handle.write(f"{normalized}\n")
        self.file_handle.flush()
        self._urls.add(normalized)
        return True

    def remove(self, url: str) -> bool:
        """Remove one normalized URL from the archive transaction."""
        from ..url_utils import normalize_youtube_url

        normalized = normalize_youtube_url(url.strip())
        if normalized not in self._urls:
            return False

        self._urls.remove(normalized)
        self.file_handle.seek(0)
        for archived_url in sorted(self._urls):
            self.file_handle.write(f"{archived_url}\n")
        self.file_handle.truncate()
        self.file_handle.flush()
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
        self.archive_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.archive_file.exists():
            self.archive_file.touch()

        with locked_text_file(self.archive_file, "r+", fcntl.LOCK_EX) as file_handle:
            yield LockedDownloadedUrlArchive(file_handle)

    def load(self) -> set[str]:
        """Read normalized archived URLs while holding a shared lock."""
        from ..url_utils import normalize_youtube_url

        if not self.archive_file.exists():
            return set()

        try:
            with locked_text_file(
                self.archive_file,
                "r",
                fcntl.LOCK_SH,
            ) as file_handle:
                return {
                    normalize_youtube_url(line.strip())
                    for line in file_handle
                    if line.strip()
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

    def claim(self, url: str) -> bool:
        """Atomically append a URL if absent and report whether this caller won."""
        return self.append(url)

    def remove(self, url: str) -> bool:
        """Remove one normalized URL from the archive under an exclusive lock."""
        try:
            with self.locked_transaction() as archive:
                return archive.remove(url)
        except Exception as exc:  # pragma: no cover - logging error path
            self.logger.error("Could not remove downloaded URL: %s", exc)
            return False
