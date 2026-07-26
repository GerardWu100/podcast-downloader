"""FastAPI app for login, queue edits, and log viewing."""

from __future__ import annotations

import html
import logging
import os
import secrets
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ..config import ConfigError, load_config
from ..log_timezone import LOG_TIME_ZONE
from ..passwords import LEGACY_PASSWORD_PLACEHOLDER, verify_password
from ..trigger import (
    pop_full_playlist_download_requests,
    pop_single_url_download_requests,
    queue_full_playlist_download,
    queue_single_url_download,
)
from ..media.urls import is_supported_media_url
from ..media.youtube import (
    is_channel_or_playlist,
    is_youtube_playlist,
    is_youtube_url,
    normalize_youtube_url,
)
from ..state.activity_store import (
    NO_DOWNLOAD_LOG_MESSAGE,
    ActivityLogStore,
    activity_log_file_for,
)
from ..state.archive_store import ArchiveStore
from ..state.auth_store import AuthStore
from ..state.bypass_store import BypassStore
from ..state.queue_store import QueueStore
from .auth import client_ip, request_is_secure, security_headers
from .templates import render_help_page, render_login_page, render_queue_page

_logger = logging.getLogger("api")

# Tests and older callers reset pending trigger state through this module.
__all__ = [
    "router",
    "pop_full_playlist_download_requests",
    "pop_single_url_download_requests",
]

router = APIRouter()

MAX_FAILED_ATTEMPTS = 5
FAIL_WINDOW_SECONDS = 10 * 60
BAN_SECONDS = 15 * 60
LOGIN_CSRF_TTL_SECONDS = 10 * 60
SESSION_COOKIE = "podcast_session"
SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
SESSIONS: dict[str, dict[str, float | str]] = {}
CSRF_TOKENS: dict[str, dict[str, float | str]] = {}  # session_id -> token metadata
_LOGIN_STATE_LOCK = threading.Lock()
_SESSION_STATE_LOCK = threading.Lock()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# In Docker, PODCAST_DATA_DIR=/data (set in docker-compose.yml). Locally, falls back to PROJECT_ROOT.
DATA_DIR = Path(os.environ.get("PODCAST_DATA_DIR", str(PROJECT_ROOT)))
try:
    CONFIG = load_config(DATA_DIR / "config.ini", DATA_DIR)
except ConfigError as exc:
    raise SystemExit(f"[api] Startup error: {exc}") from exc
SESSION_STATE_FILE = DATA_DIR / ".ui_sessions.json"
COOKIE_FILE_PERMISSION_MODE = 0o600
NETSCAPE_COOKIE_HEADER = "# Netscape HTTP Cookie File"


def _get_urls_file() -> Path:
    return CONFIG.urls_file


def _configured_cookie_file() -> Path:
    """Return the writable cookie path used by yt-dlp.

    ``load_config`` only records ``cookies_file`` when the file exists at app
    startup. The browser upload is allowed to create the first runtime cookie
    file, so it falls back to the standard data-directory location.
    """
    if CONFIG.cookies_file is not None:
        return CONFIG.cookies_file
    return DATA_DIR / "cookies.txt"


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
    """Overwrite the configured cookie file and make it readable only by owner."""
    cookie_file.parent.mkdir(parents=True, exist_ok=True)
    cookie_file.write_text(normalized_cookie_text, encoding="utf-8", newline="\n")
    cookie_file.chmod(COOKIE_FILE_PERMISSION_MODE)


def _password_file() -> Path:
    return DATA_DIR / ".ui_password"


def _auth_store() -> AuthStore:
    """Build the authentication store from current configured state paths."""
    return AuthStore(
        session_file=SESSION_STATE_FILE,
        login_state_file=DATA_DIR / ".login_state.json",
    )


def _load_login_state() -> dict:
    """Load client failure records through the locked authentication store."""
    return _auth_store().load_login_state()


def _save_login_state(state: dict) -> None:
    """Atomically replace client failure records."""
    _auth_store().save_login_state(state)


