"""Behavioral tests for API session and client IP handling."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import replace

import pytest
import src.config as config_module
from src.credentials import CREDENTIALS_FILENAME
from src.passwords import hash_password
from src.trigger import (
    pop_full_playlist_download_requests,
    pop_single_url_download_requests,
)
from src.web import routes as api_module


class _FakeClient:
    """Minimal request client object used by the tests."""

    def __init__(self, host: str) -> None:
        self.host = host


class _FakeRequest:
    """Minimal request object for internal helper tests."""

    def __init__(
        self,
        *,
        headers: dict[str, str] | None = None,
        client_host: str = "127.0.0.1",
        cookies: dict[str, str] | None = None,
        query_params: dict[str, str] | None = None,
    ) -> None:
        self.headers = headers or {}
        self.client = _FakeClient(client_host)
        self.cookies = cookies or {}
        self.query_params = query_params or {}


class _FakeUploadFile:
    """Small async upload double with the attributes the API reads."""

    def __init__(self, filename: str, content: bytes) -> None:
        self.filename = filename
        self._content = content
        # Largest number of bytes the route asked for, so a test can prove the
        # route never pulls a whole oversized upload into memory.
        self.largest_read_request = -1

    async def read(self, size: int = -1) -> bytes:
        """Return up to ``size`` bytes, like FastAPI's UploadFile.

        Parameters
        ----------
        size:
            Byte count to return. A negative value means the whole upload.
        """
        self.largest_read_request = max(self.largest_read_request, size)
        if size < 0:
            return self._content
        return self._content[:size]


def test_client_ip_ignores_forwarded_header_by_default(monkeypatch) -> None:
    """Direct deployments should not trust spoofable forwarded headers."""
    monkeypatch.setattr(
        api_module,
        "CONFIG",
        replace(api_module.CONFIG, trust_x_forwarded_for=False),
    )

    request = _FakeRequest(
        headers={"X-Forwarded-For": "198.51.100.10"},
        client_host="203.0.113.7",
    )

    assert api_module._client_ip(request) == "203.0.113.7"


def test_client_ip_uses_forwarded_header_when_enabled(monkeypatch) -> None:
    """Proxy deployments can opt in to forwarded-header trust explicitly."""
    monkeypatch.setattr(
        api_module,
        "CONFIG",
        replace(api_module.CONFIG, trust_x_forwarded_for=True),
    )

    request = _FakeRequest(
        headers={"X-Forwarded-For": "198.51.100.10, 203.0.113.7"},
        client_host="203.0.113.7",
    )

    assert api_module._client_ip(request) == "198.51.100.10"


def test_require_login_accepts_session_from_different_ip() -> None:
    """Remembered sessions should not depend on the login IP."""
    session_id = "test-unbound-session"
    api_module.SESSIONS[session_id] = {
        "created_at": time.time(),
    }

    request = _FakeRequest(
        client_host="127.0.0.2",
        cookies={api_module.SESSION_COOKIE: session_id},
    )

    result = api_module._require_login(request)

    assert result is None
    assert session_id in api_module.SESSIONS
    api_module.SESSIONS.pop(session_id, None)


def test_root_redirects_remembered_session_to_ui() -> None:
    """Reopening the app root with a valid session should skip the login form."""
    session_id = "test-root-remembered-session"
    api_module.SESSIONS[session_id] = {
        "created_at": time.time(),
    }

    request = _FakeRequest(
        cookies={api_module.SESSION_COOKIE: session_id},
    )

    response = api_module.root(request)

    assert response.headers["location"] == "/ui"
    api_module.SESSIONS.pop(session_id, None)


def test_login_page_redirects_remembered_session_to_ui() -> None:
    """Reopening /login with a valid session should not ask for the password again."""
    session_id = "test-login-remembered-session"
    api_module.SESSIONS[session_id] = {
        "created_at": time.time(),
    }

    request = _FakeRequest(
        cookies={api_module.SESSION_COOKIE: session_id},
    )

    response = api_module.login_form(request)

    assert response.headers["location"] == "/ui"
    api_module.SESSIONS.pop(session_id, None)


def test_help_page_explains_behavior_and_cookie_setup() -> None:
    """Public help should cover core controls and link to official cookie guidance."""
    response = api_module.help_page()
    body = response.body.decode("utf-8")

    assert response.status_code == 200
    assert "What it does" in body
    assert "Controls" in body
    assert "Adding YouTube access cookies" in body
    assert "github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies" in body
    assert "Content-Security-Policy" in response.headers


def test_ui_shows_reliable_status_summary(monkeypatch, tmp_path) -> None:
    """Queue UI should show service, queue count, and empty activity state."""
    session_id = "test-ui-status-session"
    queue_file = tmp_path / "urls.txt"
    queue_file.write_text(
        "https://www.youtube.com/@channel-one\nhttps://www.youtube.com/@channel-two\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        api_module,
        "CONFIG",
        replace(
            api_module.CONFIG,
            urls_file=queue_file,
            log_file=tmp_path / "download.log",
        ),
    )
    api_module.SESSIONS[session_id] = {"created_at": time.time()}
    request = _FakeRequest(
        cookies={api_module.SESSION_COOKIE: session_id},
    )

    response = api_module.ui(request)
    body = response.body.decode("utf-8")

    assert 'aria-label="System status"' in body
    assert (
        '<span class="status-value"><span class="status-dot"></span>Online</span>'
        in body
    )
    assert '<span class="status-value">2</span>' in body
    assert '<span class="status-value">No activity yet</span>' in body
    assert '<a class="nav-link" href="/help">Help</a>' in body

    api_module.SESSIONS.pop(session_id, None)
    api_module.CSRF_TOKENS.pop(session_id, None)


def test_load_session_state_round_trip_and_filtering(monkeypatch, tmp_path) -> None:
    """Persisted sessions should round-trip cleanly and skip invalid or expired entries."""
    from src.web import routes as api

    monkeypatch.setattr(api, "SESSION_STATE_FILE", tmp_path / ".ui_sessions.json")
    now = 10_000.0
    monkeypatch.setattr(api.time, "time", lambda: now)

    api._save_session_state(
        {
            "valid-session": {"created_at": now - 60},
            "expired-session": {"created_at": now - api.SESSION_MAX_AGE_SECONDS - 1},
            "bad-session": {"created_at": "not-a-number"},
        }
    )

    session_state = api._load_session_state()

    assert session_state == {"valid-session": {"created_at": now - 60}}


def test_secure_cookie_respects_cf_visitor(monkeypatch) -> None:
    """Cloudflare's CF-Visitor hint should also mark the session cookie Secure."""
    from types import SimpleNamespace

    from src.web import routes as api

    monkeypatch.setattr(api, "CONFIG", SimpleNamespace(trust_x_forwarded_for=True))

    class FakeURL:
        scheme = "http"

    class FakeRequest:
        url = FakeURL()
        headers = {"CF-Visitor": '{"scheme":"https"}'}

    assert api._request_is_secure(FakeRequest())

    response = api.RedirectResponse(url="/ui")
    api._set_session_cookie(response, FakeRequest(), "session-id")
    assert "Secure" in response.headers.get("set-cookie", "")


