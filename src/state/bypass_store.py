"""Store one-use exceptions to the YouTube waiting period."""

from __future__ import annotations

import fcntl
import logging
from pathlib import Path

from .file_locks import locked_line_file, locked_text_file


class BypassStore:
    """Manage URLs that skip the YouTube age wait for one attempt."""

    def __init__(self, bypass_file: Path, logger: logging.Logger) -> None:
        """Create a bypass store for one ``bypass_age_check_urls.txt`` file."""
        self.bypass_file = bypass_file
        self.logger = logger

    def load(self) -> set[str]:
        """Return normalized URLs that should bypass the next age check."""
        from ..media.youtube import normalize_youtube_url

        if not self.bypass_file.exists():
            return set()
        try:
            with locked_line_file(
                self.bypass_file,
                "r",
                fcntl.LOCK_SH,
            ) as bypass_lines:
                return {
                    normalize_youtube_url(entry)
                    for entry in bypass_lines.entries(skip_comments=True)
                }
        except Exception as exc:
            self.logger.warning("Could not read bypass age check file: %s", exc)
            return set()

    def add(self, url: str) -> None:
        """Append a normalized URL if it is not already present."""
        from ..media.youtube import normalize_youtube_url

        normalized = normalize_youtube_url(url.strip())
        try:
            with locked_line_file(
                self.bypass_file,
                "a+",
                fcntl.LOCK_EX,
            ) as bypass_lines:
                existing = {
                    normalize_youtube_url(entry)
                    for entry in bypass_lines.entries(skip_comments=True)
                }
                if normalized not in existing:
                    bypass_lines.append_line(normalized)
        except Exception as exc:
            self.logger.warning("Could not write to bypass age check file: %s", exc)

    def remove(self, url: str) -> None:
        """Remove one normalized URL from the bypass file."""
        from ..media.youtube import normalize_youtube_url

        if not self.bypass_file.exists():
            return

        normalized_target = normalize_youtube_url(url.strip())
        try:
            with locked_text_file(
                self.bypass_file,
                "r+",
                fcntl.LOCK_EX,
            ) as file_handle:
                lines = file_handle.readlines()
                new_lines = [
                    line
                    for line in lines
                    if normalize_youtube_url(line.strip()) != normalized_target
                ]
                if len(new_lines) != len(lines):
                    file_handle.seek(0)
                    file_handle.writelines(new_lines)
                    file_handle.truncate()
                    self.logger.debug("Removed from bypass age check file: %s", url)
        except Exception as exc:
            self.logger.warning("Could not remove from bypass age check file: %s", exc)

    def consume(self, url: str) -> bool:
        """Atomically remove and acknowledge one matching bypass URL."""
        from ..media.youtube import normalize_youtube_url

        if not self.bypass_file.exists():
            return False

        normalized_target = normalize_youtube_url(url.strip())
        try:
            with locked_text_file(
                self.bypass_file,
                "r+",
                fcntl.LOCK_EX,
            ) as file_handle:
                lines = file_handle.readlines()
                kept_lines: list[str] = []
                consumed = False
                for line in lines:
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#"):
                        kept_lines.append(line)
                        continue
                    if normalize_youtube_url(stripped) == normalized_target:
                        consumed = True
                        continue
                    kept_lines.append(line)

                if consumed:
                    file_handle.seek(0)
                    file_handle.writelines(kept_lines)
                    file_handle.truncate()
                return consumed
        except Exception as exc:
            self.logger.warning("Could not consume bypass age check URL: %s", exc)
            return False
