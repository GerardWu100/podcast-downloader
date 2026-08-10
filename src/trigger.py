"""Thread-safe queues that let the web UI wake the scheduler.

The web UI and Docker scheduler run in the same Python process under
``start.py``. Waking the scheduler is not enough on its own: it also needs to
know which exact URL to act on. Direct videos go to the single-URL queue and
playlists to the full-playlist queue, so an immediate run processes only what
the browser submitted rather than the whole of ``urls.txt``.
"""

from __future__ import annotations

import threading
from typing import Protocol

download_trigger: threading.Event = threading.Event()
_single_url_lock = threading.Lock()
_single_url_download_requests: list[str] = []
_full_playlist_download_requests: list[str] = []


class DownloadTrigger(Protocol):
    """Interface the web app uses to request scheduler work."""

    def queue_single_url_download(self, url: str) -> None:
        """Queue one direct media URL for immediate processing."""

    def queue_full_playlist_download(self, url: str) -> None:
        """Queue one playlist URL for immediate full-playlist processing."""


class InProcessDownloadTrigger:
    """Adapter that writes requests to this module's shared queues."""

    def queue_single_url_download(self, url: str) -> None:
        """Queue one direct media URL for immediate processing.

        Parameters
        ----------
        url:
            Normalized direct media URL.
        """
        queue_single_url_download(url)

    def queue_full_playlist_download(self, url: str) -> None:
        """Queue one playlist URL for immediate full-playlist processing.

        Parameters
        ----------
        url:
            Normalized YouTube playlist URL.
        """
        queue_full_playlist_download(url)


def queue_single_url_download(url: str) -> None:
    """Queue one direct video URL for an immediate single-item scheduler run.

    Parameters
    ----------
    url:
        Direct media URL that should be considered immediately without
        expanding or processing unrelated queue entries.
    """
    with _single_url_lock:
        _single_url_download_requests.append(url)
    download_trigger.set()


def queue_full_playlist_download(url: str) -> None:
    """Queue one playlist URL for an immediate full-playlist scheduler run.

    Parameters
    ----------
    url:
        YouTube playlist URL whose entire contents should be expanded and
        downloaded immediately instead of waiting for the scheduled run.
    """
    with _single_url_lock:
        _full_playlist_download_requests.append(url)
    download_trigger.set()


def pop_full_playlist_download_requests() -> list[str]:
    """Return and clear pending full-playlist download requests."""
    with _single_url_lock:
        pending_requests = list(_full_playlist_download_requests)
        _full_playlist_download_requests.clear()
    return pending_requests


def pop_single_url_download_requests() -> list[str]:
    """Return and clear pending single-video download requests."""
    with _single_url_lock:
        pending_requests = list(_single_url_download_requests)
        _single_url_download_requests.clear()
    return pending_requests


in_process_download_trigger = InProcessDownloadTrigger()
