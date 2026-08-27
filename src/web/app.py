"""Build the FastAPI web application and its saved-state dependencies."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
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


def api_body_size_refusal(request: Request) -> JSONResponse | None:
    """Return an early refusal for an unsafe ``POST /api/add-url`` body.

    FastAPI reads and validates a JSON body before it enters the route handler.
    This check therefore runs in middleware, before authentication or parsing,
    and requires the transport to declare a small size.

    Parameters
    ----------
    request:
        Incoming request whose method, path, and ``Content-Length`` are checked.

    Returns
    -------
    JSONResponse | None
        A ``411``, ``400``, or ``413`` response when the body cannot be safely
        bounded; otherwise ``None`` so normal routing can continue.
    """
    if request.method != "POST" or request.url.path != "/api/add-url":
        return None

    raw_content_length = request.headers.get("content-length")
    if raw_content_length is None:
        return JSONResponse(
            {"detail": "Content-Length is required."},
            status_code=411,
        )
    try:
        content_length = int(raw_content_length)
    except ValueError:
        return JSONResponse(
            {"detail": "Content-Length must be a non-negative integer."},
            status_code=400,
        )
    if content_length < 0:
        return JSONResponse(
            {"detail": "Content-Length must be a non-negative integer."},
            status_code=400,
        )
    if content_length > api_routes.MAX_API_REQUEST_BODY_BYTES:
        return JSONResponse(
            {"detail": "Request body is too large."},
            status_code=413,
        )
    return None


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

    @app.middleware("http")
    async def limit_api_request_body(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Bound API JSON before FastAPI buffers it or hashes credentials."""
        refusal = api_body_size_refusal(request)
        if refusal is not None:
            return refusal
        return await call_next(request)

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
