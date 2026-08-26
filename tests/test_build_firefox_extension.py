"""Tests for the Firefox extension build.

Chrome loads ``extension/`` directly; Firefox needs the same files with a
different manifest. The build script exists so that difference never becomes a
second copy of the JavaScript, and these tests guard the two ways that could
quietly go wrong: a file missing from the Firefox build, and the two manifests
drifting to different version numbers.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from scripts.build_firefox_extension import (
    BUILD_DIR,
    CHROME_MANIFEST,
    FIREFOX_MANIFEST,
    SOURCE_DIR,
    ZIP_FILE,
    build,
    collect_shared_files,
)


def test_the_two_manifests_agree_on_the_version() -> None:
    """A Firefox build labelled differently from Chrome's would confuse everyone."""
    chrome = json.loads((SOURCE_DIR / CHROME_MANIFEST).read_text())
    firefox = json.loads((SOURCE_DIR / FIREFOX_MANIFEST).read_text())

    assert chrome["version"] == firefox["version"]


def test_the_firefox_manifest_matches_what_firefox_needs() -> None:
    """Firefox has no extension service worker and wants a stable add-on id."""
    firefox = json.loads((SOURCE_DIR / FIREFOX_MANIFEST).read_text())

    assert firefox["background"] == {
        "scripts": ["background.js"],
        "type": "module",
    }
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
    """The build must not ship a second manifest or the developer guide."""
    shared_names = {path.name for path in collect_shared_files()}

    assert CHROME_MANIFEST not in shared_names
    assert FIREFOX_MANIFEST not in shared_names
    assert "GUIDE_extension.md" not in shared_names
    # The files the extension actually needs are all there.
    assert {"background.js", "settings.js", "options.html", "options.js"} <= (
        shared_names
    )


def test_build_copies_every_shared_file_and_the_firefox_manifest() -> None:
    """The built folder must be loadable on its own."""
    build(make_zip=False)

    built_files = {
        path.relative_to(BUILD_DIR) for path in BUILD_DIR.rglob("*") if path.is_file()
    }
    expected = set(collect_shared_files()) | {Path(CHROME_MANIFEST)}

    assert built_files == expected
    built_manifest = json.loads((BUILD_DIR / CHROME_MANIFEST).read_text())
    assert built_manifest["background"]["scripts"] == ["background.js"]


def test_build_removes_files_that_no_longer_exist_in_the_source() -> None:
    """A stale file left over from an earlier build would ship to Firefox."""
    build(make_zip=False)
    leftover = BUILD_DIR / "deleted-last-time.js"
    leftover.write_text("// removed from extension/ since the last build")

    build(make_zip=False)

    assert not leftover.exists()


def test_build_with_zip_writes_a_loadable_archive() -> None:
    """The archive is what addons.mozilla.org signs, so its manifest must be inside."""
    build(make_zip=True)

    with zipfile.ZipFile(ZIP_FILE) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read(CHROME_MANIFEST))

    assert "background.js" in names
    assert "icons/icon-128.png" in names
    assert manifest["browser_specific_settings"]["gecko"]["id"]


def test_build_refuses_a_version_mismatch(monkeypatch, tmp_path) -> None:
    """Catching the drift at build time beats shipping two different versions."""
    import scripts.build_firefox_extension as build_module

    source = tmp_path / "extension"
    source.mkdir()
    (source / "background.js").write_text("// shared")
    (source / CHROME_MANIFEST).write_text(json.dumps({"version": "1.1.0"}))
    (source / FIREFOX_MANIFEST).write_text(json.dumps({"version": "1.0.0"}))
    monkeypatch.setattr(build_module, "SOURCE_DIR", source)
    monkeypatch.setattr(build_module, "BUILD_DIR", tmp_path / "build")

    with pytest.raises(ValueError, match="version mismatch"):
        build_module.build(make_zip=False)
