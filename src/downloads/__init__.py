"""Download package.

This package builds and runs ``yt-dlp`` commands, checks for changed MP3 files,
writes audio tags, and keeps the queue and history files in sync.
"""

from __future__ import annotations

from .service import PodcastDownloadService

__all__ = ["PodcastDownloadService"]
