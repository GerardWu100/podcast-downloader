"""Contract tests for FastAPI application construction."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from src.notifications.apprise_client import AppriseSettings
from src.state.activity_store import ActivityLogStore
from src.state.archive_store import ArchiveStore
from src.state.auth_store import AuthStore
from src.state.bypass_store import BypassStore
from src.state.notification_store import (
    NotificationStore,
    notification_settings_file_for,
)
from src.state.queue_store import QueueStore
from src.state.run_state_store import RunKind, RunStateStore, run_state_file_for
from src.web import routes
from src.web.app import api_body_size_refusal, create_app


class _RecordingDownloadTrigger:
    """Record scheduler requests without mutating the production trigger queues."""

    def __init__(self) -> None:
        self.single_urls: list[str] = []
        self.playlist_urls: list[str] = []
        self.source_urls: list[str] = []
        self.full_queue_runs = 0

    def queue_single_url_download(self, url: str) -> None:
        """Record one direct-media scheduler request.

        Parameters
        ----------
        url:
            Normalized direct media URL.
        """
        self.single_urls.append(url)

    def queue_full_playlist_download(self, url: str) -> None:
        """Record one full-playlist scheduler request.

        Parameters
        ----------
        url:
            Normalized YouTube playlist URL.
        """
        self.playlist_urls.append(url)

    def queue_source_download(self, url: str) -> None:
        """Record one targeted saved-source request."""
        self.source_urls.append(url)

    def queue_full_queue_run(self) -> None:
        """Record one whole-queue run request from the Run button."""
        self.full_queue_runs += 1


def test_create_app_returns_independent_fastapi_instances() -> None:
    """Each factory call should own separate state and route registration."""
    first_app = create_app()
    second_app = create_app()

    assert first_app is not second_app
    assert len(first_app.routes) == len(second_app.routes)
    assert first_app.state.sessions is not second_app.state.sessions
    assert first_app.state.csrf_tokens is not second_app.state.csrf_tokens


def test_api_body_limit_rejects_unbounded_or_oversized_json() -> None:
    """Unauthenticated clients must not make FastAPI buffer arbitrary bodies."""
    request_without_length = SimpleNamespace(
        method="POST",
        url=SimpleNamespace(path="/api/add-url"),
        headers={},
    )
    oversized_request = SimpleNamespace(
        method="POST",
        url=SimpleNamespace(path="/api/add-url"),
        headers={"content-length": "1000000"},
    )

    missing_length_response = api_body_size_refusal(request_without_length)
    oversized_response = api_body_size_refusal(oversized_request)

    assert missing_length_response is not None
    assert missing_length_response.status_code == 411
    assert oversized_response is not None
    assert oversized_response.status_code == 413


def test_api_body_limit_allows_small_json_and_unrelated_routes() -> None:
    """Normal extension submissions and web pages should continue to routing."""
    small_request = SimpleNamespace(
        method="POST",
        url=SimpleNamespace(path="/api/add-url"),
        headers={"content-length": "256"},
    )
    web_request = SimpleNamespace(
        method="POST",
        url=SimpleNamespace(path="/"),
        headers={},
    )

    assert api_body_size_refusal(small_request) is None
    assert api_body_size_refusal(web_request) is None


def test_create_app_uses_injected_temporary_collaborators(tmp_path: Path) -> None:
    """Factory tests should not patch production paths or ``src.api`` globals."""
    config = replace(
        routes.CONFIG,
        urls_file=tmp_path / "urls.txt",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
        bypass_age_check_file=tmp_path / "bypass_age_check_urls.txt",
        log_file=tmp_path / "download.log",
    )
    logger = logging.getLogger("test.web.app")
    queue_store = QueueStore(config.urls_file, logger)
    archive_store = ArchiveStore(config.downloaded_urls_file, logger)
    bypass_store = BypassStore(config.bypass_age_check_file, logger)
    activity_store = ActivityLogStore(tmp_path / "activity.log")
    auth_store = AuthStore(
        session_file=tmp_path / ".ui_sessions.json",
        login_state_file=tmp_path / ".login_state.json",
    )
    trigger = _RecordingDownloadTrigger()

    app = create_app(
        config,
        queue_store=queue_store,
        archive_store=archive_store,
        bypass_store=bypass_store,
        activity_store=activity_store,
        auth_store=auth_store,
        trigger=trigger,
    )

    assert app.state.config is config
    assert app.state.queue_store is queue_store
    assert app.state.archive_store is archive_store
    assert app.state.bypass_store is bypass_store
    assert app.state.activity_store is activity_store
    assert app.state.auth_store is auth_store
    assert app.state.download_trigger is trigger


def test_routes_use_collaborators_injected_by_create_app(tmp_path: Path) -> None:
    """A request should write only through the app's injected collaborators."""
    config = replace(
        routes.CONFIG,
        urls_file=tmp_path / "injected_urls.txt",
        downloaded_urls_file=tmp_path / "injected_downloaded_urls.txt",
        bypass_age_check_file=tmp_path / "injected_bypass_urls.txt",
        log_file=tmp_path / "injected_download.log",
        cookies_file=tmp_path / "injected_cookies.txt",
    )
    logger = logging.getLogger("test.web.app.routes")
    queue_store = QueueStore(config.urls_file, logger)
    archive_store = ArchiveStore(config.downloaded_urls_file, logger)
    bypass_store = BypassStore(config.bypass_age_check_file, logger)
    activity_store = ActivityLogStore(tmp_path / "injected_activity.log")
    auth_store = AuthStore(
        session_file=tmp_path / "injected_sessions.json",
        login_state_file=tmp_path / "injected_login_state.json",
    )
    trigger = _RecordingDownloadTrigger()
    app = create_app(
        config,
        queue_store=queue_store,
        archive_store=archive_store,
        bypass_store=bypass_store,
        activity_store=activity_store,
        auth_store=auth_store,
        trigger=trigger,
    )

    session_id = "injected-app-session"
    csrf_token = "injected-app-csrf"
    app.state.sessions[session_id] = {"created_at": time.time()}
    app.state.csrf_tokens[session_id] = {
        "token": csrf_token,
        "kind": "session",
        "created_at": time.time(),
    }
    request = SimpleNamespace(
        app=app,
        headers={},
        client=SimpleNamespace(host="127.0.0.1"),
        cookies={routes.SESSION_COOKIE: session_id},
    )

    response = routes.add_url_form(
        request,
        url="https://youtu.be/injected123",
        csrf_token=csrf_token,
        skip_age_check="1",
    )

    normalized_url = "https://www.youtube.com/watch?v=injected123"
    assert response.headers["location"] == "/?msg=added"
    assert queue_store.read_urls() == [normalized_url]
    assert bypass_store.load() == {normalized_url}
    assert trigger.single_urls == [normalized_url]
    assert trigger.playlist_urls == []
    assert routes._configured_cookie_file(request) == tmp_path / "injected_cookies.txt"

    activity_store.write_event("Injected activity event")
    log_response = routes.view_logs(request)
    assert "Injected activity event" in log_response.body.decode("utf-8")

    logout_response = routes.logout(request, csrf_token)
    assert logout_response.headers["location"] == "/login"
    persisted_sessions = auth_store.load_sessions(routes.SESSION_MAX_AGE_SECONDS)
    assert auth_store.session_file.exists()
    assert session_id not in persisted_sessions


