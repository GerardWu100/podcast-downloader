"""Regression tests for Docker scheduler startup validation."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import start
import src.config as config_module
from src.trigger import pop_batch_download_request
from src.trigger import pop_single_url_download_requests
from src.trigger import queue_batch_download
from src.trigger import queue_single_url_download


def test_run_immediate_downloads_processes_single_url_requests(monkeypatch) -> None:
    """Single URL payloads should run only that URL, not the whole queue."""
    calls: list[tuple[list[str], str | None]] = []

    def fake_run(command: list[str], check: bool, cwd: str | None = None) -> None:
        calls.append((command, cwd))

    monkeypatch.setattr(start.subprocess, "run", fake_run)
    monkeypatch.setattr(start.sys, "executable", "/python")

    start._run_immediate_downloads(["https://www.youtube.com/watch?v=abc123"])

    assert calls == [
        (
            [
                "/python",
                "-m",
                "src.cli",
                "--download-single-url",
                "https://www.youtube.com/watch?v=abc123",
            ],
            str(start.PROJECT_ROOT),
        )
    ]


def test_run_immediate_downloads_processes_full_playlist_requests(monkeypatch) -> None:
    """Playlist payloads should run the full-playlist CLI path."""
    calls: list[tuple[list[str], str | None]] = []

    def fake_run(command: list[str], check: bool, cwd: str | None = None) -> None:
        calls.append((command, cwd))

    monkeypatch.setattr(start.subprocess, "run", fake_run)
    monkeypatch.setattr(start.sys, "executable", "/python")

    playlist_url = "https://www.youtube.com/playlist?list=PL123"
    start._run_immediate_downloads(
        [],
        [playlist_url],
    )

    assert calls == [
        (
            [
                "/python",
                "-m",
                "src.cli",
                "--download-full-playlist",
                playlist_url,
            ],
            str(start.PROJECT_ROOT),
        )
    ]


def test_run_immediate_downloads_falls_back_to_full_batch_without_payload(
    monkeypatch,
) -> None:
    """Internal batch triggers should keep the existing full-queue run behavior."""
    calls: list[tuple[list[str], str | None]] = []

    def fake_run(command: list[str], check: bool, cwd: str | None = None) -> None:
        calls.append((command, cwd))

    monkeypatch.setattr(start.subprocess, "run", fake_run)
    monkeypatch.setattr(start.sys, "executable", "/python")

    start._run_immediate_downloads([], batch_requested=True)

    assert calls == [(["/python", "-m", "src.cli"], str(start.PROJECT_ROOT))]


def test_run_immediate_downloads_ignores_batch_request_after_single_urls(
    monkeypatch,
) -> None:
    """Checked single payloads should not also run the full queue."""
    calls: list[tuple[list[str], str | None]] = []

    def fake_run(command: list[str], check: bool, cwd: str | None = None) -> None:
        calls.append((command, cwd))

    monkeypatch.setattr(start.subprocess, "run", fake_run)
    monkeypatch.setattr(start.sys, "executable", "/python")

    start._run_immediate_downloads(
        ["https://www.youtube.com/watch?v=abc123"],
        batch_requested=True,
    )

    assert calls == [
        (
            [
                "/python",
                "-m",
                "src.cli",
                "--download-single-url",
                "https://www.youtube.com/watch?v=abc123",
            ],
            str(start.PROJECT_ROOT),
        )
    ]


def test_post_update_delay_runs_pending_single_url_instead_of_waiting(
    monkeypatch,
) -> None:
    """A UI trigger during startup delay should be handled before a full queue run."""
    handled: list[tuple[list[str], bool]] = []
    pop_single_url_download_requests()
    pop_batch_download_request()
    queue_single_url_download("https://www.youtube.com/watch?v=abc123")

    def fake_run_immediate_downloads(
        single_url_requests: list[str],
        full_playlist_requests: list[str] | None = None,
        batch_requested: bool = False,
    ) -> None:
        handled.append((single_url_requests, batch_requested))

    monkeypatch.setattr(start, "_run_immediate_downloads", fake_run_immediate_downloads)

    triggered = start._wait_for_post_update_delay_or_ui_trigger()

    assert triggered is True
    assert handled == [(["https://www.youtube.com/watch?v=abc123"], False)]


def test_post_update_delay_runs_pending_batch_trigger(monkeypatch) -> None:
    """A pending internal batch trigger during startup delay should still run."""
    handled: list[tuple[list[str], bool]] = []
    pop_single_url_download_requests()
    pop_batch_download_request()
    queue_batch_download()

    def fake_run_immediate_downloads(
        single_url_requests: list[str],
        full_playlist_requests: list[str] | None = None,
        batch_requested: bool = False,
    ) -> None:
        handled.append((single_url_requests, batch_requested))

    monkeypatch.setattr(start, "_run_immediate_downloads", fake_run_immediate_downloads)

    triggered = start._wait_for_post_update_delay_or_ui_trigger()

    assert triggered is True
    assert handled == [([], True)]


def test_interval_wait_does_not_clear_trigger_after_plain_timeout(monkeypatch) -> None:
    """A timeout should leave any newly arriving UI trigger untouched."""
    clear_calls = 0

    class FakeTrigger:
        """Event-like test double that simulates a plain scheduler timeout."""

        def wait(self, timeout: int) -> bool:
            assert timeout == start.INTERVAL_SECONDS
            return False

        def clear(self) -> None:
            nonlocal clear_calls
            clear_calls += 1

    monkeypatch.setattr(start, "download_trigger", FakeTrigger())

    start._wait_for_interval_or_ui_triggers()

    assert clear_calls == 0


def test_parse_interval_hours_accepts_positive_integer() -> None:
    """Positive integer intervals should be accepted unchanged."""
    assert start._parse_interval_hours("48") == 48


@pytest.mark.parametrize("raw_value", ["0", "-1", "not-a-number"])
def test_parse_interval_hours_rejects_invalid_values(raw_value: str) -> None:
    """Docker scheduler intervals must fail validation when non-positive or malformed."""
    with pytest.raises(ValueError):
        start._parse_interval_hours(raw_value)


def test_update_ytdlp_returns_false_when_package_update_fails(monkeypatch) -> None:
    """A failed package update should not count as a successful pre-run refresh."""
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> SimpleNamespace:
        commands.append(command)
        return SimpleNamespace(returncode=1, stdout="", stderr="update failed")

    monkeypatch.setattr(start, "AUTO_UPDATE", True)
    monkeypatch.setattr(start.subprocess, "run", fake_run)

    did_update = start.update_ytdlp()

    assert did_update is False
    assert commands[0] == [
        "uv",
        "pip",
        "install",
        "--upgrade",
        "yt-dlp[default]",
        "--quiet",
    ]


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("channel_count", "not-an-int"),
        ("min_channel_video_age_hours", "still-not-an-int"),
        ("delay_seconds", "not-a-float"),
    ],
)
def test_load_config_rejects_invalid_numeric_values(
    tmp_path,
    key: str,
    value: str,
) -> None:
    """Startup config should reject malformed numeric settings loudly."""
    config_file = tmp_path / "config.ini"
    config_file.write_text(f"[podcast]\n{key} = {value}\n", encoding="utf-8")

    with pytest.raises(ValueError, match=key):
        config_module.load_config(config_file, tmp_path)


def test_update_ytdlp_only_upgrades_that_package(monkeypatch) -> None:
    """The scheduled updater must target only yt-dlp instead of upgrading the whole environment."""
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> SimpleNamespace:
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="2026.03.01\n")

    monkeypatch.setattr(start, "AUTO_UPDATE", True)
    monkeypatch.setattr(start.subprocess, "run", fake_run)

    did_update = start.update_ytdlp()

    assert did_update is True
    assert commands[0] == [
        "uv",
        "pip",
        "install",
        "--upgrade",
        "yt-dlp[default]",
        "--quiet",
    ]
    assert commands[1] == ["yt-dlp", "--version"]


def test_post_update_delay_waits_five_minutes_without_ui_trigger(monkeypatch) -> None:
    """Scheduled runs should pause five minutes after a yt-dlp update."""
    wait_timeouts: list[float] = []

    def fake_wait(timeout: float) -> bool:
        wait_timeouts.append(timeout)
        return False

    monkeypatch.setattr(start.download_trigger, "wait", fake_wait)

    handled_ui_trigger = start._wait_for_post_update_delay_or_ui_trigger()

    assert handled_ui_trigger is False
    assert wait_timeouts == [start.POST_UPDATE_WAIT_SECONDS]