def test_login_redirects_to_unconfigured_when_credentials_missing(
    monkeypatch, tmp_path
) -> None:
    """A missing credentials file should send the browser to the unconfigured message."""
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    api_module.CSRF_TOKENS.clear()
    api_module.CSRF_TOKENS["csrf-session"] = {
        "token": "csrf-token",
        "kind": "login",
        "created_at": time.time(),
    }

    redirect = api_module.login_action(
        _FakeRequest(client_host="127.0.0.1"),
        username="alice",
        password="any-password",
        csrf_token="csrf-token",
        csrf_session="csrf-session",
    )

    assert redirect.headers["location"] == "/login?msg=unconfigured"


def test_login_page_shows_invalid_credentials_message(monkeypatch, tmp_path) -> None:
    """Failed login attempts should return the HTML login page with an inline error."""
    credentials_file = tmp_path / CREDENTIALS_FILENAME
    credentials_file.write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "username": "alice",
                        "password_hash": hash_password(
                            "correct-password", salt=b"0123456789abcdef"
                        ),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    api_module.CSRF_TOKENS.clear()
    api_module.CSRF_TOKENS["csrf-session"] = {
        "token": "csrf-token",
        "kind": "login",
        "created_at": time.time(),
    }

    request = _FakeRequest(client_host="127.0.0.1")
    redirect = api_module.login_action(
        request,
        username="alice",
        password="wrong-password",
        csrf_token="csrf-token",
        csrf_session="csrf-session",
    )

    assert redirect.headers["location"] == "/login?msg=bad_credentials"

    login_response = api_module.login_form(
        _FakeRequest(client_host="127.0.0.1", query_params={"msg": "bad_credentials"})
    )
    assert login_response.status_code == 200
    assert "Invalid username or password." in login_response.body.decode("utf-8")


def test_logs_endpoint_reads_concise_activity_log(monkeypatch, tmp_path) -> None:
    """The browser log endpoint should show activity.log, not the full download log."""
    from src.web import routes as api

    session_id = "test-activity-log-session"
    log_file = tmp_path / "download.log"
    activity_file = tmp_path / "activity.log"
    log_file.write_text("full diagnostic detail\n", encoding="utf-8")
    activity_file.write_text("concise activity\n", encoding="utf-8")
    api.SESSIONS[session_id] = {
        "created_at": time.time(),
    }
    monkeypatch.setattr(
        api,
        "CONFIG",
        replace(api.CONFIG, log_file=log_file),
    )

    request = _FakeRequest(cookies={api.SESSION_COOKIE: session_id})

    response = api.view_logs(request)

    assert response.body.decode("utf-8") == "concise activity"
    api.SESSIONS.pop(session_id, None)


def test_logs_endpoint_can_read_full_download_log(monkeypatch, tmp_path) -> None:
    """The browser log endpoint should optionally tail the full download log."""
    from src.web import routes as api

    session_id = "test-download-log-session"
    log_file = tmp_path / "download.log"
    activity_file = tmp_path / "activity.log"
    log_file.write_text("full diagnostic detail\n", encoding="utf-8")
    activity_file.write_text("concise activity\n", encoding="utf-8")
    api.SESSIONS[session_id] = {
        "created_at": time.time(),
    }
    monkeypatch.setattr(
        api,
        "CONFIG",
        replace(api.CONFIG, log_file=log_file),
    )

    request = _FakeRequest(cookies={api.SESSION_COOKIE: session_id})

    response = api.view_logs(request, source="download")

    assert response.body.decode("utf-8") == "full diagnostic detail"
    api.SESSIONS.pop(session_id, None)


def test_logs_endpoint_falls_back_to_activity_for_unknown_source(
    monkeypatch, tmp_path
) -> None:
    """Unknown log source values should keep serving the activity feed."""
    from src.web import routes as api

    session_id = "test-unknown-log-source-session"
    log_file = tmp_path / "download.log"
    activity_file = tmp_path / "activity.log"
    log_file.write_text("full diagnostic detail\n", encoding="utf-8")
    activity_file.write_text("concise activity\n", encoding="utf-8")
    api.SESSIONS[session_id] = {
        "created_at": time.time(),
    }
    monkeypatch.setattr(
        api,
        "CONFIG",
        replace(api.CONFIG, log_file=log_file),
    )

    request = _FakeRequest(cookies={api.SESSION_COOKIE: session_id})

    response = api.view_logs(request, source="unexpected")

    assert response.body.decode("utf-8") == "concise activity"
    api.SESSIONS.pop(session_id, None)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("channel_count", "not-an-int"),
        ("min_channel_video_age_hours", "still-not-an-int"),
        ("delay_seconds", "not-a-float"),
    ],
)
def test_load_config_rejects_invalid_numeric_values(
    tmp_path,
    key: str,
    value: str,
) -> None:
    """Bad numeric config values should raise instead of silently falling back."""
    config_file = tmp_path / "config.ini"
    config_file.write_text(f"[podcast]\n{key} = {value}\n", encoding="utf-8")

    with pytest.raises(ValueError, match=key):
        config_module.load_config(config_file, tmp_path)


