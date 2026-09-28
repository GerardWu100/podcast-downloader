"""Remember which library folder each channel or playlist publishes into.

Channel-ID and playlist sources get their folder name from a ``yt-dlp`` lookup.
If that lookup fails on some later run, which is exactly what happens while
YouTube is blocking requests, the folder would fall back to the raw ``UC...`` or
``PL...`` identifier and split one podcast across two Audiobookshelf folders. A
renamed playlist would do the same. Saving the first name that resolved keeps
every later run on the same folder.

File format: one JSON object mapping the source URL exactly as it appears in
the queue to the sanitized folder name, for example
``{"https://www.youtube.com/playlist?list=PL123": "My-Playlist"}``.
"""

from __future__ import annotations

import fcntl
import json
from pathlib import Path

from .file_locks import locked_text_file

SOURCE_FOLDERS_FILE_NAME = "source_folders.json"


class SourceFolderStore:
    """Read and extend the source-to-folder map under a cross-process lock.

    Parameters
    ----------
    folders_file:
        JSON file holding the map.
    """

    def __init__(self, folders_file: Path) -> None:
        self.folders_file = folders_file

    @property
    def _lock_file(self) -> Path:
        """Return the stable sibling lock path for the replaceable map file."""
        return self.folders_file.with_name(f"{self.folders_file.name}.lock")

    def _read_unlocked(self) -> dict[str, str]:
        """Read the map, treating an absent or damaged file as empty."""
        if not self.folders_file.exists():
            return {}
        try:
            raw_map = json.loads(self.folders_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw_map, dict):
            return {}
        return {
            str(source_url): folder_name
            for source_url, folder_name in raw_map.items()
            if isinstance(folder_name, str) and folder_name
        }

    def folder_for(self, source_url: str) -> str | None:
        """Return the saved folder name for one source, or ``None``."""
        with locked_text_file(self._lock_file, "a+", fcntl.LOCK_SH):
            return self._read_unlocked().get(source_url)

    def remember(self, source_url: str, folder_name: str) -> None:
        """Save one source's folder name, replacing the file atomically."""
        with locked_text_file(self._lock_file, "a+", fcntl.LOCK_EX):
            folder_map = self._read_unlocked()
            if folder_map.get(source_url) == folder_name:
                return
            folder_map[source_url] = folder_name
            self.folders_file.parent.mkdir(parents=True, exist_ok=True)
            temporary_file = self.folders_file.with_name(
                f".{self.folders_file.name}.tmp"
            )
            temporary_file.write_text(
                json.dumps(folder_map, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            temporary_file.replace(self.folders_file)
