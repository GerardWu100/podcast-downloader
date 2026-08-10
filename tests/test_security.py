"""Tests for security fixes and code quality."""

import subprocess
import time
from pathlib import Path

from src.media import youtube


def test_expand_command_uses_separator(monkeypatch) -> None:
    """The expansion command should pass the URL after the ``--`` separator."""
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(youtube.subprocess, "run", fake_run)

    youtube.expand_channel_or_playlist(
        "https://www.youtube.com/@example",
        channel_count=1,
        min_channel_video_age_hours=0,
        logger=youtube.logging.getLogger("test"),
    )

    command = commands[0]
    separator_index = command.index("--")
    assert command[separator_index + 1] == "https://www.youtube.com/@example/videos"
    assert separator_index == len(command) - 2


def test_bare_youtube_channel_expands_from_videos_tab(monkeypatch) -> None:
    """A bare channel URL should poll normal uploads instead of mixed channel tabs."""
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(youtube.subprocess, "run", fake_run)

    youtube.expand_channel_or_playlist(
        "https://www.youtube.com/@TopTradersUnplugged/",
        channel_count=1,
        min_channel_video_age_hours=0,
        logger=youtube.logging.getLogger("test"),
    )

    command = commands[0]
    separator_index = command.index("--")
    assert (
        command[separator_index + 1]
        == "https://www.youtube.com/@TopTradersUnplugged/videos"
    )


def test_youtube_channel_videos_tab_expands_from_videos_tab(monkeypatch) -> None:
    """An explicit videos URL should continue to poll normal channel uploads."""
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(youtube.subprocess, "run", fake_run)

    youtube.expand_channel_or_playlist(
        "https://www.youtube.com/@TopTradersUnplugged/videos",
        channel_count=1,
        min_channel_video_age_hours=0,
        logger=youtube.logging.getLogger("test"),
    )

    command = commands[0]
    separator_index = command.index("--")
    assert (
        command[separator_index + 1]
        == "https://www.youtube.com/@TopTradersUnplugged/videos"
    )


def test_youtube_channel_streams_tab_expands_from_streams_tab(monkeypatch) -> None:
    """An explicit streams URL should poll livestream uploads, not normal videos."""
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(youtube.subprocess, "run", fake_run)

    youtube.expand_channel_or_playlist(
        "https://www.youtube.com/@TopTradersUnplugged/streams",
        channel_count=1,
        min_channel_video_age_hours=0,
        logger=youtube.logging.getLogger("test"),
    )

    command = commands[0]
    separator_index = command.index("--")
    assert (
        command[separator_index + 1]
        == "https://www.youtube.com/@TopTradersUnplugged/streams"
    )


