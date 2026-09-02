"""Start the web UI and scheduled downloads in one container.

Scheduled runs follow a wall clock, not a stopwatch. They start at
``scheduled_run_hour`` on every ``scheduled_run_interval_days``-th calendar
day, both read from ``config.ini``, which by default means 06:00 Toronto time
every other day. Restarting the container, redeploying, or pressing Run in the
browser therefore never moves the schedule. ``src/schedule.py`` owns the rule
that turns those two settings into run times.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import uvicorn
from src.config import ConfigError, load_config
from src.credentials import sync_ui_credentials
from src.human_time import format_clock_time
from src.log_timezone import local_now
from src.notifications.apprise_client import notifier_for_data_dir
from src.run_report import RunAlert, build_failed_run_alert, build_missed_run_alert
from src.schedule import (
    next_scheduled_run,
    previous_scheduled_run,
    scheduled_run_is_overdue,
    seconds_until_next_scheduled_run,
)
from src.state.run_state_store import (
    RunKind,
    RunState,
    RunStateStore,
    run_state_file_for,
)
from src.trigger import (
    download_trigger,
    pop_full_playlist_download_requests,
    pop_full_queue_run_request,
    pop_single_url_download_requests,
    pop_source_download_requests,
)

PROJECT_ROOT = Path(__file__).resolve().parent
# Docker keeps `.env` and runtime files in `/data`; local runs keep them at the
# project root.
DATA_DIR = Path(os.environ.get("PODCAST_DATA_DIR", str(PROJECT_ROOT)))
RUN_STATE_STORE = RunStateStore(run_state_file_for(DATA_DIR))

try:
    CONFIG = load_config(DATA_DIR / "config.ini", DATA_DIR)
except ConfigError as exc:
    raise SystemExit(f"[scheduler] Startup error: {exc}") from exc

RUN_HOUR = CONFIG.scheduled_run_hour
RUN_INTERVAL_DAYS = CONFIG.scheduled_run_interval_days


def _cli_command() -> list[str]:
    """Return the CLI command with the Python executable used by this process."""
    return [sys.executable, "-m", "src.cli"]


def _next_run_time() -> datetime:
    """Return the next scheduled run instant under the configured schedule."""
    return next_scheduled_run(
        local_now(), run_hour=RUN_HOUR, interval_days=RUN_INTERVAL_DAYS
    )


def _scheduled_run_was_missed(run_state: RunState) -> bool:
    """Return whether the container was down for the last scheduled run.

    A fixed schedule alone would let a restart at 06:05 on a run day cost two
    days of episodes. Comparing the last finished run against the most recent
    scheduled time closes that gap without moving the schedule itself. A data
    directory with no recorded run counts as missed, so a first deployment
    starts working immediately.

    No allowance is given here, unlike the health endpoint: at startup the
    question is simply whether the due run has already happened.

    Parameters
    ----------
    run_state:
        The record as the scheduler found it at startup.
    """
    return scheduled_run_is_overdue(
        run_state.finished_at,
        now=local_now(),
        run_hour=RUN_HOUR,
        interval_days=RUN_INTERVAL_DAYS,
        grace_seconds=0,
    )


def _send_alert(alert: RunAlert) -> None:
    """Post one scheduler alert to Apprise, or do nothing when it is not set up.

    The downloader process sends its own alerts. These are the ones only the
    scheduler can see: a run that never happened, and a run that could not
    start.
    """
    notifier = notifier_for_data_dir(DATA_DIR)
    if not notifier.settings.is_ready():
        return
    result = notifier.send(alert.title, alert.body)
    if not result.ok:
        print(f"[scheduler] Could not send an alert: {result.detail}", flush=True)


def _report_missed_run(run_state: RunState) -> None:
    """Tell the operator that a scheduled run did not happen.

    A machine that comes back after being down is the one silent failure the
    downloader can report on its own. One that never comes back cannot, which
    is what a watchdog polling ``/api/health`` is for.

    Parameters
    ----------
    run_state:
        The record as the scheduler found it at startup.
    """
    if run_state.finished_at is None:
        # First boot on a fresh data directory. Nothing was missed; there is
        # simply no history yet.
        return

    now = local_now()
    _send_alert(
        build_missed_run_alert(
            run_state.finished_at,
            previous_scheduled_run(
                now, run_hour=RUN_HOUR, interval_days=RUN_INTERVAL_DAYS
            ),
            now,
        )
    )


AUTO_UPDATE = os.environ.get("YT_DLP_AUTO_UPDATE", "true") == "true"
POST_UPDATE_WAIT_SECONDS = 5 * 60
YTDLP_PACKAGE_SPEC = "yt-dlp[default,curl-cffi]"
YTDLP_PRERELEASE_MODE = "allow"


def _installed_ytdlp_version() -> str:
    """Return the installed ``yt-dlp`` version, or a note that it is missing.

    A missing binary must not raise here. The scheduler thread exits the whole
    container on an unhandled error, which would turn "yt-dlp is not installed"
    into a restart loop instead of a message the downloader can report.
    """
    try:
        result = subprocess.run(
            ["yt-dlp", "--version"], capture_output=True, text=True, check=False
        )
    except OSError:
        return "not installed"
    return result.stdout.strip() or "unknown"


def update_ytdlp() -> bool:
    """Update ``yt-dlp`` when automatic updates are enabled."""
    if not AUTO_UPDATE:
        print(
            f"[scheduler] yt-dlp auto-update disabled; using {_installed_ytdlp_version()}",
            flush=True,
        )
        return False

    result = subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--upgrade",
            "--prerelease",
            YTDLP_PRERELEASE_MODE,
            YTDLP_PACKAGE_SPEC,
            "--quiet",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(
            "[scheduler] Warning: yt-dlp update failed; continuing with current version",
            flush=True,
        )
        print(f"[scheduler] yt-dlp {_installed_ytdlp_version()}", flush=True)
        return False

    print(f"[scheduler] yt-dlp {_installed_ytdlp_version()}", flush=True)
    return True


def _handle_pending_ui_requests() -> None:
    """Run whatever the browser asked for since the last check."""
    _run_immediate_downloads(
        pop_single_url_download_requests(),
        pop_full_playlist_download_requests(),
        pop_source_download_requests(),
        pop_full_queue_run_request(),
    )


def _wait_for_post_update_delay() -> None:
    """Pause after a yt-dlp update, still answering browser requests.

    Scheduled runs pause five minutes after ``yt-dlp`` updates so YouTube has
    time to settle. Requests from the browser are handled during that pause
    rather than waiting it out, and the scheduled run still follows.
    """
    wait_minutes = POST_UPDATE_WAIT_SECONDS // 60
    print(
        f"[scheduler] Waiting {wait_minutes} minutes after the yt-dlp update before downloading...",
        flush=True,
    )
    deadline = time.monotonic() + POST_UPDATE_WAIT_SECONDS
    while True:
        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds <= 0:
            return
        # The event makes this delay interruptible when the browser adds a URL.
        if not download_trigger.wait(timeout=remaining_seconds):
            return
        download_trigger.clear()
        _handle_pending_ui_requests()


def _wait_for_next_scheduled_run() -> None:
    """Sleep until the next scheduled run, answering browser requests meanwhile.

    The wait length is recomputed from the wall clock on every pass, so a
    request handled in the middle of it does not shorten or postpone the next
    scheduled run.
    """
    while True:
        remaining_seconds = seconds_until_next_scheduled_run(
            local_now(), run_hour=RUN_HOUR, interval_days=RUN_INTERVAL_DAYS
        )
        if remaining_seconds <= 0:
            return
        if not download_trigger.wait(timeout=remaining_seconds):
            return
        download_trigger.clear()
        _handle_pending_ui_requests()
        _announce_next_run()


def _announce_next_run(prefix: str = "Next scheduled run") -> None:
    """Print when the next automatic run is due."""
    print(f"[scheduler] {prefix}: {format_clock_time(_next_run_time())}", flush=True)


def update_and_run_full_queue() -> None:
    """Refresh ``yt-dlp``, wait for it to settle, then run the whole queue."""
    print("[scheduler] Updating yt-dlp...", flush=True)
    if update_ytdlp():
        _wait_for_post_update_delay()
    print("[scheduler] Starting download run...", flush=True)
    run_full_queue_pass(RunKind.SCHEDULED)


def run_full_queue_pass(kind: RunKind) -> None:
    """Run one whole-queue download pass and record when it happened.

    Parameters
    ----------
    kind:
        Whether the schedule or the browser Run button started this pass. The
        queue page shows the answer next to the last-run time.
    """
    RUN_STATE_STORE.mark_run_started(kind)
    try:
        result = subprocess.run(_cli_command(), check=False, cwd=str(PROJECT_ROOT))
    finally:
        RUN_STATE_STORE.mark_run_finished()

    # The downloader reports its own problems, but only once it is running. A
    # process that stops before that has nothing to report with.
    if result.returncode != 0:
        print(
            f"[scheduler] The download run exited with status {result.returncode}.",
            flush=True,
        )
        _send_alert(build_failed_run_alert(result.returncode, local_now()))


def run_scheduler() -> None:
    """Run the queue on the configured wall-clock schedule, forever."""
    # A container killed mid-run leaves the "running" flag set, which would
    # make the web page refuse every later Run request. Clearing it also hands
    # back the record, so startup reads the file once.
    run_state = RUN_STATE_STORE.clear_stale_running_flag()
    day_word = "day" if RUN_INTERVAL_DAYS == 1 else f"{RUN_INTERVAL_DAYS} days"
    print(
        f"[scheduler] Schedule: {RUN_HOUR:02d}:00 local time, every {day_word}",
        flush=True,
    )
    _announce_next_run()

    catching_up = _scheduled_run_was_missed(run_state)
    if catching_up:
        print(
            "[scheduler] No run since the last scheduled time — catching up now.",
            flush=True,
        )
        _report_missed_run(run_state)

    while True:
        # The catch-up pass runs before the first wait; every later pass waits
        # for its scheduled time first.
        if not catching_up:
            _wait_for_next_scheduled_run()
        catching_up = False
        update_and_run_full_queue()
        _announce_next_run("Done. Next scheduled run")


def _run_immediate_downloads(
    single_url_requests: list[str],
    full_playlist_requests: list[str] | None = None,
    source_requests: list[str] | None = None,
    full_queue_run_requested: bool = False,
) -> None:
    """Run downloads requested by the browser without updating ``yt-dlp`` first.

    Parameters
    ----------
    single_url_requests:
        Direct video URLs submitted through the UI single-item path.
    full_playlist_requests:
        Playlist URLs submitted through the UI full-playlist immediate path.
    source_requests:
        Saved queue sources whose own Run now button was pressed. Direct videos
        bypass the age gate; channels and playlists retain normal source rules.
    full_queue_run_requested:
        True when the Run button asked for the same whole-queue pass the
        schedule performs.
    """
    playlist_requests = full_playlist_requests or []
    targeted_source_requests = source_requests or []
    if playlist_requests:
        for url in playlist_requests:
            print(
                f"[scheduler] Playlist added via UI — starting full immediate run: {url}",
                flush=True,
            )
            subprocess.run(
                [*_cli_command(), "--download-full-playlist", url],
                check=False,
                cwd=str(PROJECT_ROOT),
            )
    if targeted_source_requests:
        for url in targeted_source_requests:
            print(
                f"[scheduler] Source run requested via UI: {url}",
                flush=True,
            )
            subprocess.run(
                [*_cli_command(), "--download-source-now", url],
                check=False,
                cwd=str(PROJECT_ROOT),
            )
    if single_url_requests:
        for url in single_url_requests:
            print(
                f"[scheduler] URL added via UI — starting single immediate run: {url}",
                flush=True,
            )
            subprocess.run(
                [*_cli_command(), "--download-single-url", url],
                check=False,
                cwd=str(PROJECT_ROOT),
            )
    if full_queue_run_requested:
        print(
            "[scheduler] Run requested from the web page — running the queue now",
            flush=True,
        )
        run_full_queue_pass(RunKind.MANUAL)


def run_scheduler_in_background() -> None:
    """Exit the container if the scheduler thread stops unexpectedly."""
    try:
        run_scheduler()
    except Exception as exc:
        print(f"[scheduler] Fatal error: {exc}", flush=True)
        os._exit(1)


def start_web() -> None:
    uvicorn.run("src.api:app", host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    # Create and check the credentials file before serving the login page.
    print(f"[startup] {sync_ui_credentials(DATA_DIR)}", flush=True)
    # Keep the web server as PID 1 so Docker can restart the container if needed.
    scheduler_thread = threading.Thread(target=run_scheduler_in_background, daemon=True)
    scheduler_thread.start()
    start_web()