def test_create_app_loads_sessions_from_injected_auth_store(tmp_path: Path) -> None:
    """A factory app should authenticate against its own persisted sessions."""
    auth_store = AuthStore(
        session_file=tmp_path / "sessions.json",
        login_state_file=tmp_path / "login.json",
    )
    session_id = "persisted-injected-session"
    auth_store.save_sessions({session_id: {"created_at": time.time()}})
    app = create_app(auth_store=auth_store)
    request = SimpleNamespace(
        app=app,
        cookies={routes.SESSION_COOKIE: session_id},
    )

    assert routes._require_login(request) is None


def _logged_in_request(app, session_id: str = "notify-test-session"):
    """Return a request fake with a valid session and matching CSRF token."""
    app.state.sessions[session_id] = {"created_at": time.time()}
    csrf_token = routes._get_csrf_token(session_id, SimpleNamespace(app=app))
    request = SimpleNamespace(app=app, cookies={routes.SESSION_COOKIE: session_id})
    return request, csrf_token


def test_saving_notification_settings_persists_them(tmp_path: Path) -> None:
    """The save form should write settings the downloader can read back."""
    store = NotificationStore(notification_settings_file_for(tmp_path))
    app = create_app(notification_store=store)
    request, csrf_token = _logged_in_request(app)

    response = routes.save_notifications_form(
        request,
        csrf_token=csrf_token,
        server_url="http://apprise.test/notify/key",
        notification_urls="tgram://token/chatid",
        tag="podcasts",
        enabled="1",
    )

    assert response.headers["location"] == "/settings?msg=notifications_saved"
    saved_settings = store.load()
    assert saved_settings.enabled is True
    assert saved_settings.server_url == "http://apprise.test/notify/key"
    assert saved_settings.notification_urls == "tgram://token/chatid"


def test_enabling_notifications_requires_a_usable_url(tmp_path: Path) -> None:
    """Turning notifications on without a valid endpoint must be refused."""
    store = NotificationStore(notification_settings_file_for(tmp_path))
    app = create_app(notification_store=store)
    request, csrf_token = _logged_in_request(app)

    response = routes.save_notifications_form(
        request,
        csrf_token=csrf_token,
        server_url="ftp://apprise.test/notify",
        notification_urls="",
        tag="",
        enabled="1",
    )

    assert response.headers["location"] == "/settings?msg=notifications_invalid"
    assert store.load() == AppriseSettings()


def test_settings_can_be_turned_off_without_an_url(tmp_path: Path) -> None:
    """Clearing the form and saving with the box unticked should succeed."""
    store = NotificationStore(notification_settings_file_for(tmp_path))
    app = create_app(notification_store=store)
    request, csrf_token = _logged_in_request(app)

    # Direct calls bypass FastAPI's form defaults, so every field is supplied.
    response = routes.save_notifications_form(
        request,
        csrf_token=csrf_token,
        server_url="",
        notification_urls="",
        tag="",
        enabled="",
    )

    assert response.headers["location"] == "/settings?msg=notifications_saved"
    assert store.load().enabled is False


