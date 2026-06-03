"""Tests for the concise browser activity log."""

from __future__ import annotations

import fcntl
import multiprocessing
from pathlib import Path
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from src.activity_log import activity_log_file_for, read_activity_log_tail
import src.state.activity_store as activity_store_module
from src.state.activity_store import ActivityLogStore


def test_activity_log_file_uses_download_log_directory(tmp_path: Path) -> None:
    """The concise activity log should live beside the full diagnostic log."""
    full_log_file = tmp_path / "nested" / "download.log"

    activity_log_file = activity_log_file_for(full_log_file)

    assert activity_log_file == tmp_path / "nested" / "activity.log"


def test_read_activity_log_tail_returns_last_lines(tmp_path: Path) -> None:
    """The web UI should receive the most recent concise activity entries."""
    activity_log_file = tmp_path / "activity.log"
    activity_log_file.write_text(
        "\n".join(["old event", "middle event", "new event"]),
        encoding="utf-8",
    )

    tail = read_activity_log_tail(activity_log_file, line_count=2)

    assert tail == "middle event\nnew event"


def test_read_activity_log_tail_handles_missing_file(tmp_path: Path) -> None:
    """A fresh deployment should show an empty-state message instead of an error."""
    activity_log_file = tmp_path / "activity.log"

    tail = read_activity_log_tail(activity_log_file, line_count=100)

    assert tail == "No activity yet."


def test_activity_log_store_writes_and_reads_tail(tmp_path: Path) -> None:
    """ActivityLogStore should own concise activity log persistence."""
    activity_log_file = tmp_path / "activity.log"
    store = ActivityLogStore(activity_log_file)

    store.write_event("first event")
    store.write_event("second event")

    assert store.read_tail(line_count=1).endswith("second event")


def test_activity_log_store_writes_toronto_time(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Activity log timestamps should match the Toronto-local browser clock."""
    activity_log_file = tmp_path / "activity.log"
    seen_timezones: list[ZoneInfo | None] = []

    class FixedDateTime(datetime):
        """Datetime test double that records the requested timezone."""

        @classmethod
        def now(cls, tz=None) -> datetime:
            seen_timezones.append(tz)
            return datetime(2026, 5, 5, 21, 49, 4, tzinfo=tz)

    monkeypatch.setattr(activity_store_module, "datetime", FixedDateTime)

    ActivityLogStore(activity_log_file).write_event("downloaded")

    assert seen_timezones == [ZoneInfo("America/Toronto")]
    assert activity_log_file.read_text(encoding="utf-8") == (
        "[2026-05-05 21:49:04] downloaded\n"
    )


def _write_partial_activity_log(
    activity_log_file: str,
    ready_file: str,
    release_file: str,
) -> None:
    """Write a partial line while holding an exclusive lock."""
    log_path = Path(activity_log_file)
    ready_path = Path(ready_file)
    release_path = Path(release_file)

    with open(log_path, "w+", encoding="utf-8") as file_handle:
        fcntl.flock(file_handle.fileno(), fcntl.LOCK_EX)
        file_handle.write("[2026-05-05 12:00:00] first line\n")
        file_handle.write("[2026-05-05 12:00:01] second line")
        file_handle.flush()
        ready_path.write_text("ready", encoding="utf-8")

        while not release_path.exists():
            time.sleep(0.01)

        file_handle.write(" complete\n")
        file_handle.flush()
        fcntl.flock(file_handle.fileno(), fcntl.LOCK_UN)


def test_read_activity_log_tail_returns_whole_lines_during_write(
    tmp_path: Path,
) -> None:
    """The browser log should not surface a half-written line."""
    activity_log_file = tmp_path / "activity.log"
    ready_file = tmp_path / "ready"
    release_file = tmp_path / "release"

    writer = multiprocessing.Process(
        target=_write_partial_activity_log,
        args=(str(activity_log_file), str(ready_file), str(release_file)),
    )
    writer.start()

    try:
        deadline = time.time() + 5
        while not ready_file.exists() and time.time() < deadline:
            time.sleep(0.01)

        assert ready_file.exists(), (
            "writer did not reach the locked partial-write state"
        )

        result: dict[str, str] = {}

        def read_tail() -> None:
            result["tail"] = read_activity_log_tail(activity_log_file, line_count=2)

        reader = threading.Thread(target=read_tail)
        reader.start()

        time.sleep(0.05)
        release_file.write_text("release", encoding="utf-8")

        reader.join(timeout=5)
        writer.join(timeout=5)

        assert not reader.is_alive(), "read_activity_log_tail did not finish"
        assert writer.exitcode == 0
        assert result["tail"] == (
            "[2026-05-05 12:00:00] first line\n"
            "[2026-05-05 12:00:01] second line complete"
        )
    finally:
        if writer.is_alive():
            writer.terminate()
            writer.join(timeout=5)
