"""Assemble the Firefox build of the browser extension.

Chrome loads ``extension/`` directly, because ``extension/manifest.json`` is
the Chrome manifest. Firefox needs a different manifest -- it has no extension
service workers, it wants a stable add-on id, and it reads ``options_ui``
rather than ``options_page`` -- but every other file is identical.

Rather than keep a second copy of the JavaScript, this script copies the shared
files into ``build/firefox-extension/`` and drops ``manifest.firefox.json`` in
as that folder's ``manifest.json``.

Usage
-----
    uv run python scripts/build_firefox_extension.py
    uv run python scripts/build_firefox_extension.py --zip

The plain form produces a folder to load through ``about:debugging``. ``--zip``
also writes ``build/podcast-downloader-firefox.zip``, which is the shape
addons.mozilla.org wants when you sign the add-on so it survives a restart.
"""

from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = PROJECT_ROOT / "extension"
BUILD_DIR = PROJECT_ROOT / "build" / "firefox-extension"
ZIP_FILE = PROJECT_ROOT / "build" / "podcast-downloader-firefox.zip"

CHROME_MANIFEST = "manifest.json"
FIREFOX_MANIFEST = "manifest.firefox.json"
# Files that belong to the repository rather than to a browser build.
EXCLUDED_NAMES = frozenset({CHROME_MANIFEST, FIREFOX_MANIFEST, "GUIDE_extension.md"})


def collect_shared_files() -> list[Path]:
    """Return every extension file that both browsers use, sorted for stability.

    Returns
    -------
    list[Path]
        Paths relative to ``extension/``, excluding the two manifests and the
        developer guide.
    """
    return sorted(
        path.relative_to(SOURCE_DIR)
        for path in SOURCE_DIR.rglob("*")
        if path.is_file() and path.name not in EXCLUDED_NAMES
    )


def build(*, make_zip: bool) -> Path:
    """Write the Firefox build and optionally the archive beside it.

    Parameters
    ----------
    make_zip:
        True to also write :data:`ZIP_FILE` for signing.

    Returns
    -------
    Path
        The build directory.

    Raises
    ------
    FileNotFoundError
        When the Firefox manifest is missing.
    ValueError
        When the two manifests disagree on the version number, which would ship
        Firefox users a build labelled differently from the Chrome one.
    """
    firefox_manifest_file = SOURCE_DIR / FIREFOX_MANIFEST
    if not firefox_manifest_file.is_file():
        raise FileNotFoundError(f"missing {firefox_manifest_file}")

    chrome_manifest = json.loads((SOURCE_DIR / CHROME_MANIFEST).read_text())
    firefox_manifest = json.loads(firefox_manifest_file.read_text())
    if chrome_manifest["version"] != firefox_manifest["version"]:
        raise ValueError(
            f"version mismatch: {CHROME_MANIFEST} says "
            f"{chrome_manifest['version']!r} and {FIREFOX_MANIFEST} says "
            f"{firefox_manifest['version']!r}"
        )

    # Start clean so a file deleted from extension/ cannot linger in the build.
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    BUILD_DIR.mkdir(parents=True)

    shared_files = collect_shared_files()
    for relative_path in shared_files:
        destination = BUILD_DIR / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE_DIR / relative_path, destination)

    shutil.copy2(firefox_manifest_file, BUILD_DIR / CHROME_MANIFEST)

    print(f"Copied {len(shared_files)} shared files into {BUILD_DIR}")
    print(f"Wrote {FIREFOX_MANIFEST} as {BUILD_DIR / CHROME_MANIFEST}")

    if make_zip:
        ZIP_FILE.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(ZIP_FILE, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(BUILD_DIR.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(BUILD_DIR))
        print(f"Wrote {ZIP_FILE}")

    return BUILD_DIR


def main() -> None:
    """Parse arguments and run the build."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--zip",
        action="store_true",
        dest="make_zip",
        help="also write the archive to upload to addons.mozilla.org",
    )
    arguments = parser.parse_args()
    build(make_zip=arguments.make_zip)


if __name__ == "__main__":
    main()
