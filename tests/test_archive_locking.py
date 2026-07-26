"""Regression tests for downloaded archive locking behavior."""

from __future__ import annotations

import fcntl
import logging
import multiprocessing
from pathlib import Path
import threading
import time

from src.state.archive_store import ArchiveStore


def _lock_then_rewrite_archive(
    archive_file: str,
    ready_file: str,
    release_file: str,
) -> None:
    """Hold an exclusive lock on the archive, then replace its contents."""
    archive_path = Path(archive_file)
    ready_path = Path(ready_file)
    release_path = Path(release_file)

    with open(archive_path, "r+", encoding="utf-8") as file_handle:
        fcntl.flock(file_handle.fileno(), fcntl.LOCK_EX)
        ready_path.write_text("ready", encoding="utf-8")

        while not release_path.exists():
            time.sleep(0.01)

        file_handle.seek(0)
        file_handle.truncate()
        file_handle.write("https://www.youtube.com/watch?v=new456\n")
        file_handle.flush()

        fcntl.flock(file_handle.fileno(), fcntl.LOCK_UN)


def test_archive_store_load_waits_for_lock_and_reads_latest_content(
    tmp_path,
) -> None:
    """Archive reads should block behind writers instead of racing stale state."""
    archive_file = tmp_path / "downloaded_urls.txt"
    archive_file.write_text(
        "https://www.youtube.com/watch?v=abc123\n", encoding="utf-8"
    )
    ready_file = tmp_path / "ready"
    release_file = tmp_path / "release"

    process = multiprocessing.Process(
        target=_lock_then_rewrite_archive,
        args=(str(archive_file), str(ready_file), str(release_file)),
    )
    process.start()

    try:
        deadline = time.time() + 5
        while not ready_file.exists() and time.time() < deadline:
            time.sleep(0.01)

        assert ready_file.exists(), (
            "helper process did not acquire the archive lock in time"
        )

        result: dict[str, set[str]] = {}
        store = ArchiveStore(archive_file, logging.getLogger("test"))

        def load_in_thread() -> None:
            result["urls"] = store.load()

        thread = threading.Thread(target=load_in_thread)
        thread.start()

        time.sleep(0.1)
        release_file.write_text("release", encoding="utf-8")

        thread.join(timeout=5)
        process.join(timeout=5)

        assert not thread.is_alive(), "ArchiveStore.load did not finish"
        assert process.exitcode == 0
        assert result["urls"] == {"https://www.youtube.com/watch?v=new456"}
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)


def test_archive_store_append_waits_for_lock_and_preserves_new_entry(
    tmp_path,
) -> None:
    """Archive appends should serialize with concurrent rewrites instead of being lost."""
    archive_file = tmp_path / "downloaded_urls.txt"
    archive_file.write_text(
        "https://www.youtube.com/watch?v=abc123\n", encoding="utf-8"
    )
    ready_file = tmp_path / "ready"
    release_file = tmp_path / "release"

    process = multiprocessing.Process(
        target=_lock_then_rewrite_archive,
        args=(str(archive_file), str(ready_file), str(release_file)),
    )
    process.start()

    try:
        deadline = time.time() + 5
        while not ready_file.exists() and time.time() < deadline:
            time.sleep(0.01)

        assert ready_file.exists(), (
            "helper process did not acquire the archive lock in time"
        )

        result: dict[str, bool] = {}
        store = ArchiveStore(archive_file, logging.getLogger("test"))

        def append_in_thread() -> None:
            result["added"] = store.append("https://www.youtube.com/watch?v=late789")

        thread = threading.Thread(target=append_in_thread)
        thread.start()

        time.sleep(0.1)
        release_file.write_text("release", encoding="utf-8")

        thread.join(timeout=5)
        process.join(timeout=5)

        assert not thread.is_alive(), "ArchiveStore.append did not finish"
        assert process.exitcode == 0
        assert result["added"] is True
        assert archive_file.read_text(encoding="utf-8") == (
            "https://www.youtube.com/watch?v=new456\n"
            "https://www.youtube.com/watch?v=late789\n"
        )
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