def test_cleanup_expired_login_csrf_tokens_removes_only_stale_login_tokens(
    monkeypatch,
) -> None:
    """Anonymous login CSRF tokens should expire without affecting active session CSRF state."""
    now = 1_000.0
    monkeypatch.setattr(api_module.time, "time", lambda: now)
    api_module.CSRF_TOKENS.clear()
    api_module.CSRF_TOKENS["stale-login"] = {
        "token": "a",
        "kind": "login",
        "created_at": now - api_module.LOGIN_CSRF_TTL_SECONDS - 1,
    }
    api_module.CSRF_TOKENS["fresh-login"] = {
        "token": "b",
        "kind": "login",
        "created_at": now,
    }
    api_module.CSRF_TOKENS["session-token"] = {
        "token": "c",
        "kind": "session",
        "created_at": now - api_module.LOGIN_CSRF_TTL_SECONDS - 1,
    }

    api_module._cleanup_expired_login_csrf_tokens()

    assert "stale-login" not in api_module.CSRF_TOKENS
    assert "fresh-login" in api_module.CSRF_TOKENS
    assert "session-token" in api_module.CSRF_TOKENS


def test_security_headers_allow_nonced_ui_script() -> None:
    """The UI CSP must allow its own nonced inline script and same-origin log fetches."""
    headers = api_module._security_headers(script_nonce="nonce-123")
    csp = headers["Content-Security-Policy"]

    assert "script-src 'nonce-nonce-123'" in csp
    assert "connect-src 'self'" in csp
    assert "default-src 'none'" in csp


def test_ui_uses_nonce_based_script_instead_of_inline_handlers() -> None:
    """The UI page should match its CSP by using a nonced script and no onclick handlers."""
    session_id = "test-ui-session"
    api_module.SESSIONS[session_id] = {
        "ip": "127.0.0.1",
        "created_at": time.time(),
    }

    request = _FakeRequest(
        client_host="127.0.0.1",
        cookies={api_module.SESSION_COOKIE: session_id},
    )

    response = api_module.ui(request)
    body = response.body.decode("utf-8")

    assert 'script nonce="' in body
    assert "onclick=" not in body
    assert "script-src 'nonce-" in response.headers["Content-Security-Policy"]

    api_module.SESSIONS.pop(session_id, None)


def test_ui_bypass_label_uses_shorter_immediate_download_text(monkeypatch) -> None:
    """The checkbox label should explain immediate video and playlist behavior."""
    session_id = "test-ui-bypass-label"
    api_module.SESSIONS[session_id] = {
        "ip": "127.0.0.1",
        "created_at": time.time(),
    }
    monkeypatch.setattr(
        api_module,
        "CONFIG",
        replace(api_module.CONFIG, min_channel_video_age_hours=12),
    )

    request = _FakeRequest(
        client_host="127.0.0.1",
        cookies={api_module.SESSION_COOKIE: session_id},
    )

    response = api_module.ui(request)
    body = response.body.decode("utf-8")

    assert "Run now (skip the wait or download a full playlist)" in body
    assert "Download this video now" not in body

    api_module.SESSIONS.pop(session_id, None)


def test_ui_shows_playlist_checkbox_when_age_gate_disabled(monkeypatch) -> None:
    """The immediate-download control should stay visible for full-playlist adds."""
    session_id = "test-ui-no-bypass"
    api_module.SESSIONS[session_id] = {
        "ip": "127.0.0.1",
        "created_at": time.time(),
    }
    monkeypatch.setattr(
        api_module,
        "CONFIG",
        replace(api_module.CONFIG, min_channel_video_age_hours=0),
    )

    request = _FakeRequest(
        client_host="127.0.0.1",
        cookies={api_module.SESSION_COOKIE: session_id},
    )

    response = api_module.ui(request)
    body = response.body.decode("utf-8")

    assert "skip_age_check" in body
    assert "Run now (download a full playlist)" in body

    api_module.SESSIONS.pop(session_id, None)


def test_settings_page_includes_authenticated_cookie_upload_form() -> None:
    """The settings page should expose a CSRF-protected cookies.txt upload form."""
    session_id = "test-settings-cookie-upload-form"
    api_module.SESSIONS[session_id] = {
        "ip": "127.0.0.1",
        "created_at": time.time(),
    }

    request = _FakeRequest(
        client_host="127.0.0.1",
        cookies={api_module.SESSION_COOKIE: session_id},
    )

    response = api_module.settings(request)
    body = response.body.decode("utf-8")

    assert 'action="/upload-cookies"' in body
    assert 'enctype="multipart/form-data"' in body
    assert 'name="cookie_file"' in body
    assert 'name="csrf_token"' in body
    assert "YouTube access cookies" in body

    api_module.SESSIONS.pop(session_id, None)


def test_queue_page_links_to_settings_without_embedding_them() -> None:
    """Setup controls moved off the queue page, which now only links to them."""
    session_id = "test-queue-links-to-settings"
    api_module.SESSIONS[session_id] = {
        "ip": "127.0.0.1",
        "created_at": time.time(),
    }

    request = _FakeRequest(
        client_host="127.0.0.1",
        cookies={api_module.SESSION_COOKIE: session_id},
    )

    body = api_module.ui(request).body.decode("utf-8")

    assert 'href="/settings"' in body
    assert "YouTube access cookies" not in body
    assert 'action="/upload-cookies"' not in body
    assert 'action="/save-notifications"' not in body
    # The queue itself must still be there.
    assert 'action="/add-url"' in body

    api_module.SESSIONS.pop(session_id, None)


