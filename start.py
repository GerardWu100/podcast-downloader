"""Container entrypoint that runs the web UI and scheduler together."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

import uvicorn
from src.trigger import (
    download_trigger,
    pop_batch_download_request,
    pop_full_playlist_download_requests,
    pop_single_url_download_requests,
)

PROJECT_ROOT = Path(__file__).resolve().parent


def _cli_command() -> list[str]:
    """Return the scheduler-safe CLI command for the current Python executable."""
    return [sys.executable, "-m", "src.cli"]


def _parse_interval_hours(raw_value: str) -> int:
    """Parse ``DOWNLOAD_INTERVAL_HOURS`` and reject invalid values early."""
    try:
        interval_hours = int(raw_value)
    except ValueError as exc:
        raise ValueError(
            "DOWNLOAD_INTERVAL_HOURS must be a positive integer number of hours."
        ) from exc

    if interval_hours <= 0:
        raise ValueError("DOWNLOAD_INTERVAL_HOURS must be greater than zero.")

    return interval_hours


try:
    INTERVAL_HOURS = _parse_interval_hours(
        os.environ.get("DOWNLOAD_INTERVAL_HOURS", "48")
    )
except ValueError as exc:
    raise SystemExit(f"[scheduler] Startup error: {exc}") from exc

INTERVAL_SECONDS = INTERVAL_HOURS * 3600
AUTO_UPDATE = os.environ.get("YT_DLP_AUTO_UPDATE", "true") == "true"
POST_UPDATE_WAIT_SECONDS = 5 * 60


def update_ytdlp() -> bool:
    """Update ``yt-dlp`` in place when auto-update is enabled."""
    if not AUTO_UPDATE:
        result = subprocess.run(
            ["yt-dlp", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        print(
            f"[scheduler] yt-dlp auto-update disabled; using {result.stdout.strip()}",
            flush=True,
        )
        return False

    result = subprocess.run(
        ["uv", "pip", "install", "--upgrade", "yt-dlp[default]", "--quiet"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(
            "[scheduler] Warning: yt-dlp update failed; continuing with current version",
            flush=True,
        )
        version_result = subprocess.run(
            ["yt-dlp", "--version"], capture_output=True, text=True, check=False
        )
        print(f"[scheduler] yt-dlp {version_result.stdout.strip()}", flush=True)
        return False

    version_result = subprocess.run(
        ["yt-dlp", "--version"], capture_output=True, text=True, check=False
    )
    print(f"[scheduler] yt-dlp {version_result.stdout.strip()}", flush=True)
    return True


def _wait_for_post_update_delay_or_ui_trigger() -> bool:
    """Wait after an update, but handle a pending UI trigger first.

    Scheduled runs pause five minutes after ``yt-dlp`` updates so YouTube has
    time to settle. UI-triggered work can interrupt that wait immediately.

    Returns
    -------
    bool
        ``True`` when a UI-triggered download was handled during the delay.
        The caller should skip the full scheduled queue pass in that case.
    """
    wait_minutes = POST_UPDATE_WAIT_SECONDS // 60
    print(
        f"[scheduler] Waiting {wait_minutes} minutes after the yt-dlp update before downloading...",
        flush=True,
    )
    # Event.wait keeps the delay interruptible when the UI queues a direct video.
    triggered = download_trigger.wait(timeout=POST_UPDATE_WAIT_SECONDS)
    if not triggered:
        return False

    download_trigger.clear()
    _run_immediate_downloads(
        pop_single_url_download_requests(),
        pop_full_playlist_download_requests(),
        pop_batch_download_request(),
    )
    return True


def _wait_for_interval_or_ui_triggers() -> None:
    """Wait for the next scheduled interval while serving UI-triggered runs."""
    while True:
        triggered = download_trigger.wait(timeout=INTERVAL_SECONDS)
        if not triggered:
            break
        download_trigger.clear()
        _run_immediate_downloads(
            pop_single_url_download_requests(),
            pop_full_playlist_download_requests(),
            pop_batch_download_request(),
        )


def run_scheduler() -> None:
    print(f"[scheduler] Interval: every {INTERVAL_HOURS}h", flush=True)
    while True:
        print("[scheduler] Updating yt-dlp...", flush=True)
        did_update = update_ytdlp()
        if did_update:
            handled_ui_trigger = _wait_for_post_update_delay_or_ui_trigger()
            if handled_ui_trigger:
                print(
                    f"[scheduler] UI-triggered run complete. Next scheduled run in {INTERVAL_HOURS}h.",
                    flush=True,
                )
                _wait_for_interval_or_ui_triggers()
                continue
        print("[scheduler] Starting download run...", flush=True)
        subprocess.run(_cli_command(), check=False, cwd=str(PROJECT_ROOT))
        print(f"[scheduler] Done. Next run in {INTERVAL_HOURS}h.", flush=True)

        # Wait for either the full interval or a UI-triggered download.
        # After each triggered run we wait a full interval again before the next
        # scheduled run, so adding a URL always resets the 48h clock.
        _wait_for_interval_or_ui_triggers()


def _run_immediate_downloads(
    single_url_requests: list[str],
    full_playlist_requests: list[str] | None = None,
    batch_requested: bool = False,
) -> None:
    """Run UI-triggered downloads without doing a scheduled ``yt-dlp`` update.

    Parameters
    ----------
    single_url_requests:
        Direct video URLs submitted through the UI single-item path.
    full_playlist_requests:
        Playlist URLs submitted through the UI full-playlist immediate path.
    batch_requested:
        Whether an older or internal caller requested a full immediate queue
        run. This is ignored when single URL requests are present because
        direct-video submissions mean "download this URL only."
    """
    playlist_requests = full_playlist_requests or []
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
    if not single_url_requests and not playlist_requests and batch_requested:
        print("[scheduler] URL added via UI — starting immediate run...", flush=True)
        subprocess.run(_cli_command(), check=False, cwd=str(PROJECT_ROOT))

    print(
        f"[scheduler] Immediate run complete. Next scheduled run in {INTERVAL_HOURS}h.",
        flush=True,
    )


def run_scheduler_in_background() -> None:
    """Restart the whole container if the scheduler thread crashes unexpectedly."""
    try:
        run_scheduler()
    except Exception as exc:
        print(f"[scheduler] Fatal error: {exc}", flush=True)
        os._exit(1)


def start_web() -> None:
    uvicorn.run("src.api:app", host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    # Keep the web server as PID 1 so Docker can restart the container if it exits.
    scheduler_thread = threading.Thread(target=run_scheduler_in_background, daemon=True)
    scheduler_thread.start()
    start_web()