def test_test_button_reports_a_refused_url_without_sending(tmp_path: Path) -> None:
    """The test endpoint should explain a bad URL rather than attempt a request."""
    app = create_app(
        notification_store=NotificationStore(notification_settings_file_for(tmp_path))
    )
    request, csrf_token = _logged_in_request(app)

    response = routes.test_notification(
        request,
        csrf_token=csrf_token,
        server_url="not-a-url",
        notification_urls="",
        tag="",
    )

    payload = json.loads(response.body)
    assert payload["ok"] is False
    assert "http://" in payload["detail"]


def test_test_button_requires_a_session(tmp_path: Path) -> None:
    """An expired session must not be able to make the server send requests."""
    app = create_app(
        notification_store=NotificationStore(notification_settings_file_for(tmp_path))
    )
    request = SimpleNamespace(app=app, cookies={})

    response = routes.test_notification(
        request,
        csrf_token="irrelevant",
        server_url="http://apprise.test/notify/key",
        notification_urls="",
        tag="",
    )

    assert response.status_code == 401


def _signed_in_request(app, session_id: str, csrf_token: str) -> SimpleNamespace:
    """Return a request object carrying a valid session and CSRF token.

    Parameters
    ----------
    app:
        Application whose state holds the sessions and tokens.
    session_id:
        Session identifier to register and send as a cookie.
    csrf_token:
        Token registered for that session.
    """
    app.state.sessions[session_id] = {"created_at": time.time()}
    app.state.csrf_tokens[session_id] = {
        "token": csrf_token,
        "kind": "session",
        "created_at": time.time(),
    }
    return SimpleNamespace(
        app=app,
        headers={},
        client=SimpleNamespace(host="127.0.0.1"),
        cookies={routes.SESSION_COOKIE: session_id},
    )


def test_run_button_asks_the_scheduler_for_a_whole_queue_pass(tmp_path: Path) -> None:
    """The Run button must request the same work the schedule performs."""
    trigger = _RecordingDownloadTrigger()
    run_state_store = RunStateStore(run_state_file_for(tmp_path))
    app = create_app(
        replace(routes.CONFIG, urls_file=tmp_path / "urls.txt"),
        run_state_store=run_state_store,
        trigger=trigger,
    )
    request = _signed_in_request(app, "run-now-session", "run-now-csrf")

    response = routes.run_now_form(request, csrf_token="run-now-csrf")

    assert response.headers["location"] == "/?msg=run_started"
    assert trigger.full_queue_runs == 1
    assert trigger.single_urls == []


def test_source_run_button_targets_only_the_selected_saved_source(
    tmp_path: Path,
) -> None:
    """A source-row button should queue its URL without running the whole queue."""
    source_url = "https://www.youtube.com/@examplechannel"
    queue_file = tmp_path / "urls.txt"
    queue_file.write_text(f"{source_url}\n", encoding="utf-8")
    trigger = _RecordingDownloadTrigger()
    app = create_app(
        replace(routes.CONFIG, urls_file=queue_file),
        trigger=trigger,
    )
    request = _signed_in_request(app, "source-now-session", "source-now-csrf")

    response = routes.run_source_form(
        request,
        url=source_url,
        csrf_token="source-now-csrf",
    )

    assert response.headers["location"] == "/?msg=source_run_started"
    assert trigger.source_urls == [source_url]
    assert trigger.full_queue_runs == 0
    assert trigger.single_urls == []


def test_source_run_button_rejects_a_url_no_longer_in_queue(tmp_path: Path) -> None:
    """A stale or forged source-row form must not start arbitrary work."""
    trigger = _RecordingDownloadTrigger()
    app = create_app(
        replace(routes.CONFIG, urls_file=tmp_path / "urls.txt"),
        trigger=trigger,
    )
    request = _signed_in_request(app, "stale-source-session", "stale-source-csrf")

    response = routes.run_source_form(
        request,
        url="https://www.youtube.com/watch?v=not-saved",
        csrf_token="stale-source-csrf",
    )

    assert response.headers["location"] == "/?msg=notfound"
    assert trigger.source_urls == []


def test_run_button_is_refused_while_a_run_is_already_going(tmp_path: Path) -> None:
    """Two passes over one queue would fight over the same state files."""
    trigger = _RecordingDownloadTrigger()
    run_state_store = RunStateStore(run_state_file_for(tmp_path))
    run_state_store.mark_run_started(RunKind.SCHEDULED)
    app = create_app(
        replace(routes.CONFIG, urls_file=tmp_path / "urls.txt"),
        run_state_store=run_state_store,
        trigger=trigger,
    )
    request = _signed_in_request(app, "run-busy-session", "run-busy-csrf")

    response = routes.run_now_form(request, csrf_token="run-busy-csrf")

    assert response.headers["location"] == "/?msg=run_already_running"
    assert trigger.full_queue_runs == 0
