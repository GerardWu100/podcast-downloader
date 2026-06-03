"""Thread-safe download wake-up state shared by the web UI and scheduler.

The web UI and Docker scheduler run in the same Python process under
``start.py``. Direct-video additions need one extra piece of state: the exact
URL that should be considered immediately as a single podcast item. The batch
flag remains available for scheduler compatibility, but the current browser
submission path uses the single-URL queue for direct videos and leaves channels
or playlists for the scheduled full-queue run.
"""

from __future__ import annotations

import threading

download_trigger: threading.Event = threading.Event()
_single_url_lock = threading.Lock()
_single_url_download_requests: list[str] = []
_batch_download_requested = False


def queue_single_url_download(url: str) -> None:
    """Queue one direct video URL for an immediate single-item scheduler run.

    Parameters
    ----------
    url:
        Direct media URL that should be considered immediately without
        expanding or processing unrelated queue entries.
    """
    global _batch_download_requested
    with _single_url_lock:
        _single_url_download_requests.append(url)
        _batch_download_requested = False
    download_trigger.set()


def queue_batch_download() -> None:
    """Mark that the scheduler should run the full queue immediately."""
    global _batch_download_requested
    with _single_url_lock:
        _batch_download_requested = True
    download_trigger.set()


def pop_single_url_download_requests() -> list[str]:
    """Return and clear pending single-video download requests."""
    with _single_url_lock:
        pending_requests = list(_single_url_download_requests)
        _single_url_download_requests.clear()
    return pending_requests


def pop_batch_download_request() -> bool:
    """Return and clear the pending full-queue immediate-run flag."""
    global _batch_download_requested
    with _single_url_lock:
        batch_requested = _batch_download_requested
        _batch_download_requested = False
    return batch_requested
