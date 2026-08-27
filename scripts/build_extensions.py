"""Package the browser extension for Chrome and for Firefox.

``extension/`` is the single source. Chrome can load that folder directly, so
this script is not needed for day-to-day Chrome work; it exists to produce the
two archives attached to a release, and the Firefox folder, which Chrome's
manifest cannot serve.

The browsers need different manifests. Firefox has no extension service
workers, so ``background.js`` runs as an event page; it wants a stable add-on
id before it will install anything permanently; and it reads ``options_ui``
where Chrome reads ``options_page``. Every other file is identical, which is
why the difference lives in ``extension/manifest.firefox.json`` rather than in
a second copy of the JavaScript.

Usage
-----
    uv run python scripts/build_extensions.py            # both folders
    uv run python scripts/build_extensions.py --zip      # folders and archives
    uv run python scripts/build_extensions.py --browser firefox

Archives are named with the manifest version, so a downloaded file says which
build it is.
"""

from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path
from typing import NamedTuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = PROJECT_ROOT / "extension"
BUILD_ROOT = PROJECT_ROOT / "build"

CHROME_MANIFEST = "manifest.json"
FIREFOX_MANIFEST = "manifest.firefox.json"
# Release artifacts use an allowlist so an editor file, local secret, or new
# developer document cannot silently enter a browser archive. A developer who
# adds a real runtime asset must make that release decision explicit here.
SHARED_FILES = (
    Path("background.js"),
    Path("settings.js"),
    Path("options.html"),
    Path("options.css"),
    Path("options.js"),
    Path("icons/icon-16.png"),
    Path("icons/icon-32.png"),
    Path("icons/icon-48.png"),
    Path("icons/icon-128.png"),
)


class BrowserTarget(NamedTuple):
    """One browser's packaging recipe.

    Attributes
    ----------
    name:
        Lower-case browser name, used on the command line and in file names.
    manifest_source:
        File in ``extension/`` that becomes the build's ``manifest.json``.
    output_dir:
        Folder the build is written to.
    """

    name: str
    manifest_source: str
    output_dir: Path


TARGETS = (
    BrowserTarget("chrome", CHROME_MANIFEST, BUILD_ROOT / "chrome-extension"),
    BrowserTarget("firefox", FIREFOX_MANIFEST, BUILD_ROOT / "firefox-extension"),
)


def collect_shared_files() -> list[Path]:
    """Return the audited extension files both browsers use.

    Returns
    -------
    list[Path]
        Allowlisted paths relative to ``extension/``.

    Raises
    ------
    FileNotFoundError
        When an allowlisted runtime file is missing.
    ValueError
        When an allowlisted file or one of its parent paths is a symbolic link.
    """
    for relative_path in SHARED_FILES:
        source_path = SOURCE_DIR / relative_path
        paths_to_check = [SOURCE_DIR]
        nested_path = SOURCE_DIR
        for path_part in relative_path.parts:
            nested_path /= path_part
            paths_to_check.append(nested_path)
        if any(path.is_symlink() for path in paths_to_check):
            raise ValueError(f"refusing to package symbolic link: {source_path}")
        if not source_path.is_file():
            raise FileNotFoundError(f"missing extension runtime file: {source_path}")
    return list(SHARED_FILES)


def manifest_version() -> str:
    """Return the shared version, refusing to build when the manifests disagree.

    Returns
    -------
    str
        The version both manifests declare.

    Raises
    ------
    ValueError
        When they differ, which would otherwise ship two archives labelled
        differently for the same code.
    """
    chrome = json.loads((SOURCE_DIR / CHROME_MANIFEST).read_text())
    firefox = json.loads((SOURCE_DIR / FIREFOX_MANIFEST).read_text())
    if chrome["version"] != firefox["version"]:
        raise ValueError(
            f"version mismatch: {CHROME_MANIFEST} says {chrome['version']!r} "
            f"and {FIREFOX_MANIFEST} says {firefox['version']!r}"
        )
    return str(chrome["version"])


def build_target(target: BrowserTarget, *, make_zip: bool) -> Path:
    """Write one browser's build, and its archive when asked.

    Parameters
    ----------
    target:
        Which browser to package.
    make_zip:
        True to also write ``build/podcast-downloader-<browser>-<version>.zip``.

    Returns
    -------
    Path
        The build directory.

    Raises
    ------
    FileNotFoundError
        When the target's manifest is missing.
    """
    manifest_file = SOURCE_DIR / target.manifest_source
    if not manifest_file.is_file():
        raise FileNotFoundError(f"missing {manifest_file}")

    version = manifest_version()

    # Start clean so a file deleted from extension/ cannot linger in a build.
    if target.output_dir.exists():
        shutil.rmtree(target.output_dir)
    target.output_dir.mkdir(parents=True)

    shared_files = collect_shared_files()
    for relative_path in shared_files:
        destination = target.output_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE_DIR / relative_path, destination)
    shutil.copy2(manifest_file, target.output_dir / CHROME_MANIFEST)

    print(f"{target.name}: {len(shared_files) + 1} files -> {target.output_dir}")

    if make_zip:
        archive_file = BUILD_ROOT / f"podcast-downloader-{target.name}-{version}.zip"
        # A release upload often selects build/*.zip. Remove older archives for
        # this browser so that glob cannot accidentally publish a stale version.
        for old_archive in BUILD_ROOT.glob(f"podcast-downloader-{target.name}-*.zip"):
            old_archive.unlink()
        with zipfile.ZipFile(archive_file, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(target.output_dir.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(target.output_dir))
        print(f"{target.name}: archive -> {archive_file}")

    return target.output_dir


def main() -> None:
    """Parse arguments and package the requested browsers."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--browser",
        choices=[target.name for target in TARGETS],
        help="package only this browser (default: both)",
    )
    parser.add_argument(
        "--zip",
        action="store_true",
        dest="make_zip",
        help="also write the archives, for a release or for add-on signing",
    )
    arguments = parser.parse_args()

    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    for target in TARGETS:
        if arguments.browser in (None, target.name):
            build_target(target, make_zip=arguments.make_zip)


if __name__ == "__main__":
    main()
