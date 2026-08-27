"""Guard what `COPY . .` puts into the container image.

The Dockerfile copies the whole repository in one step, so everything that is
not excluded by ``.dockerignore`` ships to production. That is convenient and
easy to get wrong: adding a folder to the repository silently adds it to the
image unless someone remembers this file.

These tests name the folders that must never end up in the image and fail when
one loses its exclusion.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCKERIGNORE_FILE = PROJECT_ROOT / ".dockerignore"

# Folders the running container has no use for. The server is src/ plus the
# root entry points; none of these are imported by src/, start.py, or
# docker-entrypoint.sh.
DEVELOPER_ONLY_DIRECTORIES = (
    "extension",  # browser code, runs in the user's browser, not on the server
    "tests",
    "scripts",
    "docs",
    "blog",
)

# Folders that tools generate. These are the dangerous ones: they are absent on
# a clean checkout, so a missing exclusion shows up only on the machine that
# happened to run the generator before building.
GENERATED_DIRECTORIES = (
    "build",  # scripts/build_firefox_extension.py writes the Firefox extension here
    "dist",
)


def dockerignore_entries() -> set[str]:
    """Return the ``.dockerignore`` patterns, without comments or blank lines."""
    return {
        line.strip()
        for line in DOCKERIGNORE_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


@pytest.mark.parametrize("directory", DEVELOPER_ONLY_DIRECTORIES)
def test_developer_only_directories_stay_out_of_the_image(directory: str) -> None:
    """Nothing the server does not import should be shipped to production."""
    assert f"{directory}/" in dockerignore_entries()


@pytest.mark.parametrize("directory", GENERATED_DIRECTORIES)
def test_generated_directories_stay_out_of_the_image(directory: str) -> None:
    """Generated output must be excluded even though it is absent from a clean checkout.

    ``build/`` is the live example: it holds the assembled Firefox extension, it
    is in ``.gitignore`` so nobody sees it in a diff, and without an entry here
    ``docker compose up --build`` would bake whichever copy happened to exist on
    the build machine into the image.
    """
    assert f"{directory}/" in dockerignore_entries()


def test_the_server_code_is_not_excluded() -> None:
    """A guard against over-excluding: the image still needs the application."""
    entries = dockerignore_entries()

    for required in ("src/", "start.py", "main.py", "config.ini"):
        assert required not in entries


def test_secrets_and_runtime_state_stay_out_of_the_image() -> None:
    """Login state and cookies belong to the mounted data directory, not the image."""
    entries = dockerignore_entries()

    for secret in (
        ".ui_credentials.json",
        ".ui_sessions.json",
        ".login_state.json",
        "urls.txt",
        "downloaded_urls.txt",
    ):
        assert secret in entries