def test_settings_page_shows_saved_notification_values_and_examples() -> None:
    """Saved values reload into the form, and each field explains itself."""
    session_id = "test-settings-notification-values"
    api_module.SESSIONS[session_id] = {
        "ip": "127.0.0.1",
        "created_at": time.time(),
    }

    request = _FakeRequest(
        client_host="127.0.0.1",
        cookies={api_module.SESSION_COOKIE: session_id},
    )

    body = api_module.settings(request).body.decode("utf-8")

    assert 'action="/save-notifications"' in body
    assert 'id="notify-test"' in body
    assert ".nav-link {" in body
    assert "text-decoration:none" in body
    # A worked example for the field that is easiest to get wrong.
    assert "http://apprise-api:8000/notify/your-key" in body
    assert "/notify/" in body

    api_module.SESSIONS.pop(session_id, None)


def test_upload_cookies_overwrites_existing_cookie_file(
    tmp_path,
    monkeypatch,
) -> None:
    """Authenticated uploads should replace cookies.txt and set private permissions."""
    session_id = "test-upload-cookies"
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File\nold\n", encoding="utf-8")
    monkeypatch.setattr(
        api_module,
        "CONFIG",
        replace(api_module.CONFIG, cookies_file=cookie_file),
    )
    api_module.SESSIONS[session_id] = {
        "ip": "127.0.0.1",
        "created_at": time.time(),
    }
    api_module.CSRF_TOKENS[session_id] = {
        "token": "csrf-token",
        "kind": "session",
        "created_at": time.time(),
    }
    uploaded_text = (
        "# Netscape HTTP Cookie File\r\n.youtube.com\tTRUE\t/\tTRUE\t0\tTEST\tfresh\r\n"
    )
    request = _FakeRequest(
        client_host="127.0.0.1",
        cookies={api_module.SESSION_COOKIE: session_id},
    )

    response = asyncio.run(
        api_module.upload_cookies_form(
            request,
            csrf_token="csrf-token",
            cookie_file=_FakeUploadFile("cookies.txt", uploaded_text.encode("utf-8")),
        )
    )

    assert response.headers["location"] == "/settings?msg=cookies_updated"
    assert cookie_file.read_text(encoding="utf-8") == uploaded_text.replace(
        "\r\n", "\n"
    )
    assert oct(cookie_file.stat().st_mode & 0o777) == "0o600"

    api_module.SESSIONS.pop(session_id, None)
    api_module.CSRF_TOKENS.pop(session_id, None)


def test_upload_cookies_refuses_oversized_file_without_buffering_it(
    tmp_path,
    monkeypatch,
) -> None:
    """An oversized upload must be rejected without reading the whole body."""
    session_id = "test-upload-cookies-oversized"
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File\nold\n", encoding="utf-8")
    monkeypatch.setattr(
        api_module,
        "CONFIG",
        replace(api_module.CONFIG, cookies_file=cookie_file),
    )
    api_module.SESSIONS[session_id] = {
        "ip": "127.0.0.1",
        "created_at": time.time(),
    }
    api_module.CSRF_TOKENS[session_id] = {
        "token": "csrf-token",
        "kind": "session",
        "created_at": time.time(),
    }
    oversized_upload = _FakeUploadFile(
        "cookies.txt",
        b"# Netscape HTTP Cookie File\n"
        + b"x" * (api_module.MAX_COOKIE_UPLOAD_BYTES * 2),
    )
    request = _FakeRequest(
        client_host="127.0.0.1",
        cookies={api_module.SESSION_COOKIE: session_id},
    )

    with pytest.raises(api_module.HTTPException) as raised:
        asyncio.run(
            api_module.upload_cookies_form(
                request,
                csrf_token="csrf-token",
                cookie_file=oversized_upload,
            )
        )

    assert raised.value.status_code == 413
    assert oversized_upload.largest_read_request == (
        api_module.MAX_COOKIE_UPLOAD_BYTES + 1
    )
    assert (
        cookie_file.read_text(encoding="utf-8") == "# Netscape HTTP Cookie File\nold\n"
    )

    api_module.SESSIONS.pop(session_id, None)
    api_module.CSRF_TOKENS.pop(session_id, None)


def test_upload_cookies_rejects_invalid_cookie_header(
    tmp_path,
    monkeypatch,
) -> None:
    """Cookie uploads should reject files that are not Netscape-format cookies."""
    session_id = "test-upload-cookies-invalid"
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File\nold\n", encoding="utf-8")
    monkeypatch.setattr(
        api_module,
        "CONFIG",
        replace(api_module.CONFIG, cookies_file=cookie_file),
    )
    api_module.SESSIONS[session_id] = {
        "ip": "127.0.0.1",
        "created_at": time.time(),
    }
    api_module.CSRF_TOKENS[session_id] = {
        "token": "csrf-token",
        "kind": "session",
        "created_at": time.time(),
    }
    request = _FakeRequest(
        client_host="127.0.0.1",
        cookies={api_module.SESSION_COOKIE: session_id},
    )

    response = asyncio.run(
        api_module.upload_cookies_form(
            request,
            csrf_token="csrf-token",
            cookie_file=_FakeUploadFile("cookies.txt", b'{"not": "cookies"}\n'),
        )
    )

    assert response.headers["location"] == "/settings?msg=cookies_invalid"
    assert (
        cookie_file.read_text(encoding="utf-8") == "# Netscape HTTP Cookie File\nold\n"
    )

    api_module.SESSIONS.pop(session_id, None)
    api_module.CSRF_TOKENS.pop(session_id, None)


