"""Regression tests for strict runtime configuration validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from src.config import ConfigError, load_config


def write_config(config_file: Path, body: str) -> None:
    """Write a minimal config file for one validation case.

    Parameters
    ----------
    config_file:
        Temporary ``config.ini`` path used by the test.
    body:
        Lines that belong inside the ``[podcast]`` section.
    """
    config_file.write_text(f"[podcast]\n{body}\n", encoding="utf-8")


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("channel_count", "0", "channel_count must be at least 1"),
        ("channel_count", "-1", "channel_count must be at least 1"),
        (
            "min_channel_video_age_hours",
            "-1",
            "min_channel_video_age_hours must be at least 0",
        ),
        ("delay_seconds", "-0.1", "delay_seconds must be at least 0"),
        ("retention_days", "0", "retention_days must be at least 1"),
        ("retention_days", "-1", "retention_days must be at least 1"),
    ],
)
def test_load_config_rejects_out_of_range_numeric_values(
    tmp_path: Path,
    key: str,
    value: str,
    message: str,
) -> None:
    """Numeric config values should fail fast when outside accepted ranges."""
    config_file = tmp_path / "config.ini"
    write_config(config_file, f"{key} = {value}")

    with pytest.raises(ConfigError, match=message):
        load_config(config_file, tmp_path)


@pytest.mark.parametrize(
    "key",
    [
        "urls_file",
        "output_dir",
        "intermediate_dir",
        "log_file",
        "downloaded_urls_file",
        "bypass_age_check_file",
        "cookies_file",
    ],
)
def test_load_config_rejects_blank_path_values(tmp_path: Path, key: str) -> None:
    """Configured path strings should not collapse to the project directory."""
    config_file = tmp_path / "config.ini"
    write_config(config_file, f"{key} =    ")

    with pytest.raises(ConfigError, match=f"{key} must not be blank"):
        load_config(config_file, tmp_path)


def test_load_config_rejects_blank_download_directory_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Docker download-directory override should not be blank."""
    config_file = tmp_path / "config.ini"
    write_config(config_file, "channel_count = 1")
    monkeypatch.setenv("PODCAST_DOWNLOAD_DIR", "   ")

    with pytest.raises(ConfigError, match="PODCAST_DOWNLOAD_DIR must not be blank"):
        load_config(config_file, tmp_path)


def test_load_config_rejects_blank_intermediate_directory_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Docker intermediate-directory override should not be blank."""
    config_file = tmp_path / "config.ini"
    write_config(config_file, "channel_count = 1")
    monkeypatch.setenv("PODCAST_INTERMEDIATE_DIR", "   ")

    with pytest.raises(
        ConfigError,
        match="PODCAST_INTERMEDIATE_DIR must not be blank",
    ):
        load_config(config_file, tmp_path)


def test_load_config_defaults_intermediate_dir_to_download_work(tmp_path: Path) -> None:
    """Local runs should keep scratch files out of the library folder by default."""
    config_file = tmp_path / "config.ini"
    write_config(config_file, "channel_count = 1")

    config = load_config(config_file, tmp_path)

    assert config.intermediate_dir == tmp_path / "download_work"


def test_load_config_defaults_channel_count_to_two(tmp_path: Path) -> None:
    """The built-in polling depth should match the checked-in operating default."""
    config_file = tmp_path / "config.ini"
    write_config(config_file, "")

    config = load_config(config_file, tmp_path)

    assert config.channel_count == 2


def test_load_config_defaults_retention_to_thirty_days(tmp_path: Path) -> None:
    """The built-in retention window should match the checked-in operating default."""
    config_file = tmp_path / "config.ini"
    write_config(config_file, "channel_count = 1")

    config = load_config(config_file, tmp_path)

    assert config.retention_days == 30


def test_load_config_defaults_always_use_cookies_to_true(tmp_path: Path) -> None:
    """YouTube cookies should default to always-on mode with alternate fallback."""
    config_file = tmp_path / "config.ini"
    write_config(config_file, "channel_count = 1")

    config = load_config(config_file, tmp_path)

    assert config.always_use_cookies is True


def test_load_config_reads_always_use_cookies(tmp_path: Path) -> None:
    """The cookie strategy toggle should accept standard yes/no config values."""
    config_file = tmp_path / "config.ini"
    write_config(config_file, "channel_count = 1\nalways_use_cookies = yes")

    config = load_config(config_file, tmp_path)

    assert config.always_use_cookies is True
