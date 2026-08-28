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
    SHARED_FILES,
    SOURCE_DIR,
    TARGETS,
    build_target,
    collect_shared_files,
    manifest_version,
)

TARGETS_BY_NAME = {target.name: target for target in TARGETS}
FIREFOX_MINIMUM_VERSION = 140
FIREFOX_REQUIRED_DATA = {
    "authenticationInfo",
    "browsingActivity",
    "websiteContent",
}


def test_the_two_manifests_agree_on_the_version() -> None:
    """One codebase must not ship as two different version numbers."""
    assert manifest_version()


def test_the_firefox_manifest_matches_what_firefox_needs() -> None:
    """Firefox needs an event page, stable ID, and honest data declaration."""
    firefox = json.loads((SOURCE_DIR / FIREFOX_MANIFEST).read_text())
    gecko_settings = firefox["browser_specific_settings"]["gecko"]

    assert firefox["background"] == {"scripts": ["background.js"], "type": "module"}
    assert "service_worker" not in firefox["background"]
    assert gecko_settings["id"]
    assert int(gecko_settings["strict_min_version"].split(".")[0]) >= (
        FIREFOX_MINIMUM_VERSION
    )
    assert set(gecko_settings["data_collection_permissions"]["required"]) == (
        FIREFOX_REQUIRED_DATA
    )
    assert (
        int(
            firefox["browser_specific_settings"]["gecko_android"][
                "strict_min_version"
            ].split(".")[0]
        )
        >= 142
    )
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
    """Only the audited runtime allowlist should enter a browser build."""
    shared_files = set(collect_shared_files())
    shared_names = {path.name for path in shared_files}

    assert shared_files == set(SHARED_FILES)
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


def test_the_archive_is_named_for_its_browser_and_version() -> None:
    """A downloaded file should say which build it is without being opened."""
    target = TARGETS_BY_NAME["chrome"]
    build_target(target, make_zip=True)
    archive_file = BUILD_ROOT / (
        f"podcast-downloader-chrome-{manifest_version()}.zip"
    )

    assert archive_file.is_file()
    with zipfile.ZipFile(archive_file) as archive:
        names = set(archive.namelist())

    # The manifest must sit at the archive root, not inside a wrapper folder,
    # or the browser will not recognise the unzipped result as an extension.
    assert CHROME_MANIFEST in names
    assert "background.js" in names
    assert "icons/icon-128.png" in names


def test_firefox_ships_no_archive() -> None:
    """An unsigned Firefox zip is a file people download and cannot install.

    Firefox refuses any add-on Mozilla has not signed, reporting it as corrupt.
    Publishing one next to the signed ``.xpi`` only invites the wrong download,
    so ``--zip`` must not produce it even when asked.
    """
    target = TARGETS_BY_NAME["firefox"]
    stale_archive = BUILD_ROOT / (
        f"podcast-downloader-firefox-{manifest_version()}.zip"
    )
    stale_archive.write_bytes(b"left over from an older build")

    build_target(target, make_zip=True)

    assert not stale_archive.exists()
    assert not list(BUILD_ROOT.glob("podcast-downloader-firefox-*.zip"))


def test_building_without_an_archive_keeps_the_chrome_archive() -> None:
    """``--sign`` rebuilds both folders, and must not delete the release zip.

    Signing runs the ordinary build first with ``make_zip=False``. If that pass
    cleared Chrome's archive, a ``--zip`` then ``--sign`` sequence would leave
    nothing for Chrome users to download.
    """
    chrome_target = TARGETS_BY_NAME["chrome"]
    build_target(chrome_target, make_zip=True)
    archive_file = BUILD_ROOT / (
        f"podcast-downloader-chrome-{manifest_version()}.zip"
    )
    assert archive_file.is_file()

    build_target(chrome_target, make_zip=False)

    assert archive_file.is_file()


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


def test_build_refuses_an_allowlisted_symbolic_link(monkeypatch, tmp_path) -> None:
    """A release file must not point outside the reviewed extension tree."""
    import scripts.build_extensions as build_module

    source = tmp_path / "extension"
    source.mkdir()
    outside_file = tmp_path / "private.txt"
    outside_file.write_text("secret", encoding="utf-8")
    (source / SHARED_FILES[0]).symlink_to(outside_file)
    monkeypatch.setattr(build_module, "SOURCE_DIR", source)

    with pytest.raises(ValueError, match="symbolic link"):
        build_module.collect_shared_files()


