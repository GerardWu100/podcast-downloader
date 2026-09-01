"""Thread-safe queues that let the web UI wake the scheduler.

The web UI and Docker scheduler run in the same Python process under
``start.py``. Waking the scheduler is not enough on its own: it also needs to
know which exact URL to act on. Direct videos go to the single-URL queue and
playlists to the full-playlist queue, so an immediate run processes only what
the browser submitted rather than the whole of ``urls.txt``.

The Run button is the one exception. It asks for the same work the scheduled
06:00 run does, so it sets a flag instead of naming a URL.
"""

from __future__ import annotations

import threading
from typing import Protocol

download_trigger: threading.Event = threading.Event()
# One lock guards all three pending-request containers below.
_requests_lock = threading.Lock()
_single_url_download_requests: list[str] = []
_full_playlist_download_requests: list[str] = []
_full_queue_run_requested = False


class DownloadTrigger(Protocol):
    """Interface the web app uses to request scheduler work."""

    def queue_single_url_download(self, url: str) -> None:
        """Queue one direct media URL for immediate processing."""

    def queue_full_playlist_download(self, url: str) -> None:
        """Queue one playlist URL for immediate full-playlist processing."""

    def queue_full_queue_run(self) -> None:
        """Ask for one immediate pass over the whole queue."""


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

    def queue_full_queue_run(self) -> None:
        """Ask for one immediate pass over the whole queue."""
        queue_full_queue_run()


def queue_single_url_download(url: str) -> None:
    """Queue one direct video URL for an immediate single-item scheduler run.

    Parameters
    ----------
    url:
        Direct media URL that should be considered immediately without
        expanding or processing unrelated queue entries.
    """
    with _requests_lock:
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
    with _requests_lock:
        _full_playlist_download_requests.append(url)
    download_trigger.set()


def queue_full_queue_run() -> None:
    """Ask the scheduler to run the whole queue now, as the schedule would.

    This is what the Run button sends. It carries no URL because the run reads
    ``urls.txt`` itself, exactly like the scheduled 06:00 pass.
    """
    global _full_queue_run_requested
    with _requests_lock:
        _full_queue_run_requested = True
    download_trigger.set()


def pop_full_queue_run_request() -> bool:
    """Return whether a whole-queue run is pending, and clear the request."""
    global _full_queue_run_requested
    with _requests_lock:
        was_requested = _full_queue_run_requested
        _full_queue_run_requested = False
    return was_requested


def pop_full_playlist_download_requests() -> list[str]:
    """Return and clear pending full-playlist download requests."""
    with _requests_lock:
        pending_requests = list(_full_playlist_download_requests)
        _full_playlist_download_requests.clear()
    return pending_requests


def pop_single_url_download_requests() -> list[str]:
    """Return and clear pending single-video download requests."""
    with _requests_lock:
        pending_requests = list(_single_url_download_requests)
        _single_url_download_requests.clear()
    return pending_requests


in_process_download_trigger = InProcessDownloadTrigger()
