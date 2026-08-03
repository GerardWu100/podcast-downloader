"""Locked one-shot age-bypass storage for direct YouTube videos."""

from __future__ import annotations

import fcntl
import logging
from pathlib import Path

from .file_locks import locked_text_file


class BypassStore:
    """Manage URLs that skip the YouTube age gate for one download attempt."""

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
            with locked_text_file(self.bypass_file, "r", fcntl.LOCK_SH) as file_handle:
                return {
                    normalize_youtube_url(line.strip())
                    for line in file_handle
                    if line.strip() and not line.strip().startswith("#")
                }
        except Exception as exc:
            self.logger.warning("Could not read bypass age check file: %s", exc)
            return set()

    def add(self, url: str) -> None:
        """Append a normalized URL if it is not already present."""
        from ..media.youtube import normalize_youtube_url

        normalized = normalize_youtube_url(url.strip())
        self.bypass_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.bypass_file.exists():
            self.bypass_file.touch()
        try:
            with locked_text_file(
                self.bypass_file,
                "a+",
                fcntl.LOCK_EX,
            ) as file_handle:
                file_handle.seek(0)
                existing: set[str] = set()
                last_line = ""
                for line in file_handle:
                    last_line = line
                    if line.strip():
                        existing.add(normalize_youtube_url(line.strip()))
                if normalized not in existing:
                    file_handle.seek(0, 2)
                    # Repair a missing final newline so the new URL is not
                    # spliced onto a hand-edited last line.
                    if last_line and not last_line.endswith("\n"):
                        file_handle.write("\n")
                    file_handle.write(f"{normalized}\n")
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
