"""The server, the Docker image tag, and the extension share one version."""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.version import APP_VERSION

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SEMANTIC_VERSION = re.compile(r"\d+\.\d+\.\d+")


def test_version_is_major_minor_patch() -> None:
    """The release workflow turns tag vX.Y.Z into image tags; other shapes break it."""
    assert SEMANTIC_VERSION.fullmatch(APP_VERSION)


def test_extension_manifests_match_the_app_version() -> None:
    """A release must not ship an extension numbered differently from its server."""
    for manifest_name in ("manifest.json", "manifest.firefox.json"):
        manifest = json.loads(
            (PROJECT_ROOT / "extension" / "src" / manifest_name).read_text(encoding="utf-8")
        )
        assert manifest["version"] == APP_VERSION, manifest_name
