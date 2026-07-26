"""Contract tests for FastAPI application construction."""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from src.state.activity_store import ActivityLogStore
from src.state.archive_store import ArchiveStore
from src.state.auth_store import AuthStore
from src.state.bypass_store import BypassStore
from src.state.queue_store import QueueStore
from src.web import routes
from src.web.app import create_app


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
    trigger = object()

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
