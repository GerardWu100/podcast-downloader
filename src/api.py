"""FastAPI app for login, queue edits, and log viewing."""

from __future__ import annotations

import html
import json
import logging
import os
import secrets
import threading
import time
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from .activity_log import (
    activity_log_file_for,
    read_activity_log_tail,
    read_download_log_tail,
)
from .config import ConfigError, load_config
from .passwords import LEGACY_PASSWORD_PLACEHOLDER, verify_password
from .trigger import (
    pop_full_playlist_download_requests,
    pop_single_url_download_requests,
    queue_full_playlist_download,
    queue_single_url_download,
)
from .url_utils import (
    add_to_bypass_age_file,
    append_urls,
    is_channel_or_playlist,
    is_supported_media_url,
    is_youtube_playlist,
    is_youtube_url,
    load_queue_urls,
    load_downloaded_url_archive,
    normalize_youtube_url,
    remove_url_from_queue,
)

_logger = logging.getLogger("api")

# Tests and older callers reset pending trigger state through this module.
__all__ = [
    "app",
    "pop_full_playlist_download_requests",
    "pop_single_url_download_requests",
]

app = FastAPI(
    title="Podcast URL Ingest", docs_url=None, redoc_url=None, openapi_url=None
)

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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
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


def _load_login_state() -> dict:
    state_path = DATA_DIR / ".login_state.json"
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_login_state(state: dict) -> None:
    state_path = DATA_DIR / ".login_state.json"
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _load_and_save_login_state(update_fn: "Callable[[dict], None]") -> dict:
    """Load login state, apply an update, then save it back under one lock."""
    with _LOGIN_STATE_LOCK:
        state = _load_login_state()
        update_fn(state)
        _save_login_state(state)
        return state


def _security_headers(script_nonce: str | None = None) -> dict[str, str]:
    """Return defensive headers for browser-facing responses."""
    csp_parts = [
        "default-src 'none'",
        "style-src 'unsafe-inline'",
        "img-src 'self' data:",
        "connect-src 'self'",
        "form-action 'self'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
    ]
    if script_nonce:
        csp_parts.append(f"script-src 'nonce-{script_nonce}'")

    return {
        "Cache-Control": "no-store",
        "Pragma": "no-cache",
        "Referrer-Policy": "same-origin",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Content-Security-Policy": "; ".join(csp_parts),
    }


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
    headers = getattr(request, "headers", {})
    if CONFIG.trust_x_forwarded_for:
        # Cloudflare Tunnel sets CF-Connecting-IP to the real client address.
        cf_ip = headers.get("CF-Connecting-IP")
        if cf_ip:
            return cf_ip.strip()
        # Other reverse proxies usually place the client IP in X-Forwarded-For.
        forwarded = headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
    client = getattr(request, "client", None)
    if client and getattr(client, "host", None):
        return client.host
    return "unknown"


def _request_is_secure(request: Request) -> bool:
    """Best-effort detection for HTTPS when sitting behind Cloudflare or a proxy."""
    if request.url.scheme == "https":
        return True
    if not CONFIG.trust_x_forwarded_for:
        return False

    headers = getattr(request, "headers", {})
    forwarded_proto = headers.get("X-Forwarded-Proto", "").split(",")[0].strip().lower()
    if forwarded_proto == "https":
        return True

    cf_visitor = headers.get("CF-Visitor", "")
    if cf_visitor:
        try:
            visitor_data = json.loads(cf_visitor)
        except json.JSONDecodeError:
            return False
        if isinstance(visitor_data, dict):
            return str(visitor_data.get("scheme", "")).lower() == "https"
    return False


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
    """Load remembered login sessions from disk."""
    if not SESSION_STATE_FILE.exists():
        return {}
    try:
        raw_state = json.loads(SESSION_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw_state, dict):
        return {}

    now = time.time()
    loaded: dict[str, dict[str, float | str]] = {}
    for session_id, session in raw_state.items():
        if not isinstance(session_id, str) or not isinstance(session, dict):
            continue
        try:
            created_at = float(session.get("created_at", 0))
        except (TypeError, ValueError):
            continue
        if now - created_at > SESSION_MAX_AGE_SECONDS:
            continue
        loaded[session_id] = {"created_at": created_at}
    return loaded


