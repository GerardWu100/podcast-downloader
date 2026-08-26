"""FastAPI app for login, queue edits, and log viewing."""

from __future__ import annotations

import html
import logging
import math
import os
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import TypeVar, cast

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)

from ..config import ConfigError, PodcastConfig, load_config
from ..credentials import CREDENTIALS_FILENAME, load_ui_accounts
from ..log_timezone import LOG_TIME_ZONE
from ..media.urls import is_supported_media_url
from ..state.activity_store import (
    NO_DOWNLOAD_LOG_MESSAGE,
    ActivityLogStore,
    activity_log_file_for,
)
from ..state.archive_store import ArchiveStore
from ..notifications.apprise_client import (
    APPRISE_INFO_TYPE,
    AppriseNotifier,
    AppriseSettings,
    validate_server_url,
)
from ..state.auth_store import AuthStore
from ..state.bypass_store import BypassStore
from ..state.notification_store import (
    NotificationStore,
    notification_settings_file_for,
)
from ..state.queue_store import QueueStore
from ..trigger import DownloadTrigger, in_process_download_trigger
from .account_auth import (
    LOGIN_STATE_LOCK,
    CredentialCheck,
    check_credentials,
    is_banned,
)
from .auth import client_ip, request_is_secure, security_headers
from .queue_actions import add_url_to_queue
from .templates import (
    render_help_page,
    render_login_page,
    render_queue_page,
    render_settings_page,
)

_logger = logging.getLogger("api")
_Dependency = TypeVar("_Dependency")

router = APIRouter()

LOGIN_CSRF_TTL_SECONDS = 10 * 60
SESSION_COOKIE = "podcast_session"
SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
SESSIONS: dict[str, dict[str, float | str]] = {}
CSRF_TOKENS: dict[str, dict[str, float | str]] = {}  # session_id -> token metadata
_SESSION_STATE_LOCK = threading.Lock()
_CSRF_STATE_LOCK = threading.RLock()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# In Docker, PODCAST_DATA_DIR=/data (set in docker-compose.yml). Locally, falls back to PROJECT_ROOT.
DATA_DIR = Path(os.environ.get("PODCAST_DATA_DIR", str(PROJECT_ROOT)))
try:
    CONFIG = load_config(DATA_DIR / "config.ini", DATA_DIR)
except ConfigError as exc:
    raise SystemExit(f"[api] Startup error: {exc}") from exc
SESSION_STATE_FILE = DATA_DIR / ".ui_sessions.json"
# Icons, the web manifest, and the service worker ship with the code rather
# than living in the mounted data directory, so this path follows the package.
STATIC_DIR = Path(__file__).resolve().parent / "static"
SERVICE_WORKER_SOURCE = (STATIC_DIR / "service-worker.js").read_text(encoding="utf-8")
COOKIE_FILE_PERMISSION_MODE = 0o600
NETSCAPE_COOKIE_HEADER = "# Netscape HTTP Cookie File"
MAX_COOKIE_UPLOAD_BYTES = 5 * 1024 * 1024


def _app_state_value(
    request: Request,
    name: str,
    fallback: _Dependency,
) -> _Dependency:
    """Return one injected application dependency or its direct-call fallback."""
    request_app = getattr(request, "app", None)
    app_state = getattr(request_app, "state", None)
    if app_state is None:
        return fallback
    return cast(_Dependency, getattr(app_state, name, fallback))


def _request_config(request: Request) -> PodcastConfig:
    """Return configuration attached by ``create_app()``."""
    return _app_state_value(request, "config", CONFIG)


def _queue_store(request: Request) -> QueueStore:
    """Return the injected queue store, falling back for direct helper tests."""
    fallback = QueueStore(CONFIG.urls_file, _logger)
    return _app_state_value(request, "queue_store", fallback)


def _archive_store(request: Request) -> ArchiveStore:
    """Return the injected archive store, falling back for direct helper tests."""
    fallback = ArchiveStore(CONFIG.downloaded_urls_file, _logger)
    return _app_state_value(request, "archive_store", fallback)


def _bypass_store(request: Request) -> BypassStore:
    """Return the injected bypass store, falling back for direct helper tests."""
    fallback = BypassStore(CONFIG.bypass_age_check_file, _logger)
    return _app_state_value(request, "bypass_store", fallback)