def test_build_removes_old_archives_for_the_same_browser() -> None:
    """A release glob must not pick up an archive from an earlier version."""
    target = TARGETS_BY_NAME["chrome"]
    old_archive = BUILD_ROOT / "podcast-downloader-chrome-0.0.1.zip"
    old_archive.parent.mkdir(parents=True, exist_ok=True)
    old_archive.write_bytes(b"stale")

    build_target(target, make_zip=True)

    assert not old_archive.exists()


def test_signing_needs_credentials_and_says_where_to_get_them(
    monkeypatch, tmp_path
) -> None:
    """The error must lead somewhere, not just report a missing variable."""
    import scripts.build_extensions as build_module

    monkeypatch.delenv(build_module.AMO_KEY_NAME, raising=False)
    monkeypatch.delenv(build_module.AMO_SECRET_NAME, raising=False)
    monkeypatch.setattr(
        build_module, "AMO_CREDENTIALS_FILE", tmp_path / ".amo-credentials"
    )

    with pytest.raises(ValueError, match="addons.mozilla.org"):
        build_module.read_amo_credentials()


def test_signing_reads_a_credentials_file(monkeypatch, tmp_path) -> None:
    """Typing two long secrets on every run would not survive contact with use."""
    import scripts.build_extensions as build_module

    monkeypatch.delenv(build_module.AMO_KEY_NAME, raising=False)
    monkeypatch.delenv(build_module.AMO_SECRET_NAME, raising=False)
    credentials_file = tmp_path / ".amo-credentials"
    credentials_file.write_text(
        f"# Mozilla signing key\n"
        f"{build_module.AMO_KEY_NAME}=user:12345:67\n"
        f"{build_module.AMO_SECRET_NAME}=abcdef0123456789\n"
    )
    credentials_file.chmod(0o600)
    monkeypatch.setattr(build_module, "AMO_CREDENTIALS_FILE", credentials_file)

    assert build_module.read_amo_credentials() == (
        "user:12345:67",
        "abcdef0123456789",
    )


def test_signing_refuses_a_world_readable_credentials_file(
    monkeypatch, tmp_path
) -> None:
    """A signing key anyone on the machine can read is a key worth refusing."""
    import scripts.build_extensions as build_module

    monkeypatch.delenv(build_module.AMO_KEY_NAME, raising=False)
    monkeypatch.delenv(build_module.AMO_SECRET_NAME, raising=False)
    credentials_file = tmp_path / ".amo-credentials"
    credentials_file.write_text(
        f"{build_module.AMO_KEY_NAME}=k\n{build_module.AMO_SECRET_NAME}=s\n"
    )
    credentials_file.chmod(0o644)
    monkeypatch.setattr(build_module, "AMO_CREDENTIALS_FILE", credentials_file)

    with pytest.raises(ValueError, match="chmod 600"):
        build_module.read_amo_credentials()


def test_the_environment_wins_over_the_credentials_file(
    monkeypatch, tmp_path
) -> None:
    """A CI job supplies credentials by environment; that must not be overridden."""
    import scripts.build_extensions as build_module

    credentials_file = tmp_path / ".amo-credentials"
    credentials_file.write_text(
        f"{build_module.AMO_KEY_NAME}=from-file\n"
        f"{build_module.AMO_SECRET_NAME}=from-file\n"
    )
    credentials_file.chmod(0o600)
    monkeypatch.setattr(build_module, "AMO_CREDENTIALS_FILE", credentials_file)
    monkeypatch.setenv(build_module.AMO_KEY_NAME, "from-environment")
    monkeypatch.setenv(build_module.AMO_SECRET_NAME, "from-environment")

    assert build_module.read_amo_credentials() == (
        "from-environment",
        "from-environment",
    )


