"""Behavioral tests for CLI-only queue mutation paths."""

from __future__ import annotations

import subprocess
import sys

import src.cli as cli_module
from src.config import PodcastConfig
from src.state.bypass_store import BypassStore
from src.state.queue_store import QueueStore


def test_cli_skip_age_check_help_names_direct_youtube_urls(tmp_path) -> None:
    """The public CLI help should not imply non-YouTube URLs use the age gate."""
    parser = cli_module.build_parser(
        default_urls_file=tmp_path / "urls.txt",
        default_output_dir=tmp_path / "downloads",
        default_channel_count=1,
    )

    help_text = " ".join(parser.format_help().split())

    assert "mark direct YouTube video URLs for an age-gate bypass" in help_text
    assert "mark direct media URLs for an age-gate bypass" not in help_text


def test_cli_skip_age_check_marks_added_url_for_bypass(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The CLI should expose the same direct-video bypass path as the web UI."""
    queue_file = tmp_path / "urls.txt"
    bypass_file = tmp_path / "bypass_age_check_urls.txt"
    config = PodcastConfig(
        urls_file=queue_file,
        output_dir=tmp_path / "downloads",
        intermediate_dir=tmp_path / "download_work",
        channel_count=1,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
        min_channel_video_age_hours=24,
        delay_seconds=2.0,
        retention_days=90,
        trust_x_forwarded_for=False,
        cookies_file=None,
        always_use_cookies=False,
        bypass_age_check_file=bypass_file,
    )

    monkeypatch.setattr(cli_module, "load_config", lambda *args, **kwargs: config)
    monkeypatch.setattr(
        cli_module.sys,
        "argv",
        [
            "main.py",
            "--add-url",
            "https://youtu.be/abc123",
            "--skip-age-check",
        ],
    )

    result = cli_module.main()

    assert result == 0
    assert QueueStore(queue_file, cli_module._logger).read_urls() == [
        "https://www.youtube.com/watch?v=abc123"
    ]
    assert BypassStore(bypass_file, cli_module._logger).load() == {
        "https://www.youtube.com/watch?v=abc123"
    }
    assert "Added 1 URL(s)" in capsys.readouterr().out


def test_cli_skip_age_check_does_not_mark_non_youtube_url_for_bypass(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The CLI bypass file should contain only direct YouTube video URLs."""
    queue_file = tmp_path / "urls.txt"
    bypass_file = tmp_path / "bypass_age_check_urls.txt"
    config = PodcastConfig(
        urls_file=queue_file,
        output_dir=tmp_path / "downloads",
        intermediate_dir=tmp_path / "download_work",
        channel_count=1,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
        min_channel_video_age_hours=24,
        delay_seconds=2.0,
        retention_days=90,
        trust_x_forwarded_for=False,
        cookies_file=None,
        always_use_cookies=False,
        bypass_age_check_file=bypass_file,
    )

    monkeypatch.setattr(cli_module, "load_config", lambda *args, **kwargs: config)
    monkeypatch.setattr(
        cli_module.sys,
        "argv",
        [
            "main.py",
            "--add-url",
            "https://videos.example.com/watch/episode-1",
            "--skip-age-check",
        ],
    )

    result = cli_module.main()

    assert result == 0
    assert QueueStore(queue_file, cli_module._logger).read_urls() == [
        "https://videos.example.com/watch/episode-1"
    ]
    assert BypassStore(bypass_file, cli_module._logger).load() == set()
    assert "Added 1 URL(s)" in capsys.readouterr().out


def test_cli_reports_config_error_and_exits_nonzero(monkeypatch, capsys) -> None:
    """Startup should fail cleanly when config validation rejects a setting."""

    def raise_config_error(*args, **kwargs) -> None:
        raise cli_module.ConfigError("channel_count must be an integer")

    monkeypatch.setattr(cli_module, "load_config", raise_config_error)
    monkeypatch.setattr(
        cli_module.sys,
        "argv",
        ["main.py"],
    )

    result = cli_module.main()

    assert result == 1
    assert "channel_count must be an integer" in capsys.readouterr().out


def test_cli_module_entrypoint_shows_help() -> None:
    """The scheduler should be able to run the CLI with ``python -m src.cli``."""
    result = subprocess.run(
        [sys.executable, "-m", "src.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0
    assert "Podcast downloader with YouTube SponsorBlock cleanup" in result.stdout
