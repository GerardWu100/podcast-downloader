"""Production Uvicorn entrypoint for the podcast downloader web interface."""

from __future__ import annotations

from .web.app import create_app

app = create_app()
