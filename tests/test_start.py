"""Regression tests for Docker scheduler startup validation."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
import src.config as config_module
import start
from src.log_timezone import LOG_TIME_ZONE
from src.state.run_state_store import RunKind, RunState
from src.trigger import (
    pop_full_queue_run_request,
    pop_single_url_download_requests,
    pop_source_download_requests,
    queue_full_queue_run,
    queue_single_url_download,
    queue_source_download,
)


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


def test_run_immediate_downloads_processes_targeted_source_requests(
    monkeypatch,
) -> None:
    """Saved-source payloads should use the targeted source CLI path."""
    calls: list[tuple[list[str], str | None]] = []

    def fake_run(command: list[str], check: bool, cwd: str | None = None) -> None:
        calls.append((command, cwd))

    monkeypatch.setattr(start.subprocess, "run", fake_run)
    monkeypatch.setattr(start.sys, "executable", "/python")

    source_url = "https://www.youtube.com/@examplechannel"
    start._run_immediate_downloads([], [], [source_url])

    assert calls == [
        (
            ["/python", "-m", "src.cli", "--download-source-now", source_url],
            str(start.PROJECT_ROOT),
        )
    ]


def test_run_immediate_downloads_without_any_payload_runs_nothing(
    monkeypatch,
) -> None:
    """An empty wake-up must not fall back to running the whole queue."""
    calls: list[tuple[list[str], str | None]] = []

    def fake_run(command: list[str], check: bool, cwd: str | None = None) -> None:
        calls.append((command, cwd))

    monkeypatch.setattr(start.subprocess, "run", fake_run)
    monkeypatch.setattr(start.sys, "executable", "/python")

    start._run_immediate_downloads([])

    assert calls == []


def test_run_immediate_downloads_runs_whole_queue_when_button_pressed(
    monkeypatch,
) -> None:
    """The Run button should start the same pass the schedule runs."""
    calls: list[tuple[list[str], str | None]] = []
    recorded_kinds: list[RunKind] = []

    def fake_run(command: list[str], check: bool, cwd: str | None = None):
        calls.append((command, cwd))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(start.subprocess, "run", fake_run)
    monkeypatch.setattr(start.sys, "executable", "/python")
    monkeypatch.setattr(
        start.RUN_STATE_STORE,
        "mark_run_started",
        lambda kind: recorded_kinds.append(kind),
    )
    monkeypatch.setattr(start.RUN_STATE_STORE, "mark_run_finished", lambda: None)

    start._run_immediate_downloads([], [], [], True)

    assert calls == [(["/python", "-m", "src.cli"], str(start.PROJECT_ROOT))]
    assert recorded_kinds == [RunKind.MANUAL]


def test_post_update_delay_runs_pending_request_and_still_returns(
    monkeypatch,
) -> None:
    """A request during the post-update pause runs without cancelling the pass."""
    handled: list[list[str]] = []
    pop_single_url_download_requests()
    queue_single_url_download("https://www.youtube.com/watch?v=abc123")

    def fake_run_immediate_downloads(
        single_url_requests: list[str],
        full_playlist_requests: list[str] | None = None,
        source_requests: list[str] | None = None,
        full_queue_run_requested: bool = False,
    ) -> None:
        handled.append(single_url_requests)
        # Simulate the pause elapsing while that request was being handled.
        monkeypatch.setattr(start.time, "monotonic", lambda: float("inf"))

    monkeypatch.setattr(start, "_run_immediate_downloads", fake_run_immediate_downloads)

    start._wait_for_post_update_delay()

    assert handled == [["https://www.youtube.com/watch?v=abc123"]]


def test_pending_source_request_is_popped_for_the_scheduler(monkeypatch) -> None:
    """The scheduler handoff should carry one row-level Run now request."""
    handled: list[tuple[list[str], list[str]]] = []
    pop_source_download_requests()
    source_url = "https://www.youtube.com/playlist?list=PL123"
    queue_source_download(source_url)

    def fake_run_immediate_downloads(
        single_url_requests: list[str],
        full_playlist_requests: list[str] | None = None,
        source_requests: list[str] | None = None,
        full_queue_run_requested: bool = False,
    ) -> None:
        handled.append((single_url_requests, source_requests or []))

    monkeypatch.setattr(start, "_run_immediate_downloads", fake_run_immediate_downloads)

    start._handle_pending_ui_requests()

    assert handled == [([], [source_url])]


def test_scheduled_wait_uses_seconds_until_the_next_fixed_run_time(
    monkeypatch,
) -> None:
    """The wait length must come from the wall clock, not a fixed interval."""
    wait_timeouts: list[float] = []

    class FakeTrigger:
        """Event-like test double that reports a plain scheduler timeout."""

        def wait(self, timeout: float) -> bool:
            wait_timeouts.append(timeout)
            return False

        def clear(self) -> None:
            raise AssertionError("A plain timeout must not clear the trigger.")

    monkeypatch.setattr(start, "download_trigger", FakeTrigger())
    # 05:00 on a run day, so the next 06:00 run is exactly one hour away.
    run_day = datetime(2026, 9, 3, 5, 0, tzinfo=LOG_TIME_ZONE)
    assert run_day.date().toordinal() % start.RUN_INTERVAL_DAYS == 0
    monkeypatch.setattr(start, "local_now", lambda: run_day)

    start._wait_for_next_scheduled_run()

    assert wait_timeouts == [3600.0]


def test_scheduled_run_is_treated_as_missed_when_nothing_ran_since(
    monkeypatch,
) -> None:
    """A container that was down over the run time should catch up on startup."""
    now = datetime(2026, 9, 3, 9, 0, tzinfo=LOG_TIME_ZONE)
    monkeypatch.setattr(start, "local_now", lambda: now)

    stale_run = RunState(finished_at=now - timedelta(days=3))

    assert start._scheduled_run_was_missed(stale_run) is True


def test_scheduled_run_is_not_missed_when_it_already_ran_today(monkeypatch) -> None:
    """A restart after a completed run must not start a second one."""
    now = datetime(2026, 9, 3, 9, 0, tzinfo=LOG_TIME_ZONE)
    monkeypatch.setattr(start, "local_now", lambda: now)

    recent_run = RunState(finished_at=now - timedelta(hours=2))

    assert start._scheduled_run_was_missed(recent_run) is False


def test_full_queue_run_request_is_popped_once(monkeypatch) -> None:
    """Reading the Run request must clear it so it cannot run twice."""
    pop_full_queue_run_request()
    queue_full_queue_run()

    assert pop_full_queue_run_request() is True
    assert pop_full_queue_run_request() is False


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
        "--prerelease",
        "allow",
        "yt-dlp[default,curl-cffi]",
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
        "--prerelease",
        "allow",
        "yt-dlp[default,curl-cffi]",
        "--quiet",
    ]
    assert commands[1] == ["yt-dlp", "--version"]


def test_post_update_delay_waits_five_minutes_without_a_request(monkeypatch) -> None:
    """Scheduled runs should pause five minutes after a yt-dlp update."""
    wait_timeouts: list[float] = []

    def fake_wait(timeout: float) -> bool:
        wait_timeouts.append(timeout)
        return False

    monkeypatch.setattr(start.download_trigger, "wait", fake_wait)

    start._wait_for_post_update_delay()

    assert wait_timeouts == [pytest.approx(start.POST_UPDATE_WAIT_SECONDS, abs=1)]


def test_a_run_that_cannot_start_is_reported(monkeypatch) -> None:
    """A downloader that stops before running has nothing to report with.

    Nothing is downloaded and nothing fails, so without this the failure is
    invisible until someone notices the library has stopped growing.
    """
    alerts: list[str] = []

    monkeypatch.setattr(
        start.subprocess,
        "run",
        lambda command, check=False, cwd=None: SimpleNamespace(returncode=1),
    )
    monkeypatch.setattr(start.RUN_STATE_STORE, "mark_run_started", lambda kind: None)
    monkeypatch.setattr(start.RUN_STATE_STORE, "mark_run_finished", lambda: None)
    monkeypatch.setattr(start, "_send_alert", lambda alert: alerts.append(alert.title))

    start.run_full_queue_pass(RunKind.SCHEDULED)

    assert alerts == ["Podcast downloader could not finish a run"]


def test_a_successful_run_is_not_reported(monkeypatch) -> None:
    """Exit status zero means the downloader spoke for itself."""
    alerts: list[str] = []

    monkeypatch.setattr(
        start.subprocess,
        "run",
        lambda command, check=False, cwd=None: SimpleNamespace(returncode=0),
    )
    monkeypatch.setattr(start.RUN_STATE_STORE, "mark_run_started", lambda kind: None)
    monkeypatch.setattr(start.RUN_STATE_STORE, "mark_run_finished", lambda: None)
    monkeypatch.setattr(start, "_send_alert", lambda alert: alerts.append(alert.title))

    start.run_full_queue_pass(RunKind.SCHEDULED)

    assert alerts == []


def test_a_missing_ytdlp_does_not_take_the_container_down(monkeypatch) -> None:
    """The scheduler thread exits the process on an unhandled error.

    Letting a missing binary raise here would turn "yt-dlp is not installed"
    into a restart loop instead of a message the operator can read.
    """

    def raise_missing(*args, **kwargs):
        raise FileNotFoundError(2, "No such file or directory: 'yt-dlp'")

    monkeypatch.setattr(start, "AUTO_UPDATE", False)
    monkeypatch.setattr(start.subprocess, "run", raise_missing)

    assert start.update_ytdlp() is False
    assert start._installed_ytdlp_version() == "not installed"
