"""Shared advisory locking helper for UTF-8 text state files."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
from pathlib import Path
from typing import Iterator, TextIO


@contextmanager
def locked_text_file(path: Path, mode: str, lock_type: int) -> Iterator[TextIO]:
    """Open a text file and hold an advisory ``fcntl`` lock.

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
