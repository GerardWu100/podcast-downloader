"""Queue sources show channel and playlist names, looked up once in the background."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

from src.media.youtube import SourceKind, source_kind
from src.state.queue_store import QueueStore
from src.state.source_map_store import SOURCE_NAMES_FILE_NAME, SourceMapStore
from src.web import routes
from src.web.app import create_app
from src.web.source_names import SourceNameResolver, fallback_source_label

CHANNEL_URL = "https://www.youtube.com/@example-podcast/videos"
PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLexample-playlist"
VIDEO_URL = "https://www.youtube.com/watch?v=EXAMPLE0001"


class _CountingLookup:
    """Fake yt-dlp lookup that records every call."""

    def __init__(self, names: dict[str, str | None]) -> None:
        self.names = names
        self.calls: list[str] = []

    def __call__(self, url: str) -> str | None:
        self.calls.append(url)
        return self.names.get(url)


def test_source_kind_tells_channels_playlists_and_videos_apart() -> None:
    assert source_kind(CHANNEL_URL) is SourceKind.CHANNEL
    assert source_kind(PLAYLIST_URL) is SourceKind.PLAYLIST
    assert source_kind(VIDEO_URL) is SourceKind.VIDEO


def test_fallback_label_is_the_handle_or_a_short_url() -> None:
    """Until a name is known, show something shorter than the full URL."""
    assert fallback_source_label(CHANNEL_URL) == "@example-podcast"
    assert fallback_source_label(PLAYLIST_URL) == "youtube.com/playlist?list=PLexample-playlist"


def test_resolver_looks_each_source_up_once_and_keeps_the_name(tmp_path: Path) -> None:
    store = SourceMapStore(tmp_path / SOURCE_NAMES_FILE_NAME)
    lookup = _CountingLookup({CHANNEL_URL: "Example Podcast"})
    resolver = SourceNameResolver(store, lookup)

    resolver.request([CHANNEL_URL, CHANNEL_URL])
    resolver.wait_until_idle()
    resolver.request([CHANNEL_URL])
    resolver.wait_until_idle()

    resolver.close()

    assert lookup.calls == [CHANNEL_URL]
    assert store.read_all() == {CHANNEL_URL: "Example Podcast"}


def test_resolver_waits_before_retrying_a_failed_lookup(tmp_path: Path) -> None:
    """While YouTube blocks the server, page loads must not retry every time."""
    lookup = _CountingLookup({PLAYLIST_URL: None})
    resolver = SourceNameResolver(SourceMapStore(tmp_path / "names.json"), lookup)

    resolver.request([PLAYLIST_URL])
    resolver.wait_until_idle()
    resolver.request([PLAYLIST_URL])
    resolver.close()

    assert lookup.calls == [PLAYLIST_URL]


def test_store_forgets_removed_sources(tmp_path: Path) -> None:
    store = SourceMapStore(tmp_path / "names.json")
    store.remember(CHANNEL_URL, "Example Podcast")
    store.remember(PLAYLIST_URL, "Example Playlist")

    store.forget([CHANNEL_URL])

    assert store.read_all() == {PLAYLIST_URL: "Example Playlist"}


def test_queue_page_shows_names_and_kinds(tmp_path: Path, monkeypatch) -> None:
    """A known name replaces the URL; an unknown one shows the short label."""
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(f"{CHANNEL_URL}\n{PLAYLIST_URL}\n", encoding="utf-8")
    monkeypatch.setattr(routes, "DATA_DIR", tmp_path)
    store = SourceMapStore(tmp_path / SOURCE_NAMES_FILE_NAME)
    store.remember(PLAYLIST_URL, "Example Playlist")
    lookup = _CountingLookup({})
    app = create_app(
        queue_store=QueueStore(urls_file, routes._logger),
        source_name_resolver=SourceNameResolver(store, lookup),
    )
    session_id = "names-session"
    app.state.sessions[session_id] = {"created_at": time.time()}
    request = SimpleNamespace(
        app=app, cookies={routes.SESSION_COOKIE: session_id}, query_params={}
    )

    body = routes.queue_page(request).body.decode("utf-8")
    app.state.source_name_resolver.close()

    assert ">Example Playlist</a>" in body
    assert ">@example-podcast</a>" in body
    assert ">Playlist</span>" in body and ">Channel</span>" in body
    # Only the source without a name was looked up.
    assert lookup.calls == [CHANNEL_URL]
