"""Download execution package.

This package owns the concrete download pass: building and running ``yt-dlp``
commands, detecting MP3 file changes, stamping audio metadata, and keeping the
queue/archive files in sync after each attempt.
"""

from __future__ import annotations

from .service import PodcastDownloadService

__all__ = ["PodcastDownloadService"]
