"""Tests for the concise browser activity log."""

from __future__ import annotations

import fcntl
import multiprocessing
from pathlib import Path
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import logging

from src.state.activity_store import (
    NO_DOWNLOAD_LOG_MESSAGE,
    ActivityLogStore,
    activity_log_file_for,
)
from src.downloads.service import PodcastDownloadService
import src.state.activity_store as activity_store_module


def test_activity_log_file_uses_download_log_directory(tmp_path: Path) -> None:
    """The concise activity log should live beside the full diagnostic log."""
    full_log_file = tmp_path / "nested" / "download.log"

    activity_log_file = activity_log_file_for(full_log_file)

    assert activity_log_file == tmp_path / "nested" / "activity.log"


def test_activity_store_read_tail_returns_last_lines(tmp_path: Path) -> None:
    """The web UI should receive the most recent concise activity entries."""
    activity_log_file = tmp_path / "activity.log"
    activity_log_file.write_text(
        "\n".join(["old event", "middle event", "new event"]),
        encoding="utf-8",
    )

    tail = ActivityLogStore(activity_log_file).read_tail(line_count=2)

    assert tail == "middle event\nnew event"


def test_activity_store_read_tail_handles_missing_file(tmp_path: Path) -> None:
    """A fresh deployment should show an empty-state message instead of an error."""
    activity_log_file = tmp_path / "activity.log"

    tail = ActivityLogStore(activity_log_file).read_tail(line_count=100)

    assert tail == "No activity yet."


def test_download_log_store_read_tail_returns_last_lines(tmp_path: Path) -> None:
    """The full diagnostic log tail should return the newest lines."""
    download_log_file = tmp_path / "download.log"
    download_log_file.write_text(
        "line one\nline two\nline three\n",
        encoding="utf-8",
    )

    tail = ActivityLogStore(download_log_file).read_tail(
        line_count=2,
        empty_message=NO_DOWNLOAD_LOG_MESSAGE,
    )

    assert tail == "line two\nline three"


def test_download_log_store_read_tail_handles_missing_file(tmp_path: Path) -> None:
    """A missing download log should show a download-specific empty state."""
    download_log_file = tmp_path / "download.log"

    tail = ActivityLogStore(download_log_file).read_tail(
        line_count=100,
        empty_message=NO_DOWNLOAD_LOG_MESSAGE,
    )

    assert tail == "No log entries yet."


def test_activity_log_store_writes_and_reads_tail(tmp_path: Path) -> None:
    """ActivityLogStore should own concise activity log persistence."""
    activity_log_file = tmp_path / "activity.log"
    store = ActivityLogStore(activity_log_file)

    store.write_event("first event")
    store.write_event("second event")

    assert store.read_tail(line_count=1).endswith("second event")


def test_download_log_formatter_uses_toronto_time(tmp_path: Path) -> None:
    """Full diagnostic log timestamps should use Toronto time without seconds."""
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text("", encoding="utf-8")
    log_file = tmp_path / "download.log"

    downloader = PodcastDownloadService(
        urls_file=urls_file,
        downloads_dir=tmp_path / "downloads",
        log_file=log_file,
    )
    file_handler = next(
        handler
        for handler in downloader.logger.handlers
        if isinstance(handler, logging.FileHandler)
    )
    formatter = file_handler.formatter
    assert formatter is not None

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="queued",
        args=(),
        exc_info=None,
    )
    record.created = datetime(2026, 5, 6, 1, 49, 4, tzinfo=ZoneInfo("UTC")).timestamp()

    assert formatter.format(record) == "[2026-05-05 21:49] INFO: queued"


def test_activity_log_store_writes_toronto_time(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Activity log timestamps should use Toronto time without seconds."""
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
        "[2026-05-05 21:49] downloaded\n"
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


def test_activity_store_read_tail_returns_whole_lines_during_write(
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
            result["tail"] = ActivityLogStore(activity_log_file).read_tail(line_count=2)

        reader = threading.Thread(target=read_tail)
        reader.start()

        time.sleep(0.05)
        release_file.write_text("release", encoding="utf-8")

        reader.join(timeout=5)
        writer.join(timeout=5)

        assert not reader.is_alive(), "ActivityLogStore.read_tail did not finish"
        assert writer.exitcode == 0
        assert result["tail"] == (
            "[2026-05-05 12:00:00] first line\n"
            "[2026-05-05 12:00:01] second line complete"
        )
    finally:
        if writer.is_alive():
            writer.terminate()
            writer.join(timeout=5)
