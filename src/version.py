"""The application's version, read from ``pyproject.toml``.

``pyproject.toml`` is the one place the version is written. The Docker image
copies it next to ``src/``, and ``tests/test_version.py`` fails when the
browser extension's manifests disagree with it, so the server, the image tag,
and the extension always ship under one number.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

PYPROJECT_FILE = Path(__file__).resolve().parent.parent / "pyproject.toml"


def read_app_version() -> str:
    """Return ``[project].version`` from ``pyproject.toml``, such as ``"2.0.0"``."""
    with PYPROJECT_FILE.open("rb") as pyproject:
        return tomllib.load(pyproject)["project"]["version"]


APP_VERSION = read_app_version()