def _save_session_state(state: dict[str, dict[str, float | str]]) -> None:
    """Persist remembered login sessions to disk."""
    SESSION_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


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


@app.get("/")
def root(request: Request) -> RedirectResponse:
    """Route returning browsers to either the queue UI or the login form."""
    if _has_valid_session(request):
        return RedirectResponse(url="/ui", status_code=302)
    return RedirectResponse(url="/login", status_code=302)


_BASE_STYLES = """
  :root {
    color-scheme:light dark;
    --bg:#f0f2f5; --surface:#fff; --input-bg:#f8f9fa; --input-focus:#fff;
    --border:#e1e4e8; --text:#1c1e21; --muted:#6b7280;
    --accent:#2563eb; --accent-hov:#1d4ed8; --accent-soft:#eff6ff;
    --accent-border:#bfdbfe; --ok-bg:#f0fdf4; --ok-text:#166534;
    --ok-border:#bbf7d0; --warn-bg:#fffbeb; --warn-text:#92400e;
    --warn-border:#fde68a; --danger:#b91c1c; --danger-hov:#991b1b;
    --danger-bg:#fef2f2; --danger-border:#fecaca;
    --log-bg:#1a2332; --log-border:#2d3a4d; --log-hover:rgba(255,255,255,.04);
    --log-text:#dbe4f0; --log-time:#8b9cb3; --log-ok:#4ade80; --log-warn:#fbbf24;
    --log-err:#f87171; --log-info:#7dd3fc; --log-dim:#8b9cb3; --log-neutral:#cbd5e1;
    --log-ok-soft:rgba(74,222,128,.14); --log-warn-soft:rgba(251,191,36,.14);
    --log-err-soft:rgba(248,113,113,.14); --log-info-soft:rgba(125,211,252,.14);
    --log-dim-soft:rgba(139,156,179,.12); --scrollbar:#3d4f66;
    --shadow:0 1px 3px rgba(0,0,0,.08),0 1px 2px rgba(0,0,0,.06); --r:10px;
  }
  body.theme-dark {
    color-scheme:dark;
    --bg:#101418; --surface:#171d23; --input-bg:#111820; --input-focus:#0f1720;
    --border:#2a3440; --text:#e5edf5; --muted:#9aa8b6;
    --accent:#60a5fa; --accent-hov:#3b82f6; --accent-soft:#12263d;
    --accent-border:#255783; --ok-bg:#0f2f1d; --ok-text:#86efac;
    --ok-border:#166534; --warn-bg:#30230d; --warn-text:#facc15;
    --warn-border:#854d0e; --danger:#fca5a5; --danger-hov:#fecaca;
    --danger-bg:#2a1215; --danger-border:#7f1d1d;
    --log-bg:#0a0e14; --log-border:#1e293b; --log-hover:rgba(255,255,255,.035);
    --log-text:#e2e8f0; --log-time:#94a3b8; --log-ok:#34d399; --log-warn:#fcd34d;
    --log-err:#fb7185; --log-info:#93c5fd; --log-dim:#64748b; --log-neutral:#cbd5e1;
    --log-ok-soft:rgba(52,211,153,.16); --log-warn-soft:rgba(252,211,77,.16);
    --log-err-soft:rgba(251,113,133,.16); --log-info-soft:rgba(147,197,253,.16);
    --log-dim-soft:rgba(100,116,139,.18); --scrollbar:#334155;
    --shadow:0 1px 2px rgba(0,0,0,.35),0 10px 24px rgba(0,0,0,.24);
  }
  @media (prefers-color-scheme:dark) {
    body:not(.theme-light) {
      color-scheme:dark;
      --bg:#101418; --surface:#171d23; --input-bg:#111820; --input-focus:#0f1720;
      --border:#2a3440; --text:#e5edf5; --muted:#9aa8b6;
      --accent:#60a5fa; --accent-hov:#3b82f6; --accent-soft:#12263d;
      --accent-border:#255783; --ok-bg:#0f2f1d; --ok-text:#86efac;
      --ok-border:#166534; --warn-bg:#30230d; --warn-text:#facc15;
      --warn-border:#854d0e; --danger:#fca5a5; --danger-hov:#fecaca;
      --danger-bg:#2a1215; --danger-border:#7f1d1d;
      --log-bg:#0a0e14; --log-border:#1e293b; --log-hover:rgba(255,255,255,.035);
      --log-text:#e2e8f0; --log-time:#94a3b8; --log-ok:#34d399; --log-warn:#fcd34d;
      --log-err:#fb7185; --log-info:#93c5fd; --log-dim:#64748b; --log-neutral:#cbd5e1;
      --log-ok-soft:rgba(52,211,153,.16); --log-warn-soft:rgba(252,211,77,.16);
      --log-err-soft:rgba(251,113,133,.16); --log-info-soft:rgba(147,197,253,.16);
      --log-dim-soft:rgba(100,116,139,.18); --scrollbar:#334155;
      --shadow:0 1px 2px rgba(0,0,0,.35),0 10px 24px rgba(0,0,0,.24);
    }
  }
  *,*::before,*::after { box-sizing:border-box; margin:0; padding:0; }
  body {
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    background:var(--bg); color:var(--text); line-height:1.5; font-size:14px;
  }
  .card {
    background:var(--surface); border:1px solid var(--border);
    border-radius:var(--r); padding:22px 24px; box-shadow:var(--shadow);
  }
  .card-label {
    font-size:.7rem; font-weight:700; text-transform:uppercase;
    letter-spacing:.06em; color:var(--muted); margin-bottom:14px; display:block;
  }
  input[type="text"],input[type="password"] {
    width:100%; padding:9px 12px; font-size:.875rem; border:1px solid var(--border);
    border-radius:7px; outline:none; background:var(--input-bg); color:var(--text);
    transition:border-color .15s,box-shadow .15s,background .15s;
  }
  input[type="file"] {
    width:100%; padding:7px 10px; font-size:.82rem; border:1px solid var(--border);
    border-radius:7px; outline:none; background:var(--input-bg); color:var(--text);
  }
  input[type="text"]:focus,input[type="password"]:focus {
    border-color:var(--accent); background:var(--input-focus);
    box-shadow:0 0 0 3px rgba(37,99,235,.12);
  }
  input::placeholder { color:var(--muted); opacity:.72; }
  .btn {
    padding:9px 20px; font-size:.875rem; font-weight:600;
    background:var(--accent); color:#fff; border:none; border-radius:7px;
    cursor:pointer; transition:background .15s; white-space:nowrap;
  }
  .btn:hover { background:var(--accent-hov); }
  .msg-ok   { background:var(--ok-bg); color:var(--ok-text); border:1px solid var(--ok-border); }
  .msg-warn { background:var(--warn-bg); color:var(--warn-text); border:1px solid var(--warn-border); }
  .msg-err  { background:var(--danger-bg); color:var(--danger); border:1px solid var(--danger-border); }
  .msg-ok,.msg-warn,.msg-err {
    border-radius:7px; padding:9px 14px; font-size:.82rem; margin-bottom:12px;
  }
  .bypass-row { margin-top:10px; }
  .bypass-row label {
    display:flex; align-items:center; gap:6px; cursor:pointer;
    font-size:.78rem; color:var(--muted); font-weight:normal;
  }
"""


