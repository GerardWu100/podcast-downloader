"""Compatibility adapter for the download service."""

from __future__ import annotations

import logging
from pathlib import Path

from .downloads.service import PodcastDownloadService as PodcastDownloader
from .media.youtube import get_video_metadata, is_old_enough
from .state.bypass_store import BypassStore
from .state.queue_store import QueueStore


def remove_video_url_from_file(
    urls_file: Path,
    video_url: str,
    logger: logging.Logger,
) -> None:
    """Remove one direct video URL from the monitored queue."""
    QueueStore(urls_file, logger).remove_url(video_url)


def remove_from_bypass_age_file(
    bypass_file: Path,
    video_url: str,
    logger: logging.Logger,
) -> None:
    """Remove one direct video URL from the age-bypass state."""
    BypassStore(bypass_file, logger).remove(video_url)


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