def _load_and_save_login_state(update_fn: "Callable[[dict], None]") -> dict:
    return _auth_store().update_login_state(update_fn)


def _security_headers(script_nonce: str | None = None) -> dict[str, str]:
    return security_headers(script_nonce)


def _cleanup_expired_sessions() -> None:
    """Drop expired sessions and their CSRF tokens from memory and disk."""
    with _SESSION_STATE_LOCK:
        expired = [
            sid
            for sid, s in SESSIONS.items()
            if _session_has_expired(s.get("created_at"))
        ]
        if not expired:
            return

        for sid in expired:
            SESSIONS.pop(sid, None)
            CSRF_TOKENS.pop(sid, None)
        _save_session_state(SESSIONS)


def _cleanup_expired_login_csrf_tokens() -> None:
    """Remove stale login CSRF tokens so the in-memory store stays small."""
    _cleanup_expired_sessions()
    cutoff = time.time() - LOGIN_CSRF_TTL_SECONDS
    expired_session_ids = [
        session_id
        for session_id, token_data in CSRF_TOKENS.items()
        if str(token_data.get("kind", "")) == "login"
        and float(token_data.get("created_at", 0)) < cutoff
    ]
    for session_id in expired_session_ids:
        CSRF_TOKENS.pop(session_id, None)


def _store_login_csrf_token() -> tuple[str, str]:
    """Create and store a one-time login CSRF token."""
    _cleanup_expired_login_csrf_tokens()
    csrf_session_id = secrets.token_urlsafe(16)
    csrf_token = secrets.token_urlsafe(32)
    CSRF_TOKENS[csrf_session_id] = {
        "token": csrf_token,
        "kind": "login",
        "created_at": time.time(),
    }
    return csrf_session_id, csrf_token


def _password_is_configured(password_text: str) -> bool:
    """Reject blank passwords and the legacy placeholder value."""
    normalized_password = password_text.strip()
    return (
        bool(normalized_password) and normalized_password != LEGACY_PASSWORD_PLACEHOLDER
    )


def _client_ip(request: Request) -> str:
    return client_ip(request, CONFIG.trust_x_forwarded_for)


def _request_is_secure(request: Request) -> bool:
    return request_is_secure(request, CONFIG.trust_x_forwarded_for)


def _invalidate_session(session_id: str | None) -> None:
    """Remove a session and its CSRF token."""
    if session_id:
        with _SESSION_STATE_LOCK:
            SESSIONS.pop(session_id, None)
            CSRF_TOKENS.pop(session_id, None)
            _save_session_state(SESSIONS)


def _session_has_expired(created_at_raw: float | str | None) -> bool:
    """Return ``True`` when a session is older than the configured lifetime."""
    try:
        created_at = float(created_at_raw or 0)
    except (TypeError, ValueError):
        return True
    return time.time() - created_at > SESSION_MAX_AGE_SECONDS


def _load_session_state() -> dict[str, dict[str, float | str]]:
    return _auth_store().load_sessions(SESSION_MAX_AGE_SECONDS)


def _save_session_state(state: dict[str, dict[str, float | str]]) -> None:
    _auth_store().save_sessions(state)
    return


SESSIONS = _load_session_state()


def _require_login(request: Request) -> RedirectResponse | None:
    """Validate the current session and redirect to login when it is invalid."""
    session_id = request.cookies.get(SESSION_COOKIE)
    session = SESSIONS.get(session_id)
    if not session:
        return RedirectResponse(url="/login", status_code=302)

    if _session_has_expired(session.get("created_at")):
        _invalidate_session(session_id)
        return RedirectResponse(url="/login", status_code=302)

    return None


def _has_valid_session(request: Request) -> bool:
    """Return whether the request already carries an active remembered session.

    Public entry pages such as ``/`` and ``/login`` use this check to send an
    already-authenticated browser straight to ``/ui``.
    """
    return _require_login(request) is None