@app.get("/login", response_class=HTMLResponse)
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

    return HTMLResponse(
        content=f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" /><title>Podcast Downloader</title>
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <style>
    {_BASE_STYLES}
    body {{ display:flex; align-items:center; justify-content:center; min-height:100vh; padding:24px; }}
    .card {{ width:100%; max-width:360px; }}
    .theme-toggle {{
      position:fixed; top:16px; right:16px; padding:7px 10px; border:1px solid var(--border);
      border-radius:7px; background:var(--surface); color:var(--muted); cursor:pointer;
      font-size:.78rem; font-weight:600;
    }}
    .theme-toggle:hover {{ color:var(--text); border-color:var(--accent); }}
    h1 {{ font-size:1.1rem; font-weight:700; margin-bottom:4px; }}
    .sub {{ font-size:.82rem; color:var(--muted); margin-bottom:24px; }}
    label {{ display:block; font-size:.72rem; font-weight:700; text-transform:uppercase;
             letter-spacing:.05em; color:var(--muted); margin-bottom:6px; }}
    .btn {{ margin-top:14px; width:100%; padding:10px; }}
  </style>
</head>
<body>
  <button class="theme-toggle" id="theme-toggle" type="button">Dark</button>
  <div class="card">
    <h1>Podcast Downloader</h1>
    <p class="sub">Sign in to manage your queue.</p>
    {message_html}
    <form method="post" action="/login">
      <input type="hidden" name="csrf_token" value="{safe_token}" />
      <input type="hidden" name="csrf_session" value="{safe_csrf_session}" />
      <label for="password">Password</label>
      <input id="password" name="password" type="password"
        autocomplete="current-password" autocapitalize="none"
        spellcheck="false" required autofocus />
      <button type="submit" class="btn">Sign in</button>
    </form>
  </div>
  <script nonce="{script_nonce}">
    const savedTheme = localStorage.getItem('podcast-theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const themeButton = document.getElementById('theme-toggle');

    function applyTheme(theme) {{
      document.body.classList.toggle('theme-dark', theme === 'dark');
      document.body.classList.toggle('theme-light', theme === 'light');
      themeButton.textContent = theme === 'dark' ? 'Light' : 'Dark';
    }}

    applyTheme(savedTheme || (prefersDark ? 'dark' : 'light'));
    themeButton.addEventListener('click', () => {{
      const nextTheme = document.body.classList.contains('theme-dark') ? 'light' : 'dark';
      localStorage.setItem('podcast-theme', nextTheme);
      applyTheme(nextTheme);
    }});
  </script>
</body>
</html>""",
        headers=_security_headers(script_nonce=script_nonce),
    )


@app.post("/login")
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


@app.post("/logout")
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


@app.get("/ui", response_class=HTMLResponse)
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
        bypass_label = html.escape(
            "Download now (skip age wait or full playlist)"
        )
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

    queue_urls = load_queue_urls(_get_urls_file(), _logger)
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

    return HTMLResponse(
        content=f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Podcast Downloader</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    {_BASE_STYLES}
    body {{ padding:32px 16px; }}
    .page {{ max-width:700px; margin:0 auto; display:flex; flex-direction:column; gap:16px; }}
    header {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; }}
    .header-actions {{ display:flex; align-items:center; gap:8px; }}
    .brand h1 {{ font-size:1.1rem; font-weight:700; }}
    .brand p  {{ font-size:.78rem; color:var(--muted); }}
    .theme-toggle {{
      font-size:.78rem; color:var(--muted); background:var(--surface);
      padding:6px 12px; border:1px solid var(--border); border-radius:6px;
      cursor:pointer; transition:color .15s,border-color .15s;
    }}
    .theme-toggle:hover {{ color:var(--text); border-color:var(--accent); }}
    .logout-btn {{
      font-size:.78rem; color:var(--muted); background:var(--surface); text-decoration:none;
      padding:6px 12px; border:1px solid var(--border); border-radius:6px;
      cursor:pointer; transition:color .15s,border-color .15s;
    }}
    .logout-btn:hover {{ color:#dc2626; border-color:#dc2626; }}
    .card-row {{ display:flex; align-items:center; justify-content:space-between; margin-bottom:14px; }}
    .badge {{
      background:var(--accent-soft); color:var(--accent); border:1px solid var(--accent-border);
      font-size:.7rem; font-weight:700; padding:2px 8px; border-radius:999px;
    }}
    .input-row {{ display:flex; gap:8px; }}
    .input-row input {{ flex:1; }}
    .file-row {{ display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px; align-items:center; }}
    .q-list {{ list-style:none; }}
    .q-item {{ display:flex; align-items:flex-start; gap:9px; padding:8px 0; border-bottom:1px solid var(--border); }}
    .q-item:last-child {{ border-bottom:none; }}
    .q-dot {{ width:6px; height:6px; background:var(--accent); border-radius:50%; margin-top:5px; flex-shrink:0; opacity:.5; }}
    .q-url {{ flex:1; font-size:.8rem; color:var(--muted); word-break:break-all; }}
    .remove-form {{ flex-shrink:0; }}
    .btn-remove {{
      padding:5px 10px; font-size:.75rem; font-weight:600; background:var(--surface);
      color:var(--danger); border:1px solid var(--danger-border); border-radius:6px; cursor:pointer;
      transition:background .15s,border-color .15s,color .15s;
    }}
    .btn-remove:hover {{ background:var(--danger-bg); border-color:var(--danger-border); color:var(--danger-hov); }}
    .empty {{ font-size:.85rem; color:var(--muted); font-style:italic; }}
    .log-bar {{ display:flex; align-items:center; justify-content:space-between; margin-bottom:12px; gap:12px; flex-wrap:wrap; }}
    .log-controls {{ display:flex; align-items:center; gap:10px; font-size:.78rem; color:var(--muted); }}
    .log-controls label {{ display:flex; align-items:center; gap:4px; cursor:pointer; font-weight:normal; }}
    #log-ts {{
      font-variant-numeric:tabular-nums; font-size:.72rem; color:var(--muted);
      background:var(--input-bg); border:1px solid var(--border); border-radius:999px;
      padding:2px 10px;
    }}
    .log-source {{
      font-size:.75rem; font-weight:600; color:var(--text); background:var(--input-bg);
      border:1px solid var(--border); border-radius:999px; padding:5px 12px; cursor:pointer;
      transition:border-color .15s,box-shadow .15s;
    }}
    .log-source:focus {{ outline:none; border-color:var(--accent); box-shadow:0 0 0 3px rgba(37,99,235,.12); }}
    .btn-ghost {{
      padding:5px 12px; font-size:.75rem; font-weight:600; background:transparent;
      color:var(--accent); border:1px solid var(--accent-border); border-radius:999px;
      cursor:pointer; transition:all .15s;
    }}
    .btn-ghost:hover {{ background:var(--accent-soft); }}
    #log-box {{
      background:var(--log-bg); color:var(--log-text); border:1px solid var(--log-border);
      font-family:"SF Mono","Fira Code","Consolas",monospace;
      font-size:.74rem; line-height:1.45; border-radius:10px; padding:6px 0;
      height:340px; overflow-y:auto; word-break:break-word;
      box-shadow:inset 0 1px 0 rgba(255,255,255,.04);
    }}
    #log-box::-webkit-scrollbar {{ width:6px; }}
    #log-box::-webkit-scrollbar-thumb {{ background:var(--scrollbar); border-radius:999px; }}
    .log-empty {{
      display:flex; align-items:center; justify-content:center; min-height:280px;
      padding:24px; color:var(--log-dim); font-style:italic; text-align:center;
    }}
    .log-line {{
      display:flex; align-items:flex-start; gap:10px; padding:7px 14px;
      border-left:3px solid transparent; transition:background .12s;
    }}
    .log-line + .log-line {{ border-top:1px solid rgba(255,255,255,.04); }}
    .log-line:hover {{ background:var(--log-hover); }}
    .log-line--ok {{ border-left-color:var(--log-ok); }}
    .log-line--warn {{ border-left-color:var(--log-warn); }}
    .log-line--err {{ border-left-color:var(--log-err); }}
    .log-line--info {{ border-left-color:var(--log-info); }}
    .log-line--dim {{ border-left-color:var(--log-dim); }}
    .log-line--neutral {{ border-left-color:rgba(255,255,255,.12); }}
    .log-time {{
      flex-shrink:0; min-width:64px; font-size:.68rem; color:var(--log-time);
      font-variant-numeric:tabular-nums; padding-top:1px;
    }}
    .log-badge,.log-level {{
      flex-shrink:0; min-width:42px; text-align:center;
      font-size:.58rem; font-weight:700; letter-spacing:.05em; text-transform:uppercase;
      padding:2px 6px; border-radius:999px; margin-top:1px;
    }}
    .log-badge--ok,.log-level--ok {{ color:var(--log-ok); background:var(--log-ok-soft); }}
    .log-badge--warn,.log-level--warn {{ color:var(--log-warn); background:var(--log-warn-soft); }}
    .log-badge--err,.log-level--err {{ color:var(--log-err); background:var(--log-err-soft); }}
    .log-badge--info,.log-level--info {{ color:var(--log-info); background:var(--log-info-soft); }}
    .log-badge--dim,.log-level--dim {{ color:var(--log-dim); background:var(--log-dim-soft); }}
    .log-badge--neutral,.log-level--neutral {{ color:var(--log-neutral); background:var(--log-dim-soft); }}
    .log-msg {{ flex:1; color:var(--log-text); white-space:pre-wrap; }}
    .log-line--ok .log-msg {{ color:var(--log-ok); }}
    .log-line--warn .log-msg {{ color:var(--log-warn); }}
    .log-line--err .log-msg {{ color:var(--log-err); }}
    .log-line--info .log-msg {{ color:var(--log-info); }}
    .log-line--dim .log-msg {{ color:var(--log-dim); }}
  </style>
</head>
<body>
  <div class="page">
    <header>
      <div class="brand">
        <h1>Podcast Downloader</h1>
        <p>YouTube to MP3</p>
      </div>
      <div class="header-actions">
        <button class="theme-toggle" id="theme-toggle" type="button">Dark</button>
        <form method="post" action="/logout" style="margin:0">
          <input type="hidden" name="csrf_token" value="{safe_token}" />
          <button type="submit" class="logout-btn">Logout</button>
        </form>
      </div>
    </header>

    <div class="card">
      <span class="card-label">Add to queue</span>
      {msg_html}
      <form method="post" action="/add-url">
        <input type="hidden" name="csrf_token" value="{safe_token}" />
        <div class="input-row">
          <input id="url" name="url" type="text"
            placeholder="https://www.youtube.com/watch?v=...  or  /@channel"
            autocomplete="off" autocapitalize="none" spellcheck="false" required />
          <button type="submit" class="btn">Add</button>
        </div>
        {bypass_row_html}
      </form>
    </div>

    <div class="card">
      <div class="card-row">
        <span class="card-label" style="margin:0">Monitored URLs (<code>urls.txt</code>)</span>
        <span class="badge">{count}</span>
      </div>
      {queue_html}
    </div>

    <div class="card">
      <div class="log-bar">
        <div class="log-controls">
          <span class="card-label" style="margin:0">Logs</span>
          <select id="log-source" class="log-source" aria-label="Log source">
            <option value="activity" selected>Activity</option>
            <option value="download">Download log</option>
          </select>
        </div>
        <div class="log-controls">
          <span id="log-ts"></span>
          <label><input type="checkbox" id="auto-cb" checked> Auto</label>
          <button class="btn-ghost" id="refresh-logs" type="button">Refresh</button>
        </div>
      </div>
      <div id="log-box"><div class="log-empty">Loading logs…</div></div>
    </div>

    <div class="card">
      <span class="card-label">YouTube cookies</span>
      <form method="post" action="/upload-cookies" enctype="multipart/form-data">
        <input type="hidden" name="csrf_token" value="{safe_token}" />
        <div class="file-row">
          <input id="cookie-file" name="cookie_file" type="file"
            accept=".txt,text/plain" required />
          <button type="submit" class="btn">Upload</button>
        </div>
      </form>
    </div>
  </div>

  <script nonce="{script_nonce}">
    let timer = null;
    const savedTheme = localStorage.getItem('podcast-theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const themeButton = document.getElementById('theme-toggle');

    function applyTheme(theme) {{
      document.body.classList.toggle('theme-dark', theme === 'dark');
      document.body.classList.toggle('theme-light', theme === 'light');
      themeButton.textContent = theme === 'dark' ? 'Light' : 'Dark';
    }}

    applyTheme(savedTheme || (prefersDark ? 'dark' : 'light'));
    themeButton.addEventListener('click', () => {{
      const nextTheme = document.body.classList.contains('theme-dark') ? 'light' : 'dark';
      localStorage.setItem('podcast-theme', nextTheme);
      applyTheme(nextTheme);
    }});

    function esc(s) {{
      return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }}

    function classifyActivity(message) {{
      if (/^Downloaded:/i.test(message)) return 'ok';
      if (/^Failed:/i.test(message)) return 'err';
      if (/^Waiting for age gate:/i.test(message)) return 'warn';
      if (/^Skipped Short:/i.test(message)) return 'warn';
      if (/^Run finished:/i.test(message) || /^Playlist run finished:/i.test(message)) return 'info';
      if (/^Retention cleanup|^Deleted expired/i.test(message)) return 'dim';
      if (/^No activity yet\\./i.test(message)) return 'empty';
      return 'neutral';
    }}

    function classifyDownload(level, message) {{
      const upper = level.toUpperCase();
      if (upper === 'ERROR' || upper === 'CRITICAL') return 'err';
      if (upper === 'WARNING') return 'warn';
      if (upper === 'DEBUG') return 'dim';
      if (/failed|error|timed out/i.test(message)) return 'err';
      if (/waiting|skipped/i.test(message)) return 'warn';
      if (/downloaded|finished|success/i.test(message)) return 'ok';
      return 'info';
    }}

    function activityBadge(kind) {{
      const labels = {{ ok: 'Done', err: 'Fail', warn: 'Wait', info: 'Run', dim: 'Keep', neutral: 'Log' }};
      return labels[kind] || 'Log';
    }}

    function renderLogLine(kind, timeLabel, badge, message, fullTimestamp) {{
      const safeTime = esc(timeLabel);
      const safeBadge = esc(badge);
      const safeMessage = esc(message);
      const safeTitle = fullTimestamp ? ' title="' + esc(fullTimestamp) + '"' : '';
      return (
        '<div class="log-line log-line--' + kind + '"' + safeTitle + '>' +
          '<span class="log-time">' + safeTime + '</span>' +
          '<span class="log-badge log-badge--' + kind + '">' + safeBadge + '</span>' +
          '<span class="log-msg">' + safeMessage + '</span>' +
        '</div>'
      );
    }}

    function renderDownloadLine(kind, timeLabel, level, message, fullTimestamp) {{
      const safeTime = esc(timeLabel);
      const safeLevel = esc(level);
      const safeMessage = esc(message);
      const safeTitle = fullTimestamp ? ' title="' + esc(fullTimestamp) + '"' : '';
      return (
        '<div class="log-line log-line--' + kind + '"' + safeTitle + '>' +
          '<span class="log-time">' + safeTime + '</span>' +
          '<span class="log-level log-level--' + kind + '">' + safeLevel + '</span>' +
          '<span class="log-msg">' + safeMessage + '</span>' +
        '</div>'
      );
    }}

    function renderLogLines(raw, source) {{
      const lines = raw.split('\\n');
      if (!lines.length || (lines.length === 1 && !lines[0].trim())) {{
        return '<div class="log-empty">No entries yet.</div>';
      }}

      const rendered = lines.map(line => {{
        if (!line.trim()) return '';

        if (source === 'download') {{
          if (/^No log entries yet\\./i.test(line)) {{
            return '<div class="log-empty">' + esc(line) + '</div>';
          }}

          const downloadMatch = line.match(/^\\[([^\\]]+)\\]\\s+(DEBUG|INFO|WARNING|ERROR|CRITICAL):\\s*(.*)$/);
          if (downloadMatch) {{
            const timestamp = downloadMatch[1];
            const level = downloadMatch[2];
            const message = downloadMatch[3];
            const kind = classifyDownload(level, message);
            const timeLabel = timestamp.includes(' ') ? timestamp.split(' ')[1] : timestamp;
            return renderDownloadLine(kind, timeLabel, level, message, timestamp);
          }}
        }} else {{
          if (/^No activity yet\\./i.test(line)) {{
            return '<div class="log-empty">' + esc(line) + '</div>';
          }}

          const activityMatch = line.match(/^\\[([^\\]]+)\\]\\s*(.*)$/);
          if (activityMatch) {{
            const timestamp = activityMatch[1];
            const message = activityMatch[2];
            const kind = classifyActivity(message);
            const timeLabel = timestamp.includes(' ') ? timestamp.split(' ')[1] : timestamp;
            return renderLogLine(kind, timeLabel, activityBadge(kind), message, timestamp);
          }}
        }}

        const fallbackKind =
          /Failed|Error|Timed out/i.test(line) ? 'err' :
          /Waiting|Skipped/i.test(line) ? 'warn' :
          /Downloaded|finished/i.test(line) ? 'ok' :
          'neutral';
        return renderLogLine(fallbackKind, '—', activityBadge(fallbackKind), line, '');
      }}).filter(Boolean);

      return rendered.join('') || '<div class="log-empty">No entries yet.</div>';
    }}

    const logSourceSelect = document.getElementById('log-source');

    async function loadLogs() {{
      try {{
        const source = logSourceSelect.value;
        const r = await fetch('/logs?source=' + encodeURIComponent(source));
        if (!r.ok) return;
        const text = await r.text();
        const box = document.getElementById('log-box');
        const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
        box.innerHTML = renderLogLines(text, source);
        if (atBottom) box.scrollTop = box.scrollHeight;
        document.getElementById('log-ts').textContent = new Date().toLocaleTimeString();
      }} catch (_) {{}}
    }}

    function setAuto(on) {{
      clearInterval(timer);
      if (on) timer = setInterval(loadLogs, 15000);
    }}

    document.getElementById('auto-cb').addEventListener('change', e => setAuto(e.target.checked));
    document.getElementById('refresh-logs').addEventListener('click', loadLogs);
    logSourceSelect.addEventListener('change', loadLogs);
    loadLogs();
    setAuto(true);
  </script>
</body>
</html>
""",
        headers=_security_headers(script_nonce=script_nonce),
    )


@app.post("/upload-cookies")
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


@app.get("/logs")
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
            tail = read_download_log_tail(CONFIG.log_file)
        else:
            activity_log_file = activity_log_file_for(CONFIG.log_file)
            tail = read_activity_log_tail(activity_log_file)
        return Response(
            content=tail, media_type="text/plain", headers=_security_headers()
        )
    except Exception:
        return Response(
            content=error_message,
            media_type="text/plain",
            headers=_security_headers(),
        )


@app.post("/add-url")
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
    downloaded = load_downloaded_url_archive(CONFIG.downloaded_urls_file, _logger)
    if normalized in downloaded:
        return RedirectResponse(url="/ui?msg=downloaded", status_code=303)

    urls_file = _get_urls_file()
    added = append_urls(urls_file, [normalized])

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
            add_to_bypass_age_file(CONFIG.bypass_age_check_file, normalized, _logger)
        queue_single_url_download(normalized)

    return RedirectResponse(url="/ui?msg=added", status_code=303)


@app.post("/remove-url")
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

    removed = remove_url_from_queue(_get_urls_file(), url, _logger)
    if not removed:
        return RedirectResponse(url="/ui?msg=notfound", status_code=303)

    return RedirectResponse(url="/ui?msg=removed", status_code=303)
