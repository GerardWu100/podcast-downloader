"""Shared locks and line-file helpers for UTF-8 state files."""

from __future__ import annotations

import fcntl
import os
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TextIO

COMMENT_PREFIX = "#"


@contextmanager
def locked_text_file(path: Path, mode: str, lock_type: int) -> Iterator[TextIO]:
    """Open a text file and hold its process-shared ``fcntl`` lock.

    Parameters
    ----------
    path:
        File to open. Parent directories are created before opening.
    mode:
        Standard Python file mode, such as ``"r"``, ``"a+"``, or ``"r+"``.
    lock_type:
        ``fcntl.LOCK_SH`` for shared reads or ``fcntl.LOCK_EX`` for exclusive
        writes.

    Yields
    ------
    typing.TextIO
        Open UTF-8 text file handle with the requested lock held.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open(mode, encoding="utf-8") as file_handle:
        fcntl.flock(file_handle.fileno(), lock_type)
        try:
            yield file_handle
        finally:
            fcntl.flock(file_handle.fileno(), fcntl.LOCK_UN)


class LockedLineFile:
    """A locked state file holding one entry per line.

    All of this project's state files (``urls.txt``, ``downloaded_urls.txt``,
    ``bypass_age_check_urls.txt``, ``activity.log``) are plain line-per-entry
    text files that an operator may hand-edit. An editor can leave the last
    line without a trailing newline. Appending straight to the end would then
    splice the new entry onto that line and destroy both entries, so every
    append through this class writes the missing separator first.

    The check costs one ``pread`` of the file's final byte, so appending to a
    long file such as ``activity.log`` does not have to read the whole file.
    """

    def __init__(self, file_handle: TextIO) -> None:
        """Wrap an already opened and locked read-write text handle."""
        self.file_handle = file_handle
        self._separator_is_missing = self._final_newline_is_missing()

    def _final_newline_is_missing(self) -> bool:
        """Return whether the file is non-empty and does not end in a newline."""
        byte_count = os.fstat(self.file_handle.fileno()).st_size
        if byte_count == 0:
            return False
        # `pread` reads at an absolute offset without moving the handle; a
        # text-mode handle cannot reliably use `seek(-1, 2)`.
        return os.pread(self.file_handle.fileno(), 1, byte_count - 1) != b"\n"

    def entries(self, *, skip_comments: bool = False) -> list[str]:
        """Return stripped, non-blank lines in file order.

        Parameters
        ----------
        skip_comments:
            When true, lines starting with ``#`` are dropped as well. Only the
            operator-editable queue and bypass files support comments.
        """
        self.file_handle.seek(0)
        stripped_lines = (line.strip() for line in self.file_handle)
        return [
            line
            for line in stripped_lines
            if line and not (skip_comments and line.startswith(COMMENT_PREFIX))
        ]

    def append_line(self, text: str) -> None:
        """Append one newline-terminated line, repairing a missing separator."""
        self.file_handle.seek(0, 2)
        if self._separator_is_missing:
            self.file_handle.write("\n")
            self._separator_is_missing = False
        self.file_handle.write(f"{text}\n")
        self.file_handle.flush()

    def rewrite_lines(self, lines: Iterable[str]) -> None:
        """Replace the whole file with newline-terminated ``lines``."""
        self.file_handle.seek(0)
        for line in lines:
            self.file_handle.write(f"{line}\n")
        self.file_handle.truncate()
        self.file_handle.flush()
        # Every written line ends with a newline, so a later append is safe.
        self._separator_is_missing = False


@contextmanager
def locked_line_file(path: Path, mode: str, lock_type: int) -> Iterator[LockedLineFile]:
    """Open a line-oriented state file under a lock, creating it if absent.

    Use a read-write mode (``"r+"`` or ``"a+"``) so entries can be read for
    duplicate detection before appending.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    with locked_text_file(path, mode, lock_type) as file_handle:
        yield LockedLineFile(file_handle)
