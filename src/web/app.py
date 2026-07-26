"""Construct the FastAPI web application."""

from __future__ import annotations

from fastapi import FastAPI

from ..config import PodcastConfig
from ..state.activity_store import ActivityLogStore
from ..state.archive_store import ArchiveStore
from ..state.bypass_store import BypassStore
from ..state.queue_store import QueueStore
from . import routes


def create_app(
    config: PodcastConfig | None = None,
    *,
    queue_store: QueueStore | None = None,
    archive_store: ArchiveStore | None = None,
    bypass_store: BypassStore | None = None,
    activity_store: ActivityLogStore | None = None,
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

    Returns
    -------
    FastAPI
        Application exposed by ``uvicorn src.api:app``.
    """
    # Collaborators are attached at one construction seam. Route handlers move
    # to these values in the next extraction without adding module globals.
    app = routes.app
    app.state.config = config or routes.CONFIG
    app.state.queue_store = queue_store
    app.state.archive_store = archive_store
    app.state.bypass_store = bypass_store
    app.state.activity_store = activity_store
    return app
