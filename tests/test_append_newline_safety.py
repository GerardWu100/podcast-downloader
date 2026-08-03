"""Regression tests for appending to state files that lack a final newline.

State files such as ``urls.txt`` are meant to be hand-edited, and an editor may
leave the last line without a trailing newline. Appending must not splice the
new entry onto that line and lose both entries.
"""

from __future__ import annotations

import logging
from pathlib import Path

from src.state.archive_store import ArchiveStore
from src.state.bypass_store import BypassStore
from src.state.queue_store import QueueStore

_LOGGER = logging.getLogger("test")

_URL_A = "https://www.youtube.com/watch?v=AAAAAAAAAAA"
_URL_B = "https://www.youtube.com/watch?v=BBBBBBBBBBB"


def test_queue_append_repairs_missing_final_newline(tmp_path: Path) -> None:
    """Appending to a queue file with no final newline keeps both URLs."""
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(_URL_A, encoding="utf-8")  # deliberately no trailing "\n"

    store = QueueStore(urls_file, _LOGGER)
    added = store.append_urls([_URL_B])

    assert added == 1
    assert store.read_urls() == [_URL_A, _URL_B]
    assert urls_file.read_text(encoding="utf-8") == f"{_URL_A}\n{_URL_B}\n"


def test_queue_append_keeps_single_newline_when_already_terminated(
    tmp_path: Path,
) -> None:
    """A well-formed queue file gains no extra blank line on append."""
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(f"{_URL_A}\n", encoding="utf-8")

    store = QueueStore(urls_file, _LOGGER)
    store.append_urls([_URL_B])

    assert urls_file.read_text(encoding="utf-8") == f"{_URL_A}\n{_URL_B}\n"


def test_bypass_add_repairs_missing_final_newline(tmp_path: Path) -> None:
    """Adding a bypass URL to a file with no final newline keeps both URLs."""
    bypass_file = tmp_path / "bypass_age_check_urls.txt"
    bypass_file.write_text(_URL_A, encoding="utf-8")

    store = BypassStore(bypass_file, _LOGGER)
    store.add(_URL_B)

    assert store.load() == {_URL_A, _URL_B}
    assert bypass_file.read_text(encoding="utf-8") == f"{_URL_A}\n{_URL_B}\n"


def test_archive_append_repairs_missing_final_newline(tmp_path: Path) -> None:
    """Appending an archived URL to a file with no final newline keeps both."""
    archive_file = tmp_path / "downloaded_urls.txt"
    archive_file.write_text(_URL_A, encoding="utf-8")

    store = ArchiveStore(archive_file, _LOGGER)
    assert store.append(_URL_B) is True

    assert store.load() == {_URL_A, _URL_B}
    assert archive_file.read_text(encoding="utf-8") == f"{_URL_A}\n{_URL_B}\n"
