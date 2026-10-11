"""Expose the production web app to Uvicorn."""

from __future__ import annotations

import logging

from .media.youtube import get_source_display_name
from .state.source_map_store import SOURCE_NAMES_FILE_NAME, SourceMapStore
from .web import routes
from .web.app import create_app
from .web.source_names import SourceNameResolver

_logger = logging.getLogger("web.source_names")


def _look_up_source_name(url: str) -> str | None:
    """Ask yt-dlp for a source's name, with the configured YouTube cookies."""
    return get_source_display_name(
        url,
        _logger,
        routes.CONFIG.cookies_file,
        routes.CONFIG.always_use_cookies,
    )


# Only the real server looks names up. Tests build apps without a resolver, so
# they never call yt-dlp or the network.
app = create_app(
    source_name_resolver=SourceNameResolver(
        SourceMapStore(routes.DATA_DIR / SOURCE_NAMES_FILE_NAME),
        _look_up_source_name,
    )
)
