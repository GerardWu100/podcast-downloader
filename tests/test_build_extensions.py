"""Tests for the extension packaging script.

``extension/`` is the single source for both browsers. These tests guard the
two ways that could quietly go wrong: a file missing from one browser's build,
and the two manifests drifting apart so the same code ships under different
versions or different permissions.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from scripts.build_extensions import (
    BUILD_ROOT,
    CHROME_MANIFEST,
    FIREFOX_MANIFEST,
    SOURCE_DIR,
    TARGETS,
    build_target,
    collect_shared_files,
    manifest_version,
)

TARGETS_BY_NAME = {target.name: target for target in TARGETS}


def test_the_two_manifests_agree_on_the_version() -> None:
    """One codebase must not ship as two different version numbers."""
    assert manifest_version()


def test_the_firefox_manifest_matches_what_firefox_needs() -> None:
    """Firefox has no extension service worker and wants a stable add-on id."""
    firefox = json.loads((SOURCE_DIR / FIREFOX_MANIFEST).read_text())

    assert firefox["background"] == {"scripts": ["background.js"], "type": "module"}
    assert "service_worker" not in firefox["background"]
    assert firefox["browser_specific_settings"]["gecko"]["id"]
    assert "options_ui" in firefox
    assert "options_page" not in firefox


def test_the_two_manifests_request_the_same_permissions() -> None:
    """Whatever one browser is trusted with, the other must be trusted with too.

    A permission added to one manifest and forgotten in the other is the kind of
    difference nobody notices until the extension silently fails in one browser.
    """
    chrome = json.loads((SOURCE_DIR / CHROME_MANIFEST).read_text())
    firefox = json.loads((SOURCE_DIR / FIREFOX_MANIFEST).read_text())

    assert sorted(chrome["permissions"]) == sorted(firefox["permissions"])
    assert sorted(chrome["optional_host_permissions"]) == sorted(
        firefox["optional_host_permissions"]
    )


def test_shared_files_exclude_the_manifests_and_the_guide() -> None:
    """No build should ship a second manifest or the developer guide."""
    shared_names = {path.name for path in collect_shared_files()}

    assert CHROME_MANIFEST not in shared_names
    assert FIREFOX_MANIFEST not in shared_names
    assert "GUIDE_extension.md" not in shared_names
    assert {"background.js", "settings.js", "options.html", "options.js"} <= (
        shared_names
    )


@pytest.mark.parametrize("browser", sorted(TARGETS_BY_NAME))
def test_each_build_is_loadable_on_its_own(browser: str) -> None:
    """Every shared file plus that browser's manifest, and nothing else."""
    target = TARGETS_BY_NAME[browser]
    build_target(target, make_zip=False)

    built_files = {
        path.relative_to(target.output_dir)
        for path in target.output_dir.rglob("*")
        if path.is_file()
    }

    assert built_files == set(collect_shared_files()) | {Path(CHROME_MANIFEST)}


def test_each_build_carries_the_manifest_its_browser_needs() -> None:
    """Swapping the two manifests would produce builds neither browser can load."""
    for browser, expected_key in (("chrome", "service_worker"), ("firefox", "scripts")):
        target = TARGETS_BY_NAME[browser]
        build_target(target, make_zip=False)
        manifest = json.loads((target.output_dir / CHROME_MANIFEST).read_text())

        assert expected_key in manifest["background"]


def test_build_removes_files_that_no_longer_exist_in_the_source() -> None:
    """A stale file left over from an earlier build would ship to users."""
    target = TARGETS_BY_NAME["firefox"]
    build_target(target, make_zip=False)
    leftover = target.output_dir / "deleted-last-time.js"
    leftover.write_text("// removed from extension/ since the last build")

    build_target(target, make_zip=False)

    assert not leftover.exists()


@pytest.mark.parametrize("browser", sorted(TARGETS_BY_NAME))
def test_the_archive_is_named_for_its_browser_and_version(browser: str) -> None:
    """A downloaded file should say which build it is without being opened."""
    target = TARGETS_BY_NAME[browser]
    build_target(target, make_zip=True)
    archive_file = BUILD_ROOT / (
        f"podcast-downloader-{browser}-{manifest_version()}.zip"
    )

    assert archive_file.is_file()
    with zipfile.ZipFile(archive_file) as archive:
        names = set(archive.namelist())

    # The manifest must sit at the archive root, not inside a wrapper folder,
    # or the browser will not recognise the unzipped result as an extension.
    assert CHROME_MANIFEST in names
    assert "background.js" in names
    assert "icons/icon-128.png" in names


def test_build_refuses_a_version_mismatch(monkeypatch, tmp_path) -> None:
    """Catching the drift at build time beats shipping two different versions."""
    import scripts.build_extensions as build_module

    source = tmp_path / "extension"
    source.mkdir()
    (source / CHROME_MANIFEST).write_text(json.dumps({"version": "1.1.0"}))
    (source / FIREFOX_MANIFEST).write_text(json.dumps({"version": "1.0.0"}))
    monkeypatch.setattr(build_module, "SOURCE_DIR", source)

    with pytest.raises(ValueError, match="version mismatch"):
        build_module.manifest_version()