def test_login_action_accepts_valid_credentials_and_rejects_invalid_password(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Login should authenticate by behavior without relying on implementation text."""
    import json

    from src.credentials import CREDENTIALS_FILENAME
    from src.passwords import hash_password
    from src.web import routes as api

    credentials_file = tmp_path / CREDENTIALS_FILENAME
    credentials_file.write_text(
        json.dumps(
            {"username": "alice", "password_hash": hash_password("correct-password")}
        ),
        encoding="utf-8",
    )
    session_state_file = tmp_path / ".ui_sessions.json"

    class FakeURL:
        """Minimal request URL used by cookie security detection."""

        scheme = "http"

    class FakeClient:
        """Minimal request client used by login rate limiting."""

        host = "127.0.0.1"

    class FakeRequest:
        """Small request double with the attributes login_action reads."""

        url = FakeURL()
        client = FakeClient()
        headers: dict[str, str] = {}

    monkeypatch.setattr(api, "DATA_DIR", tmp_path)
    monkeypatch.setattr(api, "SESSION_STATE_FILE", session_state_file)
    api.SESSIONS.clear()
    api.CSRF_TOKENS.clear()

    bad_csrf_session, bad_csrf_token = api._store_login_csrf_token()
    bad_response = api.login_action(
        FakeRequest(),
        username="alice",
        password="wrong-password",
        csrf_token=bad_csrf_token,
        csrf_session=bad_csrf_session,
    )

    wrong_user_csrf_session, wrong_user_csrf_token = api._store_login_csrf_token()
    wrong_user_response = api.login_action(
        FakeRequest(),
        username="mallory",
        password="correct-password",
        csrf_token=wrong_user_csrf_token,
        csrf_session=wrong_user_csrf_session,
    )

    good_csrf_session, good_csrf_token = api._store_login_csrf_token()
    good_response = api.login_action(
        FakeRequest(),
        username="alice",
        password="correct-password",
        csrf_token=good_csrf_token,
        csrf_session=good_csrf_session,
    )

    assert bad_response.status_code == 303
    assert bad_response.headers["location"] == "/login?msg=bad_credentials"
    assert wrong_user_response.status_code == 303
    assert wrong_user_response.headers["location"] == "/login?msg=bad_credentials"
    assert good_response.status_code == 302
    assert good_response.headers["location"] == "/ui"
    assert api.SESSIONS
    assert (tmp_path / ".login_state.json").exists()
    assert session_state_file.exists()
    assert api._load_login_state()["127.0.0.1"]["failed"] == 0


def test_login_action_rejects_invalid_csrf_token(tmp_path: Path, monkeypatch) -> None:
    """Login should reject a mismatched CSRF token before checking credentials."""
    from src.web import routes as api

    class FakeURL:
        """Minimal request URL used by cookie security detection."""

        scheme = "http"

    class FakeClient:
        """Minimal request client used by login rate limiting."""

        host = "127.0.0.1"

    class FakeRequest:
        """Small request double with the attributes login_action reads."""

        url = FakeURL()
        client = FakeClient()
        headers: dict[str, str] = {}

    monkeypatch.setattr(api, "DATA_DIR", tmp_path)
    api.CSRF_TOKENS.clear()
    csrf_session, _csrf_token = api._store_login_csrf_token()

    response = api.login_action(
        FakeRequest(),
        username="unused-user",
        password="unused-password",
        csrf_token="wrong-token",
        csrf_session=csrf_session,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/login?msg=csrf"


def test_timing_safe_password_comparison() -> None:
    """Password hash verification should reject near misses and accept exact matches."""
    from src.passwords import hash_password, verify_password

    stored_hash = hash_password("correct-password")

    assert verify_password("correct-password", stored_hash)
    assert not verify_password("correct-passw0rd", stored_hash)


def test_session_expiry() -> None:
    """Sessions older than SESSION_MAX_AGE_SECONDS must be rejected."""
    from src.web.routes import SESSION_MAX_AGE_SECONDS, SESSIONS, _require_login

    # Create an expired session
    expired_session_id = "test-expired-session"
    SESSIONS[expired_session_id] = {
        "created_at": str(time.time() - SESSION_MAX_AGE_SECONDS - 1),
    }

    # Create a mock request
    class FakeCookies(dict):
        def get(self, key: str, default: str | None = None) -> str | None:
            return super().get(key, default)

    class FakeRequest:
        cookies = FakeCookies({("podcast_session"): expired_session_id})

    result = _require_login(FakeRequest())
    assert result is not None, "Expired session should redirect to login"
    # The expired session should have been removed
    assert expired_session_id not in SESSIONS


def test_valid_session_not_expired() -> None:
    """A fresh session should not be rejected."""
    from src.web.routes import SESSIONS, _require_login

    valid_session_id = "test-valid-session"
    SESSIONS[valid_session_id] = {
        "created_at": str(time.time()),
    }

    class FakeCookies(dict):
        def get(self, key: str, default: str | None = None) -> str | None:
            return super().get(key, default)

    class FakeRequest:
        cookies = FakeCookies({("podcast_session"): valid_session_id})

    result = _require_login(FakeRequest())
    assert result is None, "Valid session should not redirect"

    # Cleanup
    SESSIONS.pop(valid_session_id, None)


def test_session_state_persists_across_restart(monkeypatch, tmp_path) -> None:
    """Remembered sessions should survive a process restart via disk state."""
    from src.web import routes as api

    monkeypatch.setattr(api, "SESSION_STATE_FILE", tmp_path / ".ui_sessions.json")
    api.SESSIONS.clear()

    session_id = "test-persisted-session"
    api.SESSIONS[session_id] = {
        "created_at": str(time.time()),
    }
    api._save_session_state(api.SESSIONS)

    api.SESSIONS.clear()
    api.SESSIONS.update(api._load_session_state())

    class FakeCookies(dict):
        def get(self, key: str, default: str | None = None) -> str | None:
            return super().get(key, default)

    class FakeClient:
        host = "203.0.113.99"

    class FakeRequest:
        cookies = FakeCookies({("podcast_session"): session_id})
        client = FakeClient()
        headers = {}

    result = api._require_login(FakeRequest())
    assert result is None, "Persisted session should still be accepted after reload"


def test_session_is_not_bound_to_ip() -> None:
    """A remembered session should not depend on the login IP address."""
    from src.web.routes import SESSIONS, _require_login

    session_id = "test-no-ip-binding"
    SESSIONS[session_id] = {
        "created_at": str(time.time()),
    }

    class FakeCookies(dict):
        def get(self, key: str, default: str | None = None) -> str | None:
            return super().get(key, default)

    class FakeClient:
        host = "198.51.100.42"

    class FakeRequest:
        cookies = FakeCookies({("podcast_session"): session_id})
        client = FakeClient()
        headers = {}

    result = _require_login(FakeRequest())
    assert result is None, "Session should remain valid regardless of client IP"
    SESSIONS.pop(session_id, None)


def test_secure_cookie_respects_forwarded_proto(monkeypatch) -> None:
    """Cloudflare-proxied HTTPS should still mark the session cookie Secure."""
    from types import SimpleNamespace

    from src.web import routes as api

    monkeypatch.setattr(api, "CONFIG", SimpleNamespace(trust_x_forwarded_for=True))

    class FakeURL:
        scheme = "http"

    class FakeHeaders(dict):
        pass

    class FakeRequest:
        url = FakeURL()
        headers = FakeHeaders({"X-Forwarded-Proto": "https"})

    assert api._request_is_secure(FakeRequest())

    response = api.RedirectResponse(url="/ui")
    api._set_session_cookie(response, FakeRequest(), "session-id")
    assert "Secure" in response.headers.get("set-cookie", "")


def test_normalize_youtube_url() -> None:
    """Basic URL normalization tests."""
    assert (
        youtube.normalize_youtube_url("https://youtu.be/abc123")
        == "https://www.youtube.com/watch?v=abc123"
    )

    assert (
        youtube.normalize_youtube_url(
            "https://www.youtube.com/watch?v=abc123&list=PLxyz"
        )
        == "https://www.youtube.com/watch?v=abc123"
    )

    # Channel URLs should pass through unchanged
    channel = "https://www.youtube.com/@testchannel"
    assert youtube.normalize_youtube_url(channel) == channel


def test_is_channel_or_playlist() -> None:
    """Channel and playlist detection tests."""
    assert youtube.is_channel_or_playlist("https://www.youtube.com/@user")
    assert youtube.is_channel_or_playlist("https://www.youtube.com/c/name")
    assert youtube.is_channel_or_playlist("https://www.youtube.com/channel/UC123")
    assert youtube.is_channel_or_playlist("https://www.youtube.com/playlist?list=PL123")
    assert not youtube.is_channel_or_playlist("https://www.youtube.com/watch?v=abc")
    assert not youtube.is_channel_or_playlist(
        "https://videos.example.com/playlist?list=abc"
    )


def test_is_youtube_short_url() -> None:
    """Shorts URL detection."""
    assert youtube.is_youtube_short_url("https://www.youtube.com/shorts/abc123")
    assert not youtube.is_youtube_short_url("https://www.youtube.com/watch?v=abc123")