def _activity_store(request: Request) -> ActivityLogStore:
    """Return the injected concise activity-log store."""
    fallback = ActivityLogStore(activity_log_file_for(CONFIG.log_file))
    return _app_state_value(request, "activity_store", fallback)


def _notification_store(request: Request) -> NotificationStore:
    """Return the request-scoped Apprise settings store."""
    return _app_state_value(
        request,
        "notification_store",
        NotificationStore(notification_settings_file_for(DATA_DIR)),
    )


def _download_trigger(request: Request) -> DownloadTrigger:
    """Return the injected object that wakes the scheduler."""
    return _app_state_value(
        request,
        "download_trigger",
        in_process_download_trigger,
    )


def _configured_cookie_file(request: Request) -> Path:
    """Return the writable cookie path used by yt-dlp.

    ``load_config`` only records ``cookies_file`` when the file exists at app
    startup. The browser upload is allowed to create the first runtime cookie
    file, so it falls back to the standard data-directory location.
    """
    config = _request_config(request)
    if config.cookies_file is not None:
        return config.cookies_file
    return config.urls_file.parent / "cookies.txt"


def _normalize_uploaded_cookie_text(raw_cookie_file: bytes) -> str | None:
    """Decode and validate an uploaded Netscape cookies.txt file.

    Parameters
    ----------
    raw_cookie_file:
        The exact bytes received from the browser upload field.

    Returns
    -------
    str | None
        The UTF-8 text with Linux ``LF`` newlines when the file starts with the
        Netscape cookie header, otherwise ``None``.
    """
    try:
        uploaded_text = raw_cookie_file.decode("utf-8")
    except UnicodeDecodeError:
        return None

    # Browser uploads from Windows often contain CRLF. yt-dlp accepts LF, and
    # normalizing here makes hashes and diffs stable across operating systems.
    normalized_text = uploaded_text.replace("\r\n", "\n").replace("\r", "\n")
    first_line = normalized_text.split("\n", maxsplit=1)[0].strip()
    if first_line != NETSCAPE_COOKIE_HEADER:
        return None

    if normalized_text.endswith("\n"):
        return normalized_text
    return f"{normalized_text}\n"


def _write_cookie_file(cookie_file: Path, normalized_cookie_text: str) -> None:
    """Atomically replace the configured cookie file with owner-only access."""
    cookie_file.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = cookie_file.with_name(f".{cookie_file.name}.tmp")
    temporary_file.write_text(
        normalized_cookie_text,
        encoding="utf-8",
        newline="\n",
    )
    temporary_file.chmod(COOKIE_FILE_PERMISSION_MODE)
    temporary_file.replace(cookie_file)
    cookie_file.chmod(COOKIE_FILE_PERMISSION_MODE)


def _credentials_file() -> Path:
    return DATA_DIR / CREDENTIALS_FILENAME


def _auth_store(request: Request | None = None) -> AuthStore:
    """Return injected authentication state or the production-path fallback."""
    fallback = AuthStore(
        session_file=SESSION_STATE_FILE,
        login_state_file=DATA_DIR / ".login_state.json",
    )
    if request is None:
        return fallback
    return _app_state_value(request, "auth_store", fallback)


def _sessions(request: Request | None = None) -> dict[str, dict[str, float | str]]:
    """Return the session map owned by this application instance."""
    if request is None:
        return SESSIONS
    return _app_state_value(request, "sessions", SESSIONS)


def _csrf_tokens(request: Request | None = None) -> dict[str, dict[str, float | str]]:
    """Return the CSRF-token map owned by this application instance."""
    if request is None:
        return CSRF_TOKENS
    return _app_state_value(request, "csrf_tokens", CSRF_TOKENS)


def _load_login_state(request: Request | None = None) -> dict:
    """Load client failure records through the locked authentication store."""
    return _auth_store(request).load_login_state()


def _security_headers(script_nonce: str | None = None) -> dict[str, str]:
    return security_headers(script_nonce)


def _cleanup_expired_sessions(request: Request | None = None) -> None:
    """Drop expired sessions and their CSRF tokens from memory and disk."""
    with _SESSION_STATE_LOCK:
        sessions = _sessions(request)
        csrf_tokens = _csrf_tokens(request)
        expired = [
            sid
            for sid, s in sessions.items()
            if _session_has_expired(s.get("created_at"))
        ]
        if not expired:
            return

        for sid in expired:
            sessions.pop(sid, None)
            with _CSRF_STATE_LOCK:
                csrf_tokens.pop(sid, None)
        _save_session_state(sessions, request)