def test_signing_keeps_the_secret_out_of_the_command_line(monkeypatch) -> None:
    """Every process on the machine can read another's arguments from /proc.

    web-ext accepts the key either way, so it must be passed by environment.
    """
    import scripts.build_extensions as build_module

    build_target(TARGETS_BY_NAME["firefox"], make_zip=False)
    monkeypatch.setenv(build_module.AMO_KEY_NAME, "secret-key-value")
    monkeypatch.setenv(build_module.AMO_SECRET_NAME, "secret-secret-value")
    recorded: dict = {}

    def fake_runner(command, env=None, check=False):
        recorded["command"] = command
        recorded["env"] = env
        return None

    build_module.sign_firefox_build(runner=fake_runner, environment={})

    joined_command = " ".join(recorded["command"])
    assert "secret-key-value" not in joined_command
    assert "secret-secret-value" not in joined_command
    assert recorded["env"]["WEB_EXT_API_KEY"] == "secret-key-value"
    assert recorded["env"]["WEB_EXT_API_SECRET"] == "secret-secret-value"


def test_signing_uses_the_unlisted_channel_and_the_firefox_build(
    monkeypatch,
) -> None:
    """Listed would publish it publicly; the Chrome build would be rejected."""
    import scripts.build_extensions as build_module

    firefox_target = TARGETS_BY_NAME["firefox"]
    build_target(firefox_target, make_zip=False)
    monkeypatch.setenv(build_module.AMO_KEY_NAME, "k")
    monkeypatch.setenv(build_module.AMO_SECRET_NAME, "s")

    command = build_module.sign_firefox_build(
        runner=lambda *args, **kwargs: None, environment={}
    )

    assert f"--channel={build_module.AMO_CHANNEL}" in command
    assert build_module.AMO_CHANNEL == "unlisted"
    assert f"--source-dir={firefox_target.output_dir}" in command


def test_signing_refuses_when_the_firefox_build_is_missing(
    monkeypatch, tmp_path
) -> None:
    """Signing whatever happened to be lying around would be worse than failing."""
    import scripts.build_extensions as build_module

    monkeypatch.setenv(build_module.AMO_KEY_NAME, "k")
    monkeypatch.setenv(build_module.AMO_SECRET_NAME, "s")
    missing_target = build_module.BrowserTarget(
        "firefox", build_module.FIREFOX_MANIFEST, tmp_path / "absent", False
    )
    monkeypatch.setattr(build_module, "TARGETS", (missing_target,))

    with pytest.raises(FileNotFoundError, match="no Firefox build"):
        build_module.sign_firefox_build(runner=lambda *a, **k: None)


def test_the_signed_addon_is_renamed_to_something_readable(
    monkeypatch, tmp_path
) -> None:
    """web-ext names its output after Mozilla's internal identifier.

    That produces files like ``b35db559615e438998be-1.1.1.xpi``, which is the
    file a person is asked to double-click. It should say what it is.

    This runs against a temporary directory on purpose: an earlier version
    cleared ``*.xpi`` out of the real build folder and destroyed a signed
    add-on that had already cost a round trip to Mozilla.
    """
    import scripts.build_extensions as build_module

    monkeypatch.setattr(build_module, "BUILD_ROOT", tmp_path)
    opaque_file = tmp_path / "b35db559615e438998be-1.1.1.xpi"
    opaque_file.write_bytes(b"signed add-on")

    renamed = build_module.rename_signed_addon()

    assert renamed is not None
    assert renamed.parent == tmp_path
    assert renamed.name == (
        f"podcast-downloader-firefox-{build_module.manifest_version()}.xpi"
    )
    assert not opaque_file.exists()
    assert renamed.read_bytes() == b"signed add-on"


def test_renaming_reports_nothing_when_signing_produced_no_file(
    monkeypatch, tmp_path
) -> None:
    """A silent success with no add-on would be worse than saying so."""
    import scripts.build_extensions as build_module

    monkeypatch.setattr(build_module, "BUILD_ROOT", tmp_path)

    assert build_module.rename_signed_addon() is None


def test_renaming_keeps_the_newest_of_several_signed_files(
    monkeypatch, tmp_path
) -> None:
    """An earlier signing run can leave a stale add-on in the folder."""
    import os

    import scripts.build_extensions as build_module

    monkeypatch.setattr(build_module, "BUILD_ROOT", tmp_path)
    older_file = tmp_path / "aaa-1.1.0.xpi"
    older_file.write_bytes(b"stale")
    os.utime(older_file, (1_000_000, 1_000_000))
    newer_file = tmp_path / "bbb-1.1.1.xpi"
    newer_file.write_bytes(b"fresh")
    os.utime(newer_file, (2_000_000, 2_000_000))

    renamed = build_module.rename_signed_addon()

    assert renamed is not None
    assert renamed.read_bytes() == b"fresh"
