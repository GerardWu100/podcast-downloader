"""Build the FastAPI web application and its saved-state dependencies."""

from __future__ import annotations

import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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
from ..state.run_state_store import RunStateStore, run_state_file_for
from ..trigger import DownloadTrigger, in_process_download_trigger
from . import api_routes, routes

_logger = logging.getLogger("web.app")


# Largest body any browser form on the site needs. The biggest field is the
# notification URL list, a few kilobytes at most.
MAX_FORM_REQUEST_BODY_BYTES = 256 * 1024
# Multipart framing (boundaries, part headers, the CSRF field) around an
# uploaded cookie file.
MULTIPART_OVERHEAD_BYTES = 64 * 1024
COOKIE_UPLOAD_PATH = "/upload-cookies"
API_ADD_URL_PATH = "/api/add-url"


def post_body_limit_bytes(path: str) -> int:
    """Return the largest ``POST`` body, in bytes, that a route may receive."""
    if path == API_ADD_URL_PATH:
        return api_routes.MAX_API_REQUEST_BODY_BYTES
    if path == COOKIE_UPLOAD_PATH:
        return routes.MAX_COOKIE_UPLOAD_BYTES + MULTIPART_OVERHEAD_BYTES
    return MAX_FORM_REQUEST_BODY_BYTES


def post_body_size_refusal(request: Request) -> JSONResponse | None:
    """Return an early refusal for a ``POST`` body larger than its route needs.

    FastAPI reads and parses a whole JSON or form body, including uploaded
    files, before the route handler runs its login check. This check therefore
    runs in middleware, before authentication or parsing, using the declared
    ``Content-Length``. The API route also requires that header, because its
    clients are programs that always send it. A body sent without the header
    is bounded while it streams, by ``PostBodyLimitMiddleware``.

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
    if request.method != "POST":
        return None

    path = request.url.path
    body_limit = post_body_limit_bytes(path)

    raw_content_length = request.headers.get("content-length")
    if raw_content_length is None:
        if path != API_ADD_URL_PATH:
            return None
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
    if content_length > body_limit:
        return JSONResponse(
            {"detail": "Request body is too large."},
            status_code=413,
        )
    return None


class PostBodyLimitMiddleware:
    """Refuse ``POST`` bodies larger than their route needs, declared or not.

    The declared ``Content-Length`` is checked first, so an honest oversized
    request is refused before any of it is read. A chunked body has no declared
    length, so the bytes are also counted as the application reads them. Once
    the count passes the limit, reading raises a 413 ``HTTPException``, which
    FastAPI passes through its body parser unchanged, so the upload stops there
    instead of being spooled to disk in full.

    Parameters
    ----------
    app:
        The ASGI application to wrap.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return

        refusal = post_body_size_refusal(Request(scope))
        if refusal is not None:
            await refusal(scope, receive, send)
            return

        body_limit = post_body_limit_bytes(scope["path"])
        received_bytes = 0

        async def receive_within_limit() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > body_limit:
                    raise StarletteHTTPException(
                        status_code=413, detail="Request body is too large."
                    )
            return message

        await self.app(scope, receive_within_limit, send)


def create_app(
    config: PodcastConfig | None = None,
    *,
    queue_store: QueueStore | None = None,
    archive_store: ArchiveStore | None = None,
    bypass_store: BypassStore | None = None,
    activity_store: ActivityLogStore | None = None,
    auth_store: AuthStore | None = None,
    notification_store: NotificationStore | None = None,
    run_state_store: RunStateStore | None = None,
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
    run_state_store:
        Optional last-run record collaborator.
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
    if run_state_store is None:
        run_state_store = RunStateStore(run_state_file_for(routes.DATA_DIR))
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

    # Bound POST bodies before FastAPI buffers them or checks the login.
    app.add_middleware(PostBodyLimitMiddleware)

    app.state.config = resolved_config
    app.state.queue_store = queue_store
    app.state.archive_store = archive_store
    app.state.bypass_store = bypass_store
    app.state.activity_store = activity_store
    app.state.auth_store = auth_store
    app.state.notification_store = notification_store
    app.state.run_state_store = run_state_store
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
