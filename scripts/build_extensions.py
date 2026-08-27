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
    uv run python scripts/build_extensions.py --sign     # signed Firefox .xpi

Archives are named with the manifest version, so a downloaded file says which
build it is.

``--sign`` exists because Firefox will not permanently install an add-on that
Mozilla has not signed; it rejects one with the misleading message "this add-on
appears to be corrupt". Signing on the unlisted channel returns a normal
``.xpi`` that installs in one click and stays installed, without listing the
add-on in the public directory. It needs an API key from
https://addons.mozilla.org/developers/addon/api/key/ and Node, for ``npx``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import zipfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = PROJECT_ROOT / "extension"
BUILD_ROOT = PROJECT_ROOT / "build"

CHROME_MANIFEST = "manifest.json"
FIREFOX_MANIFEST = "manifest.firefox.json"

# Signing credentials. Mozilla issues these at
# https://addons.mozilla.org/developers/addon/api/key/ and they are as
# sensitive as a password: anyone holding them can publish add-ons as you.
AMO_KEY_NAME = "AMO_API_KEY"
AMO_SECRET_NAME = "AMO_API_SECRET"
AMO_CREDENTIALS_FILE = PROJECT_ROOT / ".amo-credentials"
# Refuse a credentials file that anyone else on the machine can read.
AMO_CREDENTIALS_MAX_MODE = 0o600
# "unlisted" means Mozilla signs the add-on and returns it without publishing
# it: nobody can search for or install it, and the review is automated.
AMO_CHANNEL = "unlisted"
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


def read_amo_credentials() -> tuple[str, str]:
    """Return the Mozilla API key and secret used for signing.

    The environment wins, which is how a CI job would supply them. Otherwise
    they come from ``.amo-credentials`` in the project root, a two-line
    ``KEY=VALUE`` file that is ignored by git and by the Docker build.

    Returns
    -------
    tuple[str, str]
        ``(api key, api secret)``.

    Raises
    ------
    ValueError
        When either value is missing, or when the credentials file is readable
        by anyone other than its owner.
    """
    api_key = os.environ.get(AMO_KEY_NAME, "").strip()
    api_secret = os.environ.get(AMO_SECRET_NAME, "").strip()

    if (not api_key or not api_secret) and AMO_CREDENTIALS_FILE.is_file():
        file_mode = stat.S_IMODE(AMO_CREDENTIALS_FILE.stat().st_mode)
        if file_mode & ~AMO_CREDENTIALS_MAX_MODE:
            raise ValueError(
                f"{AMO_CREDENTIALS_FILE} is mode {file_mode:04o}; anyone on this "
                f"machine can read your signing key. Run: chmod 600 "
                f"{AMO_CREDENTIALS_FILE}"
            )
        for line in AMO_CREDENTIALS_FILE.read_text(encoding="utf-8").splitlines():
            stripped_line = line.strip()
            if not stripped_line or stripped_line.startswith("#"):
                continue
            name, separator, value = stripped_line.partition("=")
            if not separator:
                continue
            if name.strip() == AMO_KEY_NAME and not api_key:
                api_key = value.strip()
            elif name.strip() == AMO_SECRET_NAME and not api_secret:
                api_secret = value.strip()

    if not api_key or not api_secret:
        raise ValueError(
            f"Signing needs {AMO_KEY_NAME} and {AMO_SECRET_NAME}. Create them at "
            "https://addons.mozilla.org/developers/addon/api/key/ , then either "
            f"export both, or put them in {AMO_CREDENTIALS_FILE} as two "
            "KEY=VALUE lines and chmod 600 it."
        )

    return api_key, api_secret


def sign_firefox_build(
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    environment: Mapping[str, str] | None = None,
) -> Sequence[str]:
    """Ask Mozilla to sign the Firefox build and return the command used.

    Parameters
    ----------
    runner:
        Callable with ``subprocess.run``'s interface. Tests replace it so the
        command can be checked without contacting Mozilla.
    environment:
        Base environment for the subprocess, defaulting to this process's.

    Returns
    -------
    Sequence[str]
        The command that was run, for logging and for tests.

    Raises
    ------
    ValueError
        When the credentials are missing or badly protected.
    FileNotFoundError
        When the Firefox build is absent, or ``npx`` is not installed.
    subprocess.CalledProcessError
        When signing fails. Mozilla's validator messages appear in the output.
    """
    api_key, api_secret = read_amo_credentials()

    firefox_target = next(
        target for target in TARGETS if target.name == "firefox"
    )
    if not (firefox_target.output_dir / CHROME_MANIFEST).is_file():
        raise FileNotFoundError(
            f"no Firefox build at {firefox_target.output_dir}; run this script "
            "without --sign first"
        )

    if shutil.which("npx") is None:
        raise FileNotFoundError(
            "npx not found. Signing uses Mozilla's web-ext tool, which needs "
            "Node installed."
        )

    command = [
        "npx",
        "--yes",
        "web-ext@latest",
        "sign",
        f"--source-dir={firefox_target.output_dir}",
        f"--artifacts-dir={BUILD_ROOT}",
        f"--channel={AMO_CHANNEL}",
    ]

    # The key and secret travel in the environment rather than in the command,
    # because every process on the machine can read another process's arguments
    # from /proc. web-ext reads any option from a matching WEB_EXT_ variable.
    signing_environment = dict(
        os.environ if environment is None else environment
    )
    signing_environment["WEB_EXT_API_KEY"] = api_key
    signing_environment["WEB_EXT_API_SECRET"] = api_secret

    print(f"firefox: signing on the {AMO_CHANNEL} channel, this takes a minute")
    runner(command, env=signing_environment, check=True)

    signed_files = sorted(BUILD_ROOT.glob("*.xpi"))
    for signed_file in signed_files:
        print(f"firefox: signed add-on -> {signed_file}")
    if not signed_files:
        print("firefox: signing reported success but wrote no .xpi")

    return command


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
    parser.add_argument(
        "--sign",
        action="store_true",
        dest="sign",
        help=(
            "have Mozilla sign the Firefox build, producing an .xpi that "
            "installs in one click and survives a restart"
        ),
    )
    arguments = parser.parse_args()

    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    for target in TARGETS:
        if arguments.browser in (None, target.name):
            build_target(target, make_zip=arguments.make_zip)

    if arguments.sign:
        sign_firefox_build()


if __name__ == "__main__":
    main()
