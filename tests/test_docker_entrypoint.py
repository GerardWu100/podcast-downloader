"""Integration-style checks for the Docker entrypoint bootstrap behavior."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from src.passwords import (
    DEFAULT_UI_PASSWORD,
    hash_password,
    is_password_hash,
    verify_password,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_compose_uses_separate_temporary_download_volume() -> None:
    """Compose should keep scratch work outside the podcast library mount."""
    compose_file = PROJECT_ROOT / "docker-compose.yml"

    compose_text = compose_file.read_text(encoding="utf-8")

    assert "PODCAST_INTERMEDIATE_DIR=/temporary" in compose_text
    assert "$HOME/downloads/temporary:/temporary" in compose_text


def _run_entrypoint(
    data_dir: Path, download_dir: Path
) -> subprocess.CompletedProcess[str]:
    """Run the Docker entrypoint against temporary directories."""
    env = os.environ.copy()
    env["PODCAST_DATA_DIR"] = str(data_dir)
    env["PODCAST_DOWNLOAD_DIR"] = str(download_dir)
    env["YT_DLP_AUTO_UPDATE"] = "false"
    return subprocess.run(
        [
            "sh",
            str(PROJECT_ROOT / "docker-entrypoint.sh"),
            sys.executable,
            "-c",
            "pass",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_entrypoint_seeds_default_password_hash(tmp_path: Path) -> None:
    """First boot should create a hashed default password in the mounted data directory."""
    data_dir = tmp_path / "data"
    download_dir = tmp_path / "downloads"
    repo_password_file = PROJECT_ROOT / ".ui_password"
    original_contents = (
        repo_password_file.read_text(encoding="utf-8")
        if repo_password_file.exists()
        else None
    )

    try:
        repo_password_file.unlink(missing_ok=True)

        result = _run_entrypoint(data_dir, download_dir)

        assert result.returncode == 0, result.stderr
        stored_value = (data_dir / ".ui_password").read_text(encoding="utf-8").strip()
        assert is_password_hash(stored_value) is True
        assert verify_password(DEFAULT_UI_PASSWORD, stored_value) is True
    finally:
        if original_contents is not None:
            repo_password_file.write_text(original_contents, encoding="utf-8")


def test_entrypoint_rewrites_plaintext_password_as_hash(tmp_path: Path) -> None:
    """A legacy plain-text password file should be migrated to a hash in place."""
    data_dir = tmp_path / "data"
    download_dir = tmp_path / "downloads"
    data_dir.mkdir()
    (data_dir / ".ui_password").write_text("custom-password\n", encoding="utf-8")

    result = _run_entrypoint(data_dir, download_dir)

    assert result.returncode == 0, result.stderr
    stored_value = (data_dir / ".ui_password").read_text(encoding="utf-8").strip()
    assert stored_value != "custom-password"
    assert is_password_hash(stored_value) is True
    assert verify_password("custom-password", stored_value) is True


def test_entrypoint_prefers_image_bundled_hash_when_data_password_missing(
    tmp_path: Path,
) -> None:
    """A repo-root .ui_password copied into the image should seed the mounted data dir."""
    data_dir = tmp_path / "data"
    download_dir = tmp_path / "downloads"
    repo_password_file = PROJECT_ROOT / ".ui_password"
    original_contents = (
        repo_password_file.read_text(encoding="utf-8")
        if repo_password_file.exists()
        else None
    )

    try:
        bundled_hash = hash_password("server-password", salt=b"fedcba9876543210")
        repo_password_file.write_text(f"{bundled_hash}\n", encoding="utf-8")

        result = _run_entrypoint(data_dir, download_dir)

        assert result.returncode == 0, result.stderr
        stored_value = (data_dir / ".ui_password").read_text(encoding="utf-8").strip()
        assert stored_value == bundled_hash
        assert verify_password("server-password", stored_value) is True
    finally:
        if original_contents is None:
            repo_password_file.unlink(missing_ok=True)
        else:
            repo_password_file.write_text(original_contents, encoding="utf-8")
