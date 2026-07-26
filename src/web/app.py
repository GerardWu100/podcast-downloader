"""Construct the FastAPI web application."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI

from ..config import PodcastConfig
from ..state.activity_store import ActivityLogStore, activity_log_file_for
from ..state.archive_store import ArchiveStore
from ..state.auth_store import AuthStore
from ..state.bypass_store import BypassStore
from ..state.queue_store import QueueStore
from ..trigger import download_trigger
from . import routes

_logger = logging.getLogger("web.app")


def create_app(
    config: PodcastConfig | None = None,
    *,
    queue_store: QueueStore | None = None,
    archive_store: ArchiveStore | None = None,
    bypass_store: BypassStore | None = None,
    activity_store: ActivityLogStore | None = None,
    auth_store: AuthStore | None = None,
    trigger: Any | None = None,
) -> FastAPI:
    """Return the configured FastAPI application.

    Parameters
    ----------
    config:
        Validated runtime configuration.
    queue_store:
        Optional queue collaborator for application tests.
    archive_store:
        Optional downloaded-URL archive collaborator for application tests.
    bypass_store:
        Optional one-shot age-bypass collaborator for application tests.
    activity_store:
        Optional activity-log collaborator for application tests.
    auth_store:
        Optional remembered-session and login-failure collaborator.
    trigger:
        Optional in-process scheduler wake-up collaborator.

    Returns
    -------
    FastAPI
        Application exposed by ``uvicorn src.api:app``.
    """
    # Construct every production collaborator in one place. Tests may replace
    # any member with a store rooted in a temporary directory.
    resolved_config = config or routes.CONFIG
    app = FastAPI(
        title="Podcast URL Ingest",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.config = resolved_config
    app.state.queue_store = queue_store or QueueStore(
        resolved_config.urls_file,
        _logger,
    )
    app.state.archive_store = archive_store or ArchiveStore(
        resolved_config.downloaded_urls_file,
        _logger,
    )
    app.state.bypass_store = bypass_store or BypassStore(
        resolved_config.bypass_age_check_file,
        _logger,
    )
    app.state.activity_store = activity_store or ActivityLogStore(
        activity_log_file_for(resolved_config.log_file)
    )
    app.state.auth_store = auth_store or AuthStore(
        session_file=routes.SESSION_STATE_FILE,
        login_state_file=routes.DATA_DIR / ".login_state.json",
    )
    app.state.download_trigger = trigger or download_trigger
    app.include_router(routes.router)
    return app
