"""Compatibility adapter for the download service."""

from __future__ import annotations

from .url_utils import (
    get_video_metadata,
    is_old_enough,
    remove_from_bypass_age_file,
    remove_video_url_from_file,
)
from .downloads.service import PodcastDownloadService as PodcastDownloader


class Colors:
    """ANSI color codes used by the CLI status output."""

    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    BLUE = "\033[0;34m"
    NC = "\033[0m"


__all__ = [
    "Colors",
    "PodcastDownloader",
    "get_video_metadata",
    "is_old_enough",
    "remove_video_url_from_file",
    "remove_from_bypass_age_file",
]