def _cleanup_expired_login_csrf_tokens(
    request: Request | None = None,
) -> None:
    """Remove old login tokens so the in-memory map stays small."""
    _cleanup_expired_sessions(request)
    cutoff = time.time() - LOGIN_CSRF_TTL_SECONDS
    with _CSRF_STATE_LOCK:
        csrf_tokens = _csrf_tokens(request)
        expired_session_ids = [
            session_id
            for session_id, token_data in csrf_tokens.items()
            if str(token_data.get("kind", "")) == "login"
            and float(token_data.get("created_at", 0)) < cutoff
        ]
        for session_id in expired_session_ids:
            csrf_tokens.pop(session_id, None)


def _store_login_csrf_token(
    request: Request | None = None,
) -> tuple[str, str]:
    """Create and store a one-time login CSRF token."""
    _cleanup_expired_login_csrf_tokens(request)
    csrf_session_id = secrets.token_urlsafe(16)
    csrf_token = secrets.token_urlsafe(32)
    with _CSRF_STATE_LOCK:
        _csrf_tokens(request)[csrf_session_id] = {
            "token": csrf_token,
            "kind": "login",
            "created_at": time.time(),
        }
    return csrf_session_id, csrf_token


def _client_ip(request: Request) -> str:
    return client_ip(request, _request_config(request).trust_x_forwarded_for)


def _request_is_secure(request: Request) -> bool:
    return request_is_secure(
        request,
        _request_config(request).trust_x_forwarded_for,
    )


def _invalidate_session(
    session_id: str | None,
    request: Request | None = None,
) -> None:
    """Remove a session and its CSRF token."""
    if session_id:
        with _SESSION_STATE_LOCK:
            sessions = _sessions(request)
            sessions.pop(session_id, None)
            with _CSRF_STATE_LOCK:
                _csrf_tokens(request).pop(session_id, None)
            _save_session_state(sessions, request)


def _session_has_expired(created_at_raw: float | str | None) -> bool:
    """Return ``True`` when a session is older than the configured lifetime."""
    try:
        created_at = float(created_at_raw or 0)
    except (TypeError, ValueError):
        return True
    session_age_seconds = time.time() - created_at
    return not math.isfinite(created_at) or not (
        0 <= session_age_seconds <= SESSION_MAX_AGE_SECONDS
    )


def _load_session_state(
    request: Request | None = None,
) -> dict[str, dict[str, float | str]]:
    return _auth_store(request).load_sessions(SESSION_MAX_AGE_SECONDS)


def _save_session_state(
    state: dict[str, dict[str, float | str]],
    request: Request | None = None,
) -> None:
    _auth_store(request).save_sessions(state)


SESSIONS = _load_session_state()


def _require_login(request: Request) -> RedirectResponse | None:
    """Check the current session and redirect to login when it has expired."""
    session_id = request.cookies.get(SESSION_COOKIE)
    session = _sessions(request).get(session_id)
    if not session:
        return RedirectResponse(url="/login", status_code=302)

    if _session_has_expired(session.get("created_at")):
        _invalidate_session(session_id, request)
        return RedirectResponse(url="/login", status_code=302)

    return None


def _has_valid_session(request: Request) -> bool:
    """Return whether the request carries an active remembered session.

    Public entry pages such as ``/`` and ``/login`` use this check to send an
    already-authenticated browser straight to the queue at ``/``.
    """
    return _require_login(request) is None


def _get_csrf_token(session_id: str, request: Request | None = None) -> str:
    """Return the CSRF token for a session, creating one if needed."""
    with _CSRF_STATE_LOCK:
        csrf_tokens = _csrf_tokens(request)
        token_data = csrf_tokens.get(session_id)
        token = str(token_data.get("token", "")) if token_data else ""
        if not token:
            token = secrets.token_urlsafe(32)
            csrf_tokens[session_id] = {
                "token": token,
                "kind": "session",
                "created_at": time.time(),
            }
        return token


def _verify_csrf_token(request: Request, csrf_token: str) -> bool:
    """Check that the submitted CSRF token matches the stored session token."""
    session_id = request.cookies.get(SESSION_COOKIE)
    with _CSRF_STATE_LOCK:
        token_data = _csrf_tokens(request).get(session_id, {})
        expected = str(token_data.get("token", ""))
    if not expected:
        return False
    return secrets.compare_digest(csrf_token, expected)