def _get_csrf_token(session_id: str) -> str:
    """Return the CSRF token for a session, creating one if needed."""
    token_data = CSRF_TOKENS.get(session_id)
    token = str(token_data.get("token", "")) if token_data else ""
    if not token:
        token = secrets.token_urlsafe(32)
        CSRF_TOKENS[session_id] = {
            "token": token,
            "kind": "session",
            "created_at": time.time(),
        }
    return token


def _verify_csrf_token(request: Request, csrf_token: str) -> bool:
    """Check that the submitted CSRF token matches the stored session token."""
    session_id = request.cookies.get(SESSION_COOKIE)
    token_data = CSRF_TOKENS.get(session_id, {})
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


def _is_banned(state: dict, ip: str) -> tuple[bool, float]:
    """Return whether an IP is banned and when that ban ends."""
    record = state.get(ip, {})
    banned_until = float(record.get("banned_until", 0))
    return time.time() < banned_until, banned_until


def _record_failure(state: dict, ip: str) -> tuple[int, float]:
    """Update the failure counters for one IP address."""
    now = time.time()
    record = state.get(ip, {})
    last_failed = float(record.get("last_failed", 0))
    failed = int(record.get("failed", 0))

    if now - last_failed > FAIL_WINDOW_SECONDS:
        failed = 0

    failed += 1
    record.update({"failed": failed, "last_failed": now})

    if failed >= MAX_FAILED_ATTEMPTS:
        record["banned_until"] = now + BAN_SECONDS

    state[ip] = record
    return failed, float(record.get("banned_until", 0))


def _clear_failures(state: dict, ip: str) -> None:
    """Reset the failure counters for one IP address."""
    record = state.get(ip)
    if record:
        record.update({"failed": 0, "last_failed": 0, "banned_until": 0})
        state[ip] = record


@router.get("/")
def root(request: Request) -> RedirectResponse:
    """Route returning browsers to either the queue UI or the login form."""
    if _has_valid_session(request):
        return RedirectResponse(url="/ui", status_code=302)
    return RedirectResponse(url="/login", status_code=302)


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


@router.get("/help", response_class=HTMLResponse)
def help_page() -> HTMLResponse:
    """Return the public usage guide rendered by the template module."""
    return render_help_page(_security_headers)


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request) -> Response:
    """Render the login form and show any login error state."""
    if _has_valid_session(request):
        return RedirectResponse(url="/ui", status_code=302)

    raw_message = request.query_params.get("msg", "")
    message_map = {
        "csrf": ("msg-err", "Your login form expired. Try again."),
        "banned": ("msg-err", "Too many failed attempts. Try again later."),
        "bad_password": ("msg-err", "Invalid password."),
        "unconfigured": ("msg-err", "Password not configured."),
        "request": ("msg-err", "Invalid request."),
    }
    message_class, message_text = message_map.get(raw_message, ("", ""))
    safe_message_text = html.escape(message_text)

    ip = _client_ip(request)
    with _LOGIN_STATE_LOCK:
        state = _load_login_state()
        banned, banned_until = _is_banned(state, ip)
    if banned:
        remaining = int(banned_until - time.time())
        message_class = "msg-err"
        safe_message_text = html.escape(
            f"Too many failed attempts. Try again in {remaining} seconds."
        )

    csrf_session_id, csrf_token = _store_login_csrf_token()
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
    password: str = Form(...),
    csrf_token: str = Form(...),
    csrf_session: str = Form(...),
) -> RedirectResponse:
    # Validate the CSRF token before reading password state or updating bans.
    token_data = CSRF_TOKENS.pop(csrf_session, {})
    expected_csrf = str(token_data.get("token", ""))
    issued_at = float(token_data.get("created_at", 0) or 0)
    token_age_seconds = time.time() - issued_at
    if (
        not expected_csrf
        or token_age_seconds > LOGIN_CSRF_TTL_SECONDS
        or not secrets.compare_digest(csrf_token, expected_csrf)
    ):
        return RedirectResponse(url="/login?msg=csrf", status_code=303)

    ip = _client_ip(request)

    # Fail fast if the IP is already banned.
    with _LOGIN_STATE_LOCK:
        state = _load_login_state()
        banned, banned_until = _is_banned(state, ip)
    if banned:
        return RedirectResponse(url="/login?msg=banned", status_code=303)

    # Keep obviously bogus password submissions from reaching the file read.
    if len(password) > 1000:
        return RedirectResponse(url="/login?msg=request", status_code=303)

    password_file = _password_file()
    if not password_file.exists():
        return RedirectResponse(url="/login?msg=unconfigured", status_code=303)

    expected_password = password_file.read_text(encoding="utf-8").strip()
    if not _password_is_configured(expected_password):
        return RedirectResponse(url="/login?msg=unconfigured", status_code=303)

    # PBKDF2 is slow enough to justify keeping it outside the file lock.
    password_ok = verify_password(password, expected_password)

    if not password_ok:
        with _LOGIN_STATE_LOCK:
            state = _load_login_state()
            _failed_count, banned_until = _record_failure(state, ip)
            _save_login_state(state)
        if banned_until and time.time() < banned_until:
            return RedirectResponse(url="/login?msg=banned", status_code=303)
        return RedirectResponse(url="/login?msg=bad_password", status_code=303)

    _load_and_save_login_state(lambda state: _clear_failures(state, ip))

    session_id = secrets.token_urlsafe(32)
    with _SESSION_STATE_LOCK:
        SESSIONS[session_id] = {"created_at": time.time()}
        _save_session_state(SESSIONS)
    response = RedirectResponse(url="/ui", status_code=302)
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
    _invalidate_session(session_id)
    response = RedirectResponse(url="/login", status_code=302)
    _delete_session_cookie(response)
    return response