def test_upload_cookies_requires_valid_csrf_token(tmp_path, monkeypatch) -> None:
    """Cookie upload is an authenticated state change and must enforce CSRF."""
    session_id = "test-upload-cookies-csrf"
    cookie_file = tmp_path / "cookies.txt"
    monkeypatch.setattr(
        api_module,
        "CONFIG",
        replace(api_module.CONFIG, cookies_file=cookie_file),
    )
    api_module.SESSIONS[session_id] = {
        "ip": "127.0.0.1",
        "created_at": time.time(),
    }
    api_module.CSRF_TOKENS[session_id] = {
        "token": "csrf-token",
        "kind": "session",
        "created_at": time.time(),
    }
    request = _FakeRequest(
        client_host="127.0.0.1",
        cookies={api_module.SESSION_COOKIE: session_id},
    )

    with pytest.raises(api_module.HTTPException) as exc_info:
        asyncio.run(
            api_module.upload_cookies_form(
                request,
                csrf_token="wrong-token",
                cookie_file=_FakeUploadFile(
                    "cookies.txt",
                    b"# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tTEST\tfresh\n",
                ),
            )
        )

    assert exc_info.value.status_code == 403
    assert not cookie_file.exists()

    api_module.SESSIONS.pop(session_id, None)
    api_module.CSRF_TOKENS.pop(session_id, None)


def test_add_url_with_bypass_enqueues_single_immediate_video(
    tmp_path,
    monkeypatch,
) -> None:
    """Checked direct-video adds should trigger only that one URL immediately."""
    session_id = "test-add-url-single-immediate"
    queue_file = tmp_path / "urls.txt"
    archive_file = tmp_path / "downloaded_urls.txt"
    bypass_file = tmp_path / "bypass_age_check_urls.txt"

    monkeypatch.setattr(
        api_module,
        "CONFIG",
        replace(
            api_module.CONFIG,
            urls_file=queue_file,
            downloaded_urls_file=archive_file,
            bypass_age_check_file=bypass_file,
        ),
    )
    api_module.SESSIONS[session_id] = {
        "ip": "127.0.0.1",
        "created_at": time.time(),
    }
    api_module.CSRF_TOKENS[session_id] = {
        "token": "csrf-token",
        "kind": "session",
        "created_at": time.time(),
    }
    pop_single_url_download_requests()

    request = _FakeRequest(
        client_host="127.0.0.1",
        cookies={api_module.SESSION_COOKIE: session_id},
    )

    response = api_module.add_url_form(
        request,
        url="https://youtu.be/abc123",
        csrf_token="csrf-token",
        skip_age_check="1",
    )

    assert response.headers["location"] == "/ui?msg=added"
    assert (
        queue_file.read_text(encoding="utf-8")
        == "https://www.youtube.com/watch?v=abc123\n"
    )
    assert (
        bypass_file.read_text(encoding="utf-8")
        == "https://www.youtube.com/watch?v=abc123\n"
    )
    assert pop_single_url_download_requests() == [
        "https://www.youtube.com/watch?v=abc123"
    ]

    api_module.SESSIONS.pop(session_id, None)
    api_module.CSRF_TOKENS.pop(session_id, None)


def test_add_playlist_with_bypass_enqueues_full_playlist_immediate_run(
    tmp_path,
    monkeypatch,
) -> None:
    """Checked playlist adds should trigger a full immediate playlist run."""
    session_id = "test-add-playlist-full-immediate"
    queue_file = tmp_path / "urls.txt"
    archive_file = tmp_path / "downloaded_urls.txt"
    bypass_file = tmp_path / "bypass_age_check_urls.txt"
    playlist_url = "https://www.youtube.com/playlist?list=PL123"

    monkeypatch.setattr(
        api_module,
        "CONFIG",
        replace(
            api_module.CONFIG,
            urls_file=queue_file,
            downloaded_urls_file=archive_file,
            bypass_age_check_file=bypass_file,
        ),
    )
    api_module.SESSIONS[session_id] = {
        "ip": "127.0.0.1",
        "created_at": time.time(),
    }
    api_module.CSRF_TOKENS[session_id] = {
        "token": "csrf-token",
        "kind": "session",
        "created_at": time.time(),
    }
    pop_single_url_download_requests()
    pop_full_playlist_download_requests()

    request = _FakeRequest(
        client_host="127.0.0.1",
        cookies={api_module.SESSION_COOKIE: session_id},
    )

    response = api_module.add_url_form(
        request,
        url=f"  {playlist_url}  ",
        csrf_token="csrf-token",
        skip_age_check="1",
    )

    assert response.headers["location"] == "/ui?msg=added"
    assert queue_file.read_text(encoding="utf-8") == f"{playlist_url}\n"
    assert not bypass_file.exists()
    assert pop_single_url_download_requests() == []
    assert pop_full_playlist_download_requests() == [playlist_url]

    api_module.SESSIONS.pop(session_id, None)
    api_module.CSRF_TOKENS.pop(session_id, None)


def test_add_channel_with_checkbox_does_not_enqueue_immediate_run(
    tmp_path,
    monkeypatch,
) -> None:
    """Checked channel adds should stay queued for the normal scheduled run."""
    session_id = "test-add-channel-checkbox-no-op"
    queue_file = tmp_path / "urls.txt"
    archive_file = tmp_path / "downloaded_urls.txt"
    bypass_file = tmp_path / "bypass_age_check_urls.txt"
    channel_url = "https://www.youtube.com/@channel-one/videos"

    monkeypatch.setattr(
        api_module,
        "CONFIG",
        replace(
            api_module.CONFIG,
            urls_file=queue_file,
            downloaded_urls_file=archive_file,
            bypass_age_check_file=bypass_file,
        ),
    )
    api_module.SESSIONS[session_id] = {
        "ip": "127.0.0.1",
        "created_at": time.time(),
    }
    api_module.CSRF_TOKENS[session_id] = {
        "token": "csrf-token",
        "kind": "session",
        "created_at": time.time(),
    }
    pop_single_url_download_requests()
    pop_full_playlist_download_requests()

    request = _FakeRequest(
        client_host="127.0.0.1",
        cookies={api_module.SESSION_COOKIE: session_id},
    )

    response = api_module.add_url_form(
        request,
        url=channel_url,
        csrf_token="csrf-token",
        skip_age_check="1",
    )

    assert response.headers["location"] == "/ui?msg=added"
    assert queue_file.read_text(encoding="utf-8") == f"{channel_url}\n"
    assert not bypass_file.exists()
    assert pop_single_url_download_requests() == []
    assert pop_full_playlist_download_requests() == []

    api_module.SESSIONS.pop(session_id, None)
    api_module.CSRF_TOKENS.pop(session_id, None)