def _set_session_cookie(
    response: RedirectResponse, request: Request, session_id: str
) -> None:
    """Set the session cookie with an explicit lifetime and HTTPS when possible."""
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        httponly=True,
        samesite="lax",
        max_age=SESSION_MAX_AGE_SECONDS,
        secure=_request_is_secure(request),
    )


def _delete_session_cookie(response: RedirectResponse) -> None:
    """Delete the session cookie during logout."""
    response.delete_cookie(SESSION_COOKIE)


def _last_activity_label(activity_log_file: Path) -> str:
    """Return the latest activity-file update time for the status header.

    Parameters
    ----------
    activity_log_file:
        Path to the concise browser activity log.

    Returns
    -------
    str
        Toronto-local update time, or a short empty-state label when the file
        has not been written yet.
    """
    try:
        modified_at = activity_log_file.stat().st_mtime
    except OSError:
        return "No activity yet"
    return datetime.fromtimestamp(modified_at, tz=LOG_TIME_ZONE).strftime(
        "%Y-%m-%d %H:%M"
    )


# One activity line looks like "[2026-08-19 15:51] Downloaded: creator - ep.mp3".
# The status row shows the episode name, so the timestamp is discarded and the
# ".mp3" suffix is trimmed off the saved file name.
DOWNLOADED_EVENT_PREFIX = "Downloaded: "
DOWNLOADED_FILE_SUFFIX = ".mp3"
# How far back to look for the most recent finished download. A run that only
# fails can push completions out of this window, in which case the row reads
# "None yet" rather than showing a stale name.
DOWNLOADED_EVENT_SEARCH_LINES = 400
NO_DOWNLOAD_YET_LABEL = "None yet"
# Episode names can run very long. Anything past this many characters is cut
# and replaced with an ellipsis so the status row stays on one line.
LAST_DOWNLOAD_NAME_MAX_CHARS = 70


def _last_download_label(activity_store: ActivityLogStore) -> str:
    """Return the name of the most recent download, for the status row.

    Parameters
    ----------
    activity_store:
        Store for the concise browser activity log.

    Returns
    -------
    str
        Episode name from the newest ``Downloaded:`` event, without the ".mp3"
        suffix and shortened when very long, or a short empty-state label when
        no completed download is in the recent window.
    """
    recent_activity = activity_store.read_tail(
        DOWNLOADED_EVENT_SEARCH_LINES,
        empty_message="",
    )
    for line in reversed(recent_activity.splitlines()):
        _timestamp, separator, message = line.partition("] ")
        if not separator or not message.startswith(DOWNLOADED_EVENT_PREFIX):
            continue
        # "Downloaded: creator - ep.mp3" -> "creator - ep"
        name = message[len(DOWNLOADED_EVENT_PREFIX) :].strip()
        if name.endswith(DOWNLOADED_FILE_SUFFIX):
            name = name[: -len(DOWNLOADED_FILE_SUFFIX)]
        if not name:
            continue
        if len(name) > LAST_DOWNLOAD_NAME_MAX_CHARS:
            name = name[: LAST_DOWNLOAD_NAME_MAX_CHARS - 1].rstrip() + "\u2026"
        return name
    return NO_DOWNLOAD_YET_LABEL


@router.get("/help", response_class=HTMLResponse)
def help_page() -> HTMLResponse:
    """Return the public usage guide rendered by the template module."""
    return render_help_page(_security_headers)


