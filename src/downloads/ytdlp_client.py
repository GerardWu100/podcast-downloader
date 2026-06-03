"""Small value objects for ``yt-dlp`` execution.

The downloader tracks file state around each ``yt-dlp`` subprocess run because
an exit code alone cannot prove that a usable MP3 was created or changed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AudioSnapshot:
    """MP3 file state captured before or after one download attempt.

    Attributes
    ----------
    files:
        Mapping from each MP3 path to ``(mtime_ns, size_bytes)``. ``mtime_ns`` is
        the filesystem modification time in nanoseconds, and ``size_bytes`` is
        the file size. Both values are needed because a downloader can preserve
        or reuse timestamps while changing bytes.
    """

    files: dict[Path, tuple[int, int]]