def test_add_direct_url_without_bypass_enqueues_single_immediate_video(
    tmp_path,
    monkeypatch,
) -> None:
    """Unchecked direct-video adds should still trigger only that new URL."""
    session_id = "test-add-url-single-immediate-without-bypass"
    queue_file = tmp_path / "urls.txt"
    archive_file = tmp_path / "downloaded_urls.txt"
    bypass_file = tmp_path / "bypass_age_check_urls.txt"

    monkeypatch.setattr(
        api_module,
        "CONFIG",
        replace(
            api_module.CONFIG,
            urls_file=queue_file,
            downloaded_urls_file=archive_file,
            bypass_age_check_file=bypass_file,
        ),
    )
    api_module.SESSIONS[session_id] = {
        "ip": "127.0.0.1",
        "created_at": time.time(),
    }
    api_module.CSRF_TOKENS[session_id] = {
        "token": "csrf-token",
        "kind": "session",
        "created_at": time.time(),
    }
    pop_single_url_download_requests()

    request = _FakeRequest(
        client_host="127.0.0.1",
        cookies={api_module.SESSION_COOKIE: session_id},
    )

    response = api_module.add_url_form(
        request,
        url="https://youtu.be/abc123",
        csrf_token="csrf-token",
        skip_age_check="",
    )

    assert response.headers["location"] == "/ui?msg=added"
    assert (
        queue_file.read_text(encoding="utf-8")
        == "https://www.youtube.com/watch?v=abc123\n"
    )
    assert not bypass_file.exists()
    assert pop_single_url_download_requests() == [
        "https://www.youtube.com/watch?v=abc123"
    ]

    api_module.SESSIONS.pop(session_id, None)
    api_module.CSRF_TOKENS.pop(session_id, None)


def test_add_non_youtube_direct_url_enqueues_single_immediate_video(
    tmp_path,
    monkeypatch,
) -> None:
    """Direct non-YouTube URLs should be attempted immediately without an age gate."""
    session_id = "test-add-non-youtube-single-immediate"
    queue_file = tmp_path / "urls.txt"
    archive_file = tmp_path / "downloaded_urls.txt"
    bypass_file = tmp_path / "bypass_age_check_urls.txt"
    non_youtube_url = "https://videos.example.com/watch/episode-1"

    monkeypatch.setattr(
        api_module,
        "CONFIG",
        replace(
            api_module.CONFIG,
            urls_file=queue_file,
            downloaded_urls_file=archive_file,
            bypass_age_check_file=bypass_file,
        ),
    )
    api_module.SESSIONS[session_id] = {
        "ip": "127.0.0.1",
        "created_at": time.time(),
    }
    api_module.CSRF_TOKENS[session_id] = {
        "token": "csrf-token",
        "kind": "session",
        "created_at": time.time(),
    }
    pop_single_url_download_requests()

    request = _FakeRequest(
        client_host="127.0.0.1",
        cookies={api_module.SESSION_COOKIE: session_id},
    )

    response = api_module.add_url_form(
        request,
        url=non_youtube_url,
        csrf_token="csrf-token",
        skip_age_check="",
    )

    assert response.headers["location"] == "/ui?msg=added"
    assert queue_file.read_text(encoding="utf-8") == f"{non_youtube_url}\n"
    assert not bypass_file.exists()
    assert pop_single_url_download_requests() == [non_youtube_url]

    api_module.SESSIONS.pop(session_id, None)
    api_module.CSRF_TOKENS.pop(session_id, None)


def test_add_non_youtube_direct_url_with_checkbox_does_not_write_bypass_file(
    tmp_path,
    monkeypatch,
) -> None:
    """The age-bypass checkbox should only write bypass state for YouTube URLs."""
    session_id = "test-add-non-youtube-no-bypass-file"
    queue_file = tmp_path / "urls.txt"
    archive_file = tmp_path / "downloaded_urls.txt"
    bypass_file = tmp_path / "bypass_age_check_urls.txt"
    non_youtube_url = "https://videos.example.com/watch/episode-1"

    monkeypatch.setattr(
        api_module,
        "CONFIG",
        replace(
            api_module.CONFIG,
            urls_file=queue_file,
            downloaded_urls_file=archive_file,
            bypass_age_check_file=bypass_file,
        ),
    )
    api_module.SESSIONS[session_id] = {
        "ip": "127.0.0.1",
        "created_at": time.time(),
    }
    api_module.CSRF_TOKENS[session_id] = {
        "token": "csrf-token",
        "kind": "session",
        "created_at": time.time(),
    }
    pop_single_url_download_requests()

    request = _FakeRequest(
        client_host="127.0.0.1",
        cookies={api_module.SESSION_COOKIE: session_id},
    )

    response = api_module.add_url_form(
        request,
        url=non_youtube_url,
        csrf_token="csrf-token",
        skip_age_check="1",
    )

    assert response.headers["location"] == "/ui?msg=added"
    assert queue_file.read_text(encoding="utf-8") == f"{non_youtube_url}\n"
    assert not bypass_file.exists()
    assert pop_single_url_download_requests() == [non_youtube_url]

    api_module.SESSIONS.pop(session_id, None)
    api_module.CSRF_TOKENS.pop(session_id, None)