@router.get("/sw.js")
def service_worker() -> Response:
    """Serve the service worker from the site root.

    A service worker can only control pages at or below its own address, so
    this file cannot be served from `/static/` like the icons are. Served from
    `/static/service-worker.js` it would control nothing but `/static/`, and
    the browser would never offer to install the site.

    The route is deliberately public. Browsers fetch both this file and the web
    manifest without sending the session cookie, so requiring a login here
    would break installation for a signed-in user.

    Returns
    -------
    fastapi.responses.Response
        JavaScript source for the worker registered by every page.
    """
    return Response(
        content=SERVICE_WORKER_SOURCE,
        media_type="text/javascript",
        headers={
            # Browsers re-check the worker on navigation. `no-cache` still
            # allows storing it, but forces revalidation, so a redeploy is
            # picked up instead of being pinned by a proxy or Cloudflare.
            "Cache-Control": "no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request) -> Response:
    """Render the login form and show any login error state."""
    if _has_valid_session(request):
        return RedirectResponse(url="/", status_code=302)

    raw_message = request.query_params.get("msg", "")
    message_map = {
        "csrf": ("msg-err", "Your login form expired. Try again."),
        "banned": ("msg-err", "Too many failed attempts. Try again later."),
        "bad_credentials": ("msg-err", "Invalid username or password."),
        "unconfigured": (
            "msg-err",
            "Login not configured. Set UI_USERNAME and UI_PASSWORD in .env "
            "and restart.",
        ),
        "request": ("msg-err", "Invalid request."),
    }
    message_class, message_text = message_map.get(raw_message, ("", ""))
    safe_message_text = html.escape(message_text)

    with LOGIN_STATE_LOCK:
        banned, banned_until = is_banned(
            _load_login_state(request), _client_ip(request)
        )
    if banned:
        remaining = int(banned_until - time.time())
        message_class = "msg-err"
        safe_message_text = html.escape(
            f"Too many failed attempts. Try again in {remaining} seconds."
        )

    csrf_session_id, csrf_token = _store_login_csrf_token(request)
    safe_token = html.escape(csrf_token)
    safe_csrf_session = html.escape(csrf_session_id)
    script_nonce = secrets.token_urlsafe(16)
    message_html = ""
    if message_class and safe_message_text:
        message_html = f'<div class="{message_class}">{safe_message_text}</div>'

    return render_login_page(
        message_html=message_html,
        safe_csrf_session=safe_csrf_session,
        safe_token=safe_token,
        script_nonce=script_nonce,
        headers=_security_headers(script_nonce),
    )


@router.post("/login")
def login_action(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    csrf_session: str = Form(...),
) -> RedirectResponse:
    """Validate a login attempt and start a remembered browser session.

    Parameters
    ----------
    request:
        Current FastAPI request carrying application dependencies and client
        network information.
    username:
        Account name submitted by the browser, compared against the value
        stored in ``.ui_credentials.json``.
    password:
        Plain-text password submitted by the browser.
    csrf_token:
        One-time Cross-Site Request Forgery token from the login form.
    csrf_session:
        Identifier used to find the server-side login token.

    Returns
    -------
    RedirectResponse
        Redirect to the queue after success or to a login status after failure.
    """
    # Validate the CSRF token before reading password state or updating bans.
    with _CSRF_STATE_LOCK:
        token_data = _csrf_tokens(request).pop(csrf_session, {})
    expected_csrf = str(token_data.get("token", ""))
    issued_at = float(token_data.get("created_at", 0) or 0)
    token_age_seconds = time.time() - issued_at
    if (
        not expected_csrf
        or token_age_seconds > LOGIN_CSRF_TTL_SECONDS
        or not secrets.compare_digest(csrf_token, expected_csrf)
    ):
        return RedirectResponse(url="/login?msg=csrf", status_code=303)

    # account_auth.check_credentials owns the ban ledger, the constant-time
    # name comparison, and the decoy password hash. The JSON API in
    # api_routes.py calls the same function, so neither door can end up with
    # weaker rules than the other. Its outcome values are this page's message
    # keys, which is why the failure branch can pass one straight through.
    outcome = check_credentials(
        username,
        password,
        accounts=load_ui_accounts(_credentials_file()),
        auth_store=_auth_store(request),
        client_address=_client_ip(request),
    )
    if outcome is not CredentialCheck.ACCEPTED:
        return RedirectResponse(url=f"/login?msg={outcome}", status_code=303)

    session_id = secrets.token_urlsafe(32)
    with _SESSION_STATE_LOCK:
        sessions = _sessions(request)
        sessions[session_id] = {"created_at": time.time()}
        _save_session_state(sessions, request)
    response = RedirectResponse(url="/", status_code=302)
    _set_session_cookie(response, request, session_id)
    return response


@router.post("/logout")
def logout(
    request: Request,
    csrf_token: str = Form(...),
) -> RedirectResponse:
    if not _verify_csrf_token(request, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    session_id = request.cookies.get(SESSION_COOKIE)
    _invalidate_session(session_id, request)
    response = RedirectResponse(url="/login", status_code=302)
    _delete_session_cookie(response)
    return response


_MSG_DISPLAY: dict[str, tuple[str, str]] = {
    "added": ("msg-ok", "Source added to the queue."),
    "removed": ("msg-ok", "Source removed from the queue."),
    "duplicate": ("msg-warn", "This source is already in the queue."),
    "downloaded": ("msg-warn", "This source has already been downloaded."),
    "notfound": ("msg-warn", "That source is no longer in the queue."),
    "invalid": ("msg-err", "Invalid URL. Enter an http(s) media URL."),
    "error": ("msg-err", "Could not add that source."),
    "cookies_updated": ("msg-ok", "YouTube access file updated."),
    "cookies_invalid": (
        "msg-err",
        "Invalid cookies.txt. Upload a Netscape-format file.",
    ),
    "cookies_error": ("msg-err", "Could not update cookies.txt."),
    "notifications_saved": ("msg-ok", "Notification settings saved."),
    "notifications_invalid": (
        "msg-err",
        "Check the Apprise notify URL. It must start with http:// or https://",
    ),
    "notifications_error": ("msg-err", "Could not save notification settings."),
}


@router.get("/", response_class=HTMLResponse)
def queue_page(request: Request, msg: str = "") -> HTMLResponse:
    """Render the authenticated queue, controls, and activity status.

    This is the site root, so the address a person types or bookmarks is the
    page they came for. A browser without a valid session is sent to ``/login``
    and returns here after signing in.

    Parameters
    ----------
    request:
        Current FastAPI request with session and application dependencies.
    msg:
        Optional known status key displayed above the queue.

    Returns
    -------
    HTMLResponse
        Queue page, or a login redirect when the session is invalid.
    """
    redirect = _require_login(request)
    if redirect:
        return redirect

    session_id = request.cookies.get(SESSION_COOKIE, "")
    csrf_token = _get_csrf_token(session_id, request)
    safe_token = html.escape(csrf_token)
    script_nonce = secrets.token_urlsafe(16)

    # Only render the message keys this page knows about.
    msg_html = ""
    if msg in _MSG_DISPLAY:
        css_class, display_text = _MSG_DISPLAY[msg]
        msg_html = f'<div class="{css_class}">{html.escape(display_text)}</div>'

    config = _request_config(request)
    if config.min_channel_video_age_hours > 0:
        bypass_label = html.escape(
            "Run now (skip the wait or download a full playlist)"
        )
    else:
        bypass_label = html.escape("Run now (download a full playlist)")
    bypass_row_html = f"""
        <div class="bypass-row">
          <label>
            <input type="checkbox" name="skip_age_check" value="1" />
            {bypass_label}
          </label>
        </div>
        """

    queue_urls = _queue_store(request).load_normalized_urls()
    safe_queue_urls = [html.escape(url) for url in queue_urls]

    if safe_queue_urls:
        items = "".join(
            f'<li class="q-item"><span class="q-dot"></span>'
            f'<span class="q-url">{safe_url}</span>'
            f'<form method="post" action="/remove-url" class="remove-form">'
            f'<input type="hidden" name="csrf_token" value="{safe_token}" />'
            f'<input type="hidden" name="url" value="{safe_url}" />'
            f'<button type="submit" class="btn-remove">Remove</button>'
            f"</form></li>"
            for safe_url in safe_queue_urls
        )
        queue_html = f'<ul class="q-list">{items}</ul>'
    else:
        queue_html = '<p class="empty">No sources are being monitored.</p>'

    count = len(safe_queue_urls)
    activity_store = _activity_store(request)
    last_activity = html.escape(
        _last_activity_label(activity_store.activity_log_file)
    )
    last_download = html.escape(_last_download_label(activity_store))

    return render_queue_page(
        bypass_row_html=bypass_row_html,
        count=count,
        last_activity=last_activity,
        last_download=last_download,
        msg_html=msg_html,
        queue_html=queue_html,
        safe_token=safe_token,
        script_nonce=script_nonce,
        headers=_security_headers(script_nonce),
    )


@router.get("/settings", response_class=HTMLResponse)
def settings(request: Request, msg: str = "") -> HTMLResponse:
    """Render the settings page for cookies and error notifications.

    Parameters
    ----------
    request:
        Current request with the session and the settings store.
    msg:
        Optional known status key displayed at the top of the page.

    Returns
    -------
    HTMLResponse
        Settings page, or a login redirect when the session is invalid.
    """
    redirect = _require_login(request)
    if redirect:
        return redirect

    session_id = request.cookies.get(SESSION_COOKIE, "")
    safe_token = html.escape(_get_csrf_token(session_id, request))
    script_nonce = secrets.token_urlsafe(16)

    msg_html = ""
    if msg in _MSG_DISPLAY:
        css_class, display_text = _MSG_DISPLAY[msg]
        msg_html = f'<div class="{css_class}">{html.escape(display_text)}</div>'

    notification_settings = _notification_store(request).load()
    return render_settings_page(
        safe_token=safe_token,
        safe_server_url=html.escape(notification_settings.server_url, quote=True),
        safe_notification_urls=html.escape(
            notification_settings.notification_urls,
            quote=True,
        ),
        safe_tag=html.escape(notification_settings.tag, quote=True),
        notifications_enabled=notification_settings.enabled,
        msg_html=msg_html,
        script_nonce=script_nonce,
        headers=_security_headers(script_nonce),
    )


@router.post("/upload-cookies")
async def upload_cookies_form(
    request: Request,
    csrf_token: str = Form(...),
    cookie_file: UploadFile = File(...),
) -> RedirectResponse:
    """Replace the runtime yt-dlp cookies.txt file from an authenticated upload."""
    redirect = _require_login(request)
    if redirect:
        return redirect

    if not _verify_csrf_token(request, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    # Read one byte past the limit rather than the whole upload. Reading it all
    # first would pull a multi-gigabyte body into memory before the size check
    # could reject it, so an oversized file is refused here instead.
    raw_cookie_file = await cookie_file.read(MAX_COOKIE_UPLOAD_BYTES + 1)
    if len(raw_cookie_file) > MAX_COOKIE_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Cookie file is too large")
    normalized_cookie_text = _normalize_uploaded_cookie_text(raw_cookie_file)
    if normalized_cookie_text is None:
        return RedirectResponse(url="/settings?msg=cookies_invalid", status_code=303)

    try:
        _write_cookie_file(_configured_cookie_file(request), normalized_cookie_text)
    except OSError:
        _logger.exception("Could not update cookies file")
        return RedirectResponse(url="/settings?msg=cookies_error", status_code=303)

    return RedirectResponse(url="/settings?msg=cookies_updated", status_code=303)


@router.post("/save-notifications")
def save_notifications_form(
    request: Request,
    csrf_token: str = Form(...),
    server_url: str = Form(""),
    notification_urls: str = Form(""),
    tag: str = Form(""),
    enabled: str = Form(""),
) -> RedirectResponse:
    """Save the Apprise error-notification settings from the settings page.

    Parameters
    ----------
    request:
        Current request carrying the session and the settings store.
    csrf_token:
        Token issued with the page that submitted this form.
    server_url:
        Apprise notify endpoint, for example ``http://apprise:8000/notify/key``.
    notification_urls:
        Optional comma-separated Apprise destinations for stateless mode.
    tag:
        Optional Apprise tag limiting which configured destinations fire.
    enabled:
        Present and non-empty when the enable checkbox was ticked.

    Returns
    -------
    RedirectResponse
        Back to the settings page with a status message.
    """
    redirect = _require_login(request)
    if redirect:
        return redirect

    if not _verify_csrf_token(request, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    is_enabled = bool(enabled)
    # An endpoint is only required once notifications are switched on, so the
    # settings can be cleared and saved without tripping validation.
    if is_enabled and validate_server_url(server_url):
        return RedirectResponse(url="/settings?msg=notifications_invalid", status_code=303)

    settings = AppriseSettings(
        enabled=is_enabled,
        server_url=server_url.strip(),
        notification_urls=notification_urls.strip(),
        tag=tag.strip(),
    )
    try:
        _notification_store(request).save(settings)
    except OSError:
        _logger.exception("Could not save notification settings")
        return RedirectResponse(url="/settings?msg=notifications_error", status_code=303)

    return RedirectResponse(url="/settings?msg=notifications_saved", status_code=303)


@router.post("/test-notification")
def test_notification(
    request: Request,
    csrf_token: str = Form(...),
    server_url: str = Form(""),
    notification_urls: str = Form(""),
    tag: str = Form(""),
) -> Response:
    """Send a test notification using the values currently in the form.

    The form values are used rather than the saved ones so the endpoint can be
    tried before it is saved.

    Returns
    -------
    Response
        JSON with ``ok`` and a ``detail`` string the page shows beside the
        button. Always HTTP 200 when authorized, because a refused Apprise
        request is a result to display, not a web-app error.
    """
    if not _has_valid_session(request):
        return JSONResponse(
            {"ok": False, "detail": "Session expired. Sign in again."},
            status_code=401,
        )

    if not _verify_csrf_token(request, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    url_problem = validate_server_url(server_url)
    if url_problem:
        return JSONResponse({"ok": False, "detail": url_problem})

    # `enabled` is forced on: pressing Test is the intent to send, whether or
    # not notifications are switched on for real downloads yet.
    notifier = AppriseNotifier(
        AppriseSettings(
            enabled=True,
            server_url=server_url.strip(),
            notification_urls=notification_urls.strip(),
            tag=tag.strip(),
        ),
        _logger,
    )
    result = notifier.send(
        "Podcast Downloader test",
        "Apprise is reachable. Download failures will arrive here.",
        notification_type=APPRISE_INFO_TYPE,
    )
    return JSONResponse({"ok": result.ok, "detail": result.detail})


_LOG_SOURCES = frozenset({"activity", "download"})


@router.get("/logs")
def view_logs(request: Request, source: str = "activity") -> Response:
    """Return a tail of ``activity.log`` or ``download.log`` as plain text.

    This endpoint is polled by the queue page's auto-refresh rather than opened
    by the browser directly, so an expired session answers ``401`` instead of
    redirecting. A redirect would be followed by ``fetch`` and hand the script
    the login page's HTML, which it would then render as log lines.
    """
    if _require_login(request) is not None:
        return Response(
            content="Session expired.",
            media_type="text/plain",
            status_code=401,
            headers=_security_headers(),
        )

    log_source = source if source in _LOG_SOURCES else "activity"
    error_message = (
        "Could not read download log."
        if log_source == "download"
        else "Could not read activity log."
    )

    try:
        if log_source == "download":
            config = _request_config(request)
            tail = ActivityLogStore(config.log_file).read_tail(
                empty_message=NO_DOWNLOAD_LOG_MESSAGE
            )
        else:
            tail = _activity_store(request).read_tail()
        return Response(
            content=tail, media_type="text/plain", headers=_security_headers()
        )
    except Exception:
        return Response(
            content=error_message,
            media_type="text/plain",
            headers=_security_headers(),
        )


@router.post("/add-url")
def add_url_form(
    request: Request,
    url: str = Form(...),
    csrf_token: str = Form(...),
    skip_age_check: str = Form(default=""),
) -> RedirectResponse:
    """Add one validated URL and request its applicable scheduler workflow.

    Parameters
    ----------
    request:
        Current FastAPI request with session and application dependencies.
    url:
        Candidate direct video, YouTube channel, or YouTube playlist URL.
    csrf_token:
        Cross-Site Request Forgery token tied to the remembered session.
    skip_age_check:
        Non-empty when the browser requests immediate direct-video or full
        playlist processing.

    Returns
    -------
    RedirectResponse
        Queue-page redirect with the mutation outcome in its message key.
    """
    redirect = _require_login(request)
    if redirect:
        return redirect

    if not _verify_csrf_token(request, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    # add_url_to_queue holds the validation, normalization, duplicate, and
    # scheduler rules, shared with the JSON API in api_routes.py so both entry
    # points behave identically. Its outcome values are the queue page's
    # message keys.
    result = add_url_to_queue(
        url,
        skip_age_check=bool(skip_age_check),
        queue_store=_queue_store(request),
        archive_store=_archive_store(request),
        bypass_store=_bypass_store(request),
        download_trigger=_download_trigger(request),
    )

    return RedirectResponse(url=f"/?msg={result.outcome}", status_code=303)


@router.post("/remove-url")
def remove_url_form(
    request: Request,
    url: str = Form(...),
    csrf_token: str = Form(...),
) -> RedirectResponse:
    """Remove one monitored URL from the queue."""
    redirect = _require_login(request)
    if redirect:
        return redirect

    if not _verify_csrf_token(request, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    if not is_supported_media_url(url):
        return RedirectResponse(url="/?msg=invalid", status_code=303)

    removed = _queue_store(request).remove_url(url)
    if not removed:
        return RedirectResponse(url="/?msg=notfound", status_code=303)

    return RedirectResponse(url="/?msg=removed", status_code=303)
