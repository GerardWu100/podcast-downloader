"""Production Uvicorn entrypoint for the podcast downloader web interface."""

from __future__ import annotations

import sys

from .web import routes
from .web.app import create_app

routes.app = create_app()

# Preserve the old direct-helper test surface during the web extraction.
# Phase 5 moves tests to the application factory, after which this alias goes.
sys.modules[__name__] = routes