_MSG_DISPLAY: dict[str, tuple[str, str]] = {
    "added": ("msg-ok", "URL added to queue."),
    "removed": ("msg-ok", "URL removed from queue."),
    "duplicate": ("msg-warn", "This URL is already in the queue."),
    "downloaded": ("msg-warn", "This URL has already been downloaded."),
    "notfound": ("msg-warn", "That URL is no longer in the queue."),
    "invalid": ("msg-err", "Invalid URL - enter an http(s) media URL."),
    "error": ("msg-err", "Could not add URL."),
    "cookies_updated": ("msg-ok", "Cookie file updated."),
    "cookies_invalid": (
        "msg-err",
        "Invalid cookies.txt - upload a Netscape-format file.",
    ),
    "cookies_error": ("msg-err", "Could not update cookies.txt."),
}


@router.get("/ui", response_class=HTMLResponse)
def ui(request: Request, msg: str = "") -> HTMLResponse:
    """HTML form for submitting a URL plus monitored URLs and activity viewer."""
    redirect = _require_login(request)
    if redirect:
        return redirect

    session_id = request.cookies.get(SESSION_COOKIE, "")
    csrf_token = _get_csrf_token(session_id)
    safe_token = html.escape(csrf_token)
    script_nonce = secrets.token_urlsafe(16)

    # Only render the message keys this page knows about.
    msg_html = ""
    if msg in _MSG_DISPLAY:
        css_class, display_text = _MSG_DISPLAY[msg]
        msg_html = f'<div class="{css_class}">{html.escape(display_text)}</div>'

    bypass_row_html = ""
    if CONFIG.min_channel_video_age_hours > 0:
        bypass_label = html.escape("Download now (skip age wait or full playlist)")
    else:
        bypass_label = html.escape("Download now (full playlist)")
    bypass_row_html = f"""
        <div class="bypass-row">
          <label>
            <input type="checkbox" name="skip_age_check" value="1" />
            {bypass_label}
          </label>
        </div>
        """

    queue_urls = QueueStore(_get_urls_file(), _logger).load_normalized_urls()
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
        queue_html = '<p class="empty">No monitored URLs in urls.txt.</p>'

    count = len(safe_queue_urls)
    last_activity = html.escape(
        _last_activity_label(activity_log_file_for(CONFIG.log_file))
    )

    return render_queue_page(
        bypass_row_html=bypass_row_html,
        count=count,
        last_activity=last_activity,
        msg_html=msg_html,
        queue_html=queue_html,
        safe_token=safe_token,
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

    raw_cookie_file = await cookie_file.read()
    normalized_cookie_text = _normalize_uploaded_cookie_text(raw_cookie_file)
    if normalized_cookie_text is None:
        return RedirectResponse(url="/ui?msg=cookies_invalid", status_code=303)

    try:
        _write_cookie_file(_configured_cookie_file(), normalized_cookie_text)
    except OSError:
        _logger.exception("Could not update cookies file")
        return RedirectResponse(url="/ui?msg=cookies_error", status_code=303)

    return RedirectResponse(url="/ui?msg=cookies_updated", status_code=303)


_LOG_SOURCES = frozenset({"activity", "download"})


@router.get("/logs")
def view_logs(request: Request, source: str = "activity") -> Response:
    """Return a tail of ``activity.log`` or ``download.log`` as plain text."""
    redirect = _require_login(request)
    if redirect:
        return redirect

    log_source = source if source in _LOG_SOURCES else "activity"
    error_message = (
        "Could not read download log."
        if log_source == "download"
        else "Could not read activity log."
    )

    try:
        if log_source == "download":
            tail = ActivityLogStore(CONFIG.log_file).read_tail(
                empty_message=NO_DOWNLOAD_LOG_MESSAGE
            )
        else:
            activity_log_file = activity_log_file_for(CONFIG.log_file)
            tail = ActivityLogStore(activity_log_file).read_tail()
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
    """Add a URL to the queue, then wake the scheduler."""
    redirect = _require_login(request)
    if redirect:
        return redirect

    if not _verify_csrf_token(request, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    # Reject malformed or non-web URLs before touching the queue.
    if not is_supported_media_url(url):
        return RedirectResponse(url="/ui?msg=invalid", status_code=303)

    normalized = normalize_youtube_url(url)

    # Avoid re-queuing anything already archived as downloaded.
    downloaded = ArchiveStore(CONFIG.downloaded_urls_file, _logger).load()
    if normalized in downloaded:
        return RedirectResponse(url="/ui?msg=downloaded", status_code=303)

    urls_file = _get_urls_file()
    added = QueueStore(urls_file, _logger).append_urls([normalized])

    if not added:
        return RedirectResponse(url="/ui?msg=duplicate", status_code=303)

    # Direct-video additions wake the scheduler with the exact new URL, so an
    # immediate UI run cannot expand channels or process older urls.txt entries.
    # Checked playlist additions wake a full-playlist immediate run. Channel URLs
    # ignore the checkbox and stay queued for the scheduled channel_count run.
    skip_age_check_value = skip_age_check if isinstance(skip_age_check, str) else ""
    is_direct_video = not is_channel_or_playlist(normalized)
    if skip_age_check_value and is_youtube_playlist(normalized):
        queue_full_playlist_download(normalized)
    elif is_direct_video:
        # The bypass file only affects YouTube's minimum-age policy. Non-YouTube
        # direct videos are immediate already, so writing them there is noise.
        if skip_age_check_value and is_youtube_url(normalized):
            BypassStore(CONFIG.bypass_age_check_file, _logger).add(normalized)
        queue_single_url_download(normalized)

    return RedirectResponse(url="/ui?msg=added", status_code=303)


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
        return RedirectResponse(url="/ui?msg=invalid", status_code=303)

    removed = QueueStore(_get_urls_file(), _logger).remove_url(url)
    if not removed:
        return RedirectResponse(url="/ui?msg=notfound", status_code=303)

    return RedirectResponse(url="/ui?msg=removed", status_code=303)
