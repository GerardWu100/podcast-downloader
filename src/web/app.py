"""Build the FastAPI web application and its saved-state dependencies."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ..config import PodcastConfig
from ..credentials import CREDENTIALS_FILENAME
from ..state.activity_store import ActivityLogStore, activity_log_file_for
from ..state.archive_store import ArchiveStore
from ..state.auth_store import AuthStore
from ..state.bypass_store import BypassStore
from ..state.notification_store import (
    NotificationStore,
    notification_settings_file_for,
)
from ..state.queue_store import QueueStore
from ..trigger import DownloadTrigger, in_process_download_trigger
from . import api_routes, routes

_logger = logging.getLogger("web.app")


def create_app(
    config: PodcastConfig | None = None,
    *,
    queue_store: QueueStore | None = None,
    archive_store: ArchiveStore | None = None,
    bypass_store: BypassStore | None = None,
    activity_store: ActivityLogStore | None = None,
    auth_store: AuthStore | None = None,
    notification_store: NotificationStore | None = None,
    trigger: DownloadTrigger | None = None,
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
    notification_store:
        Optional Apprise settings collaborator.
    trigger:
        Optional in-process scheduler wake-up collaborator.

    Returns
    -------
    FastAPI
        Application exposed by ``uvicorn src.api:app``.
    """
    # Construct every production collaborator in one place. Tests may replace
    # any member with a store rooted in a temporary directory.
    resolved_config = config if config is not None else routes.CONFIG
    if queue_store is None:
        queue_store = QueueStore(resolved_config.urls_file, _logger)
    if archive_store is None:
        archive_store = ArchiveStore(
            resolved_config.downloaded_urls_file,
            _logger,
        )
    if bypass_store is None:
        bypass_store = BypassStore(
            resolved_config.bypass_age_check_file,
            _logger,
        )
    if activity_store is None:
        activity_store = ActivityLogStore(
            activity_log_file_for(resolved_config.log_file)
        )
    if auth_store is None:
        auth_store = AuthStore(
            session_file=routes.SESSION_STATE_FILE,
            login_state_file=routes.DATA_DIR / ".login_state.json",
        )
    if notification_store is None:
        notification_store = NotificationStore(
            notification_settings_file_for(routes.DATA_DIR)
        )
    if trigger is None:
        trigger = in_process_download_trigger

    # Keep dependencies on app.state so every request uses the same objects
    # that were created or supplied here.
    app = FastAPI(
        title="Podcast Downloader",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.config = resolved_config
    app.state.queue_store = queue_store
    app.state.archive_store = archive_store
    app.state.bypass_store = bypass_store
    app.state.activity_store = activity_store
    app.state.auth_store = auth_store
    app.state.notification_store = notification_store
    app.state.sessions = auth_store.load_sessions(routes.SESSION_MAX_AGE_SECONDS)
    app.state.csrf_tokens = {}
    app.state.download_trigger = trigger
    # The /api routes check the same accounts as the login form, so they
    # need the file those accounts are stored in.
    app.state.credentials_file = routes.DATA_DIR / CREDENTIALS_FILENAME
    app.include_router(routes.router)
    app.include_router(api_routes.router)
    # Icons and the web manifest, served so a phone can install the site as an
    # app. These are public: browsers fetch a manifest without the session
    # cookie, so putting them behind the login would break installation.
    app.mount(
        "/static",
        StaticFiles(directory=routes.STATIC_DIR),
        name="static",
    )
    return app