def test_add_channel_url_does_not_trigger_immediate_batch(
    tmp_path,
    monkeypatch,
) -> None:
    """Channel/list additions should wait for the normal scheduled full-queue run."""
    session_id = "test-add-channel-no-immediate-batch"
    queue_file = tmp_path / "urls.txt"
    archive_file = tmp_path / "downloaded_urls.txt"
    bypass_file = tmp_path / "bypass_age_check_urls.txt"
    channel_url = "https://www.youtube.com/@example"

    monkeypatch.setattr(
        api_module,
        "CONFIG",
        replace(
            api_module.CONFIG,
            urls_file=queue_file,
            downloaded_urls_file=archive_file,
            bypass_age_check_file=bypass_file,
        ),
    )
    api_module.SESSIONS[session_id] = {
        "ip": "127.0.0.1",
        "created_at": time.time(),
    }
    api_module.CSRF_TOKENS[session_id] = {
        "token": "csrf-token",
        "kind": "session",
        "created_at": time.time(),
    }
    pop_single_url_download_requests()

    request = _FakeRequest(
        client_host="127.0.0.1",
        cookies={api_module.SESSION_COOKIE: session_id},
    )

    response = api_module.add_url_form(
        request,
        url=channel_url,
        csrf_token="csrf-token",
        skip_age_check="1",
    )

    assert response.headers["location"] == "/ui?msg=added"
    assert queue_file.read_text(encoding="utf-8") == f"{channel_url}\n"
    assert not bypass_file.exists()
    assert pop_single_url_download_requests() == []

    api_module.SESSIONS.pop(session_id, None)
    api_module.CSRF_TOKENS.pop(session_id, None)


def test_add_url_with_bypass_clears_pending_batch_trigger(
    tmp_path,
    monkeypatch,
) -> None:
    """The checked box should mean this URL only, even after a prior batch trigger."""
    session_id = "test-add-url-single-clears-batch"
    queue_file = tmp_path / "urls.txt"
    archive_file = tmp_path / "downloaded_urls.txt"
    bypass_file = tmp_path / "bypass_age_check_urls.txt"

    monkeypatch.setattr(
        api_module,
        "CONFIG",
        replace(
            api_module.CONFIG,
            urls_file=queue_file,
            downloaded_urls_file=archive_file,
            bypass_age_check_file=bypass_file,
        ),
    )
    api_module.SESSIONS[session_id] = {
        "ip": "127.0.0.1",
        "created_at": time.time(),
    }
    api_module.CSRF_TOKENS[session_id] = {
        "token": "csrf-token",
        "kind": "session",
        "created_at": time.time(),
    }
    pop_single_url_download_requests()

    request = _FakeRequest(
        client_host="127.0.0.1",
        cookies={api_module.SESSION_COOKIE: session_id},
    )

    response = api_module.add_url_form(
        request,
        url="https://youtu.be/def456",
        csrf_token="csrf-token",
        skip_age_check="1",
    )

    assert response.headers["location"] == "/ui?msg=added"
    assert pop_single_url_download_requests() == [
        "https://www.youtube.com/watch?v=def456"
    ]

    api_module.SESSIONS.pop(session_id, None)
    api_module.CSRF_TOKENS.pop(session_id, None)


def test_add_url_without_bypass_enqueues_single_payload_only(
    tmp_path,
    monkeypatch,
) -> None:
    """Unchecked direct-video adds should not wake the full-queue scheduler."""
    session_id = "test-add-url-single-trigger"
    queue_file = tmp_path / "urls.txt"
    archive_file = tmp_path / "downloaded_urls.txt"

    monkeypatch.setattr(
        api_module,
        "CONFIG",
        replace(
            api_module.CONFIG,
            urls_file=queue_file,
            downloaded_urls_file=archive_file,
        ),
    )
    api_module.SESSIONS[session_id] = {
        "ip": "127.0.0.1",
        "created_at": time.time(),
    }
    api_module.CSRF_TOKENS[session_id] = {
        "token": "csrf-token",
        "kind": "session",
        "created_at": time.time(),
    }
    pop_single_url_download_requests()

    request = _FakeRequest(
        client_host="127.0.0.1",
        cookies={api_module.SESSION_COOKIE: session_id},
    )

    response = api_module.add_url_form(
        request,
        url="https://youtu.be/abc123",
        csrf_token="csrf-token",
        skip_age_check="",
    )

    assert response.headers["location"] == "/ui?msg=added"
    assert pop_single_url_download_requests() == [
        "https://www.youtube.com/watch?v=abc123"
    ]

    api_module.SESSIONS.pop(session_id, None)
    api_module.CSRF_TOKENS.pop(session_id, None)


def test_add_url_accepts_non_youtube_video_url(
    tmp_path,
    monkeypatch,
) -> None:
    """The web UI should queue direct non-YouTube video URLs for yt-dlp."""
    session_id = "test-add-non-youtube-url"
    queue_file = tmp_path / "urls.txt"
    archive_file = tmp_path / "downloaded_urls.txt"

    monkeypatch.setattr(
        api_module,
        "CONFIG",
        replace(
            api_module.CONFIG,
            urls_file=queue_file,
            downloaded_urls_file=archive_file,
        ),
    )
    api_module.SESSIONS[session_id] = {
        "ip": "127.0.0.1",
        "created_at": time.time(),
    }
    api_module.CSRF_TOKENS[session_id] = {
        "token": "csrf-token",
        "kind": "session",
        "created_at": time.time(),
    }
    pop_single_url_download_requests()

    request = _FakeRequest(
        client_host="127.0.0.1",
        cookies={api_module.SESSION_COOKIE: session_id},
    )

    response = api_module.add_url_form(
        request,
        url="https://videos.example.com/watch/episode-1",
        csrf_token="csrf-token",
        skip_age_check="",
    )

    assert response.headers["location"] == "/ui?msg=added"
    assert (
        queue_file.read_text(encoding="utf-8")
        == "https://videos.example.com/watch/episode-1\n"
    )
    assert pop_single_url_download_requests() == [
        "https://videos.example.com/watch/episode-1"
    ]

    api_module.SESSIONS.pop(session_id, None)
    api_module.CSRF_TOKENS.pop(session_id, None)


