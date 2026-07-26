"""Contract tests for FastAPI application construction."""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import time

from src.state.activity_store import ActivityLogStore
from src.state.archive_store import ArchiveStore
from src.state.auth_store import AuthStore
from src.state.bypass_store import BypassStore
from src.state.queue_store import QueueStore
from src.web import routes
from src.web.app import create_app


class _RecordingDownloadTrigger:
    """Record scheduler requests without mutating the production trigger queues."""

    def __init__(self) -> None:
        self.single_urls: list[str] = []
        self.playlist_urls: list[str] = []

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


def test_create_app_returns_independent_fastapi_instances() -> None:
    """Each factory call should own separate state and route registration."""
    first_app = create_app()
    second_app = create_app()

    assert first_app is not second_app
    assert len(first_app.routes) == len(second_app.routes)


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
    routes.SESSIONS[session_id] = {"created_at": time.time()}
    routes.CSRF_TOKENS[session_id] = {
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

    try:
        response = routes.add_url_form(
            request,
            url="https://youtu.be/injected123",
            csrf_token=csrf_token,
            skip_age_check="1",
        )

        normalized_url = "https://www.youtube.com/watch?v=injected123"
        assert response.headers["location"] == "/ui?msg=added"
        assert queue_store.read_urls() == [normalized_url]
        assert bypass_store.load() == {normalized_url}
        assert trigger.single_urls == [normalized_url]
        assert trigger.playlist_urls == []
        assert routes._configured_cookie_file(request) == tmp_path / "cookies.txt"

        activity_store.write_event("Injected activity event")
        log_response = routes.view_logs(request)
        assert "Injected activity event" in log_response.body.decode("utf-8")

        logout_response = routes.logout(request, csrf_token)
        assert logout_response.headers["location"] == "/login"
        persisted_sessions = auth_store.load_sessions(routes.SESSION_MAX_AGE_SECONDS)
        assert auth_store.session_file.exists()
        assert session_id not in persisted_sessions
    finally:
        routes.SESSIONS.pop(session_id, None)
        routes.CSRF_TOKENS.pop(session_id, None)
