"""Remember one piece of text per queue source, such as its folder or its name.

Two maps use this store:

- ``source_folders.json``: which library folder each channel or playlist
  publishes into. Channel-ID and playlist sources get their folder name from a
  ``yt-dlp`` lookup. If that lookup fails on some later run, which is exactly
  what happens while YouTube is blocking requests, the folder would fall back
  to the raw ``UC...`` or ``PL...`` identifier and split one podcast across two
  Audiobookshelf folders. A renamed playlist would do the same. Saving the
  first name that resolved keeps every later run on the same folder.
- ``source_names.json``: the channel, playlist, or video name the queue page
  shows instead of the URL, and its author. Looking it up costs a ``yt-dlp``
  call, so it is done once per source and kept.

File format: one JSON object mapping the source URL exactly as it appears in
the queue to its value. Folders map to text,
``{"https://www.youtube.com/playlist?list=PL123": "My-Playlist"}``; names map
to an object, ``{"...": {"name": "My Playlist", "author": "Some Channel"}}``.
"""

from __future__ import annotations

import fcntl
import json
from collections.abc import Iterable
from pathlib import Path

from .file_locks import locked_text_file

# A stored value: folder text, or a name object such as
# {"name": "My Playlist", "author": "Some Channel"}.
SourceValue = str | dict[str, str | None]

SOURCE_FOLDERS_FILE_NAME = "source_folders.json"
SOURCE_NAMES_FILE_NAME = "source_names.json"


class SourceMapStore:
    """Read and change a source-URL-to-value map under a cross-process lock.

    Parameters
    ----------
    map_file:
        JSON file holding the map.
    """

    def __init__(self, map_file: Path) -> None:
        self.map_file = map_file

    @property
    def _lock_file(self) -> Path:
        """Return the stable sibling lock path for the replaceable map file."""
        return self.map_file.with_name(f"{self.map_file.name}.lock")

    def _read_unlocked(self) -> dict[str, SourceValue]:
        """Read the map, treating an absent or damaged file as empty."""
        if not self.map_file.exists():
            return {}
        try:
            raw_map = json.loads(self.map_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw_map, dict):
            return {}
        return {
            str(source_url): value
            for source_url, value in raw_map.items()
            if isinstance(value, (str, dict)) and value
        }

    def _write_unlocked(self, source_map: dict[str, SourceValue]) -> None:
        """Replace the map file atomically; the caller holds the lock."""
        self.map_file.parent.mkdir(parents=True, exist_ok=True)
        temporary_file = self.map_file.with_name(f".{self.map_file.name}.tmp")
        temporary_file.write_text(
            json.dumps(source_map, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary_file.replace(self.map_file)

    def value_for(self, source_url: str) -> SourceValue | None:
        """Return the saved value for one source, or ``None``."""
        with locked_text_file(self._lock_file, "a+", fcntl.LOCK_SH):
            return self._read_unlocked().get(source_url)

    def read_all(self) -> dict[str, SourceValue]:
        """Return the whole map, for a page that shows every source at once."""
        with locked_text_file(self._lock_file, "a+", fcntl.LOCK_SH):
            return self._read_unlocked()

    def remember(self, source_url: str, value: SourceValue) -> None:
        """Save one source's value."""
        with locked_text_file(self._lock_file, "a+", fcntl.LOCK_EX):
            source_map = self._read_unlocked()
            if source_map.get(source_url) == value:
                return
            source_map[source_url] = value
            self._write_unlocked(source_map)

    def forget(self, source_urls: Iterable[str]) -> None:
        """Drop the entries for sources that left the queue."""
        removed_urls = set(source_urls)
        with locked_text_file(self._lock_file, "a+", fcntl.LOCK_EX):
            source_map = self._read_unlocked()
            remaining = {
                url: value for url, value in source_map.items() if url not in removed_urls
            }
            if len(remaining) != len(source_map):
                self._write_unlocked(remaining)