def test_ui_shows_monitored_urls_with_remove_controls(tmp_path, monkeypatch) -> None:
    """The UI should show urls.txt entries and expose a remove form for each one."""
    session_id = "test-ui-monitored-urls"
    queue_file = tmp_path / "urls.txt"
    queue_file.write_text(
        "https://youtu.be/abc123\nhttps://www.youtube.com/@channelname\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        api_module,
        "CONFIG",
        replace(api_module.CONFIG, urls_file=queue_file),
    )
    api_module.SESSIONS[session_id] = {
        "ip": "127.0.0.1",
        "created_at": time.time(),
    }

    request = _FakeRequest(
        client_host="127.0.0.1",
        cookies={api_module.SESSION_COOKIE: session_id},
    )

    response = api_module.ui(request)
    body = response.body.decode("utf-8")

    assert "Monitored sources" in body
    assert "https://www.youtube.com/watch?v=abc123" in body
    assert "https://www.youtube.com/@channelname" in body
    assert 'action="/remove-url"' in body
    assert "Remove</button>" in body

    api_module.SESSIONS.pop(session_id, None)


def test_logout_invalidates_session() -> None:
    """POST /logout should remove the session and redirect to login."""
    session_id = "test-logout-session"
    api_module.SESSIONS[session_id] = {"ip": "127.0.0.1", "created_at": time.time()}
    api_module.CSRF_TOKENS[session_id] = {
        "token": "logout-csrf",
        "kind": "session",
        "created_at": time.time(),
    }

    request = _FakeRequest(
        client_host="127.0.0.1",
        cookies={api_module.SESSION_COOKIE: session_id},
    )
    response = api_module.logout(request, csrf_token="logout-csrf")

    assert response.headers["location"] == "/login"
    assert session_id not in api_module.SESSIONS


def test_logout_rejects_invalid_csrf_token() -> None:
    """POST /logout with a wrong CSRF token must return 403."""
    session_id = "test-logout-csrf-session"
    api_module.SESSIONS[session_id] = {"ip": "127.0.0.1", "created_at": time.time()}
    api_module.CSRF_TOKENS[session_id] = {
        "token": "real-csrf",
        "kind": "session",
        "created_at": time.time(),
    }

    request = _FakeRequest(
        client_host="127.0.0.1",
        cookies={api_module.SESSION_COOKIE: session_id},
    )

    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        api_module.logout(request, csrf_token="wrong-csrf")
    assert exc_info.value.status_code == 403

    api_module.SESSIONS.pop(session_id, None)
    api_module.CSRF_TOKENS.pop(session_id, None)


def test_ui_logout_is_a_post_form_not_a_link() -> None:
    """Logout must be a POST form to prevent CSRF logout via GET link."""
    session_id = "test-ui-logout-form"
    api_module.SESSIONS[session_id] = {"ip": "127.0.0.1", "created_at": time.time()}

    request = _FakeRequest(
        client_host="127.0.0.1",
        cookies={api_module.SESSION_COOKIE: session_id},
    )
    response = api_module.ui(request)
    body = response.body.decode("utf-8")

    assert 'action="/logout"' in body
    assert 'method="post"' in body.lower() or 'method="POST"' in body
    assert 'href="/logout"' not in body

    api_module.SESSIONS.pop(session_id, None)


def test_remove_url_form_deletes_url_and_redirects(tmp_path, monkeypatch) -> None:
    """Removing a monitored URL should update urls.txt and return a success banner."""
    session_id = "test-remove-url-session"
    queue_file = tmp_path / "urls.txt"
    queue_file.write_text(
        "https://www.youtube.com/watch?v=abc123\nhttps://www.youtube.com/@channelname\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        api_module,
        "CONFIG",
        replace(api_module.CONFIG, urls_file=queue_file),
    )
    api_module.SESSIONS[session_id] = {
        "ip": "127.0.0.1",
        "created_at": time.time(),
    }
    api_module.CSRF_TOKENS[session_id] = {
        "token": "csrf-token",
        "kind": "session",
        "created_at": time.time(),
    }

    request = _FakeRequest(
        client_host="127.0.0.1",
        cookies={api_module.SESSION_COOKIE: session_id},
    )

    response = api_module.remove_url_form(
        request,
        url="https://youtu.be/abc123",
        csrf_token="csrf-token",
    )

    assert response.headers["location"] == "/ui?msg=removed"
    assert (
        queue_file.read_text(encoding="utf-8")
        == "https://www.youtube.com/@channelname\n"
    )

    api_module.SESSIONS.pop(session_id, None)
    api_module.CSRF_TOKENS.pop(session_id, None)


def test_logs_endpoint_returns_401_for_expired_session() -> None:
    """An expired session must not answer the log poll with a redirect.

    The queue page fetches this endpoint every 15 seconds. ``fetch`` follows
    redirects transparently, so a redirect to ``/login`` would arrive as a
    successful HTML response and be rendered as log lines inside the log box.
    """
    from src.web import routes as api

    request = _FakeRequest(cookies={api.SESSION_COOKIE: "not-a-real-session"})

    response = api.view_logs(request)

    assert response.status_code == 401
    assert response.media_type == "text/plain"
    assert "<html" not in response.body.decode("utf-8").lower()


def test_settings_page_warns_that_testing_does_not_save() -> None:
    """Pressing Test stores nothing, so the page has to say so.

    A green test result reads as "done", and the typed endpoint then vanishes
    on the next page load.
    """
    session_id = "test-settings-save-reminder"
    api_module.SESSIONS[session_id] = {
        "ip": "127.0.0.1",
        "created_at": time.time(),
    }

    request = _FakeRequest(
        client_host="127.0.0.1",
        cookies={api_module.SESSION_COOKIE: session_id},
    )

    body = api_module.settings(request).body.decode("utf-8")

    assert "Testing does not store anything" in body
    assert "Press Save to keep these settings." in body
    assert 'id="notify-unsaved"' in body

    api_module.SESSIONS.pop(session_id, None)
