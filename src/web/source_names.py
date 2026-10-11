"""Names for queue sources, looked up in the background and kept.

The queue page shows "Example Podcast" instead of
``https://www.youtube.com/@example-podcast/videos``. Finding that name takes a
``yt-dlp`` call of a few seconds, too slow to make inside a page request. So
the page shows what it already has, and asks this resolver to look up the
rest; the next page load shows the names.

Flow::

    queue page / add / API  --request(urls)-->  pending set + work queue
    one worker thread       --lookup(url)--->   name or None
    name                    --remember------>   source_names.json (SourceMapStore)

One thread means one ``yt-dlp`` call at a time, so a page with many unnamed
sources cannot fire a burst of requests at YouTube. A failed lookup is not
retried for ``RETRY_AFTER_FAILURE_SECONDS``, for the same reason: while
YouTube is blocking the server, every page load would otherwise try again.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable, Iterable
from urllib.parse import urlparse

from ..media.youtube import SourceKind, source_kind
from ..state.source_map_store import SourceMapStore

RETRY_AFTER_FAILURE_SECONDS = 60 * 60
# The small tag shown beside each source's name on the queue page.
SOURCE_KIND_LABELS = {
    SourceKind.CHANNEL: "Channel",
    SourceKind.PLAYLIST: "Playlist",
    SourceKind.VIDEO: "Video",
}

_logger = logging.getLogger("web.source_names")
# Put on the work queue by close() to end the worker thread.
_STOP = object()


class SourceNameResolver:
    """Look up source names one at a time on a background thread.

    Parameters
    ----------
    name_store:
        Where found names are kept, keyed by the queue URL.
    lookup:
        Function from a source URL to its name, or ``None`` when it could not
        be found. Production passes ``get_source_display_name``; tests pass a
        fake so no network is used.
    """

    def __init__(
        self, name_store: SourceMapStore, lookup: Callable[[str], str | None]
    ) -> None:
        self.name_store = name_store
        self._lookup = lookup
        self._work: queue.Queue[object] = queue.Queue()
        self._state_lock = threading.Lock()
        # URLs waiting or being looked up, so a busy page cannot queue one twice.
        self._pending: set[str] = set()
        # URL -> time.monotonic() of its last failed lookup.
        self._failed_at: dict[str, float] = {}
        self._worker: threading.Thread | None = None

    def request(self, source_urls: Iterable[str]) -> None:
        """Queue a lookup for each URL that has no name, unless one is due later."""
        known_names = self.name_store.read_all()
        now = time.monotonic()
        with self._state_lock:
            for url in source_urls:
                if url in known_names or url in self._pending:
                    continue
                failed_at = self._failed_at.get(url)
                if failed_at is not None and now - failed_at < RETRY_AFTER_FAILURE_SECONDS:
                    continue
                self._pending.add(url)
                self._work.put(url)
            # Started on first use, not at import, so tests and the CLI that
            # never ask for a name never start a thread.
            if self._pending and self._worker is None:
                self._worker = threading.Thread(
                    target=self._run, name="source-name-lookup", daemon=True
                )
                self._worker.start()

    def _run(self) -> None:
        """Work through the queue forever; the thread dies with the process."""
        while True:
            url = self._work.get()
            if url is _STOP:
                self._work.task_done()
                return
            try:
                name = self._lookup(url)
                if name:
                    self.name_store.remember(url, name)
                    with self._state_lock:
                        self._failed_at.pop(url, None)
                else:
                    with self._state_lock:
                        self._failed_at[url] = time.monotonic()
            except Exception:
                # A lookup must never kill the worker, or every later source
                # would stay unnamed until a restart.
                _logger.exception("Source name lookup failed for %s", url)
                with self._state_lock:
                    self._failed_at[url] = time.monotonic()
            finally:
                with self._state_lock:
                    self._pending.discard(url)
                self._work.task_done()

    def wait_until_idle(self) -> None:
        """Block until every queued lookup has finished. For tests."""
        self._work.join()

    def close(self) -> None:
        """Finish queued lookups and end the worker thread. For tests."""
        if self._worker is not None:
            self._work.put(_STOP)
            self._worker.join()
            self._worker = None


def fallback_source_label(url: str) -> str:
    """Return a short label for a source whose name is not known yet.

    ``https://www.youtube.com/@example-podcast/videos`` -> ``@example-podcast``;
    anything else -> the URL without its scheme and ``www.``.
    """
    parsed = urlparse(url)
    path_parts = [part for part in parsed.path.split("/") if part]
    if source_kind(url) is SourceKind.CHANNEL and path_parts and path_parts[0].startswith("@"):
        return path_parts[0]
    host = parsed.netloc.removeprefix("www.")
    rest = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    return f"{host}{rest}".rstrip("/")
