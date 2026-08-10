"""Expose the production web app to Uvicorn."""

from __future__ import annotations

from .web.app import create_app

app = create_app()
