"""Record when the last full queue run happened, for the web interface.

The web page can only report "last run" if something writes it down. The
scheduler in ``start.py`` brackets every full queue pass with
``mark_run_started`` and ``mark_run_finished``, and the queue page reads the
file back. Single-URL and single-playlist runs requested from the browser are
deliberately not recorded here: they process one item, not the queue, so
counting them as a run would make the schedule look like it had already run.

The file is small and rewritten in full, so it is replaced atomically under the
same kind of lock the other JSON state files use.
"""

from __future__ import annotations

import fcntl
import json
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from ..log_timezone import LOG_TIME_ZONE, local_now
from .file_locks import locked_text_file

RUN_STATE_FILE_NAME = "run_state.json"


class RunKind(StrEnum):
    """Why a full queue run started."""

    SCHEDULED = "scheduled"
    MANUAL = "manual"


@dataclass(frozen=True)
class RunState:
    """The most recent full queue run.

    Attributes
    ----------
    started_at:
        When the most recent run began, or ``None`` before the first run.
    finished_at:
        When the most recent finished run ended. ``None`` while the first run
        is still going or before any run has happened.
    kind:
        Whether that run was started by the schedule or by the Run button.
    is_running:
        True between ``mark_run_started`` and ``mark_run_finished``.
    """

    started_at: datetime | None = None
    finished_at: datetime | None = None
    kind: RunKind = RunKind.SCHEDULED
    is_running: bool = False


def run_state_file_for(data_dir: Path) -> Path:
    """Return the run-state path inside one data directory."""
    return data_dir / RUN_STATE_FILE_NAME


def _parse_timestamp(raw_value: object) -> datetime | None:
    """Return a stored ISO 8601 timestamp, or ``None`` when it is unusable."""
    if not isinstance(raw_value, str) or not raw_value:
        return None
    try:
        parsed = datetime.fromisoformat(raw_value)
    except ValueError:
        return None
    # A file hand-edited to drop the offset would otherwise break subtraction
    # against timezone-aware "now" values.
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=LOG_TIME_ZONE)
    return parsed


class RunStateStore:
    """Read and replace the last-run record under a cross-process lock.

    Parameters
    ----------
    state_file:
        JSON file holding the record.
    """

    def __init__(self, state_file: Path) -> None:
        self.state_file = state_file

    @property
    def _lock_file(self) -> Path:
        """Return the stable sibling lock path for the replaceable state file."""
        return self.state_file.with_name(f"{self.state_file.name}.lock")

    def _read_unlocked(self) -> RunState:
        """Read the record, treating an absent or damaged file as "no runs yet"."""
        if not self.state_file.exists():
            return RunState()
        try:
            raw_state = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return RunState()
        if not isinstance(raw_state, dict):
            return RunState()
        raw_kind = str(raw_state.get("kind", RunKind.SCHEDULED))
        kind = RunKind(raw_kind) if raw_kind in set(RunKind) else RunKind.SCHEDULED
        return RunState(
            started_at=_parse_timestamp(raw_state.get("started_at")),
            finished_at=_parse_timestamp(raw_state.get("finished_at")),
            kind=kind,
            is_running=bool(raw_state.get("is_running", False)),
        )

    def _write_unlocked(self, state: RunState) -> None:
        """Replace the file with one record, writing a sibling file first."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temporary_file = self.state_file.with_name(f".{self.state_file.name}.tmp")
        temporary_file.write_text(
            json.dumps(
                {
                    "started_at": (
                        state.started_at.isoformat() if state.started_at else ""
                    ),
                    "finished_at": (
                        state.finished_at.isoformat() if state.finished_at else ""
                    ),
                    "kind": str(state.kind),
                    "is_running": state.is_running,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary_file.replace(self.state_file)

    def load(self) -> RunState:
        """Return the saved record, or an empty record when nothing is saved."""
        with locked_text_file(self._lock_file, "a+", fcntl.LOCK_SH):
            return self._read_unlocked()

    def _update(self, **changes: object) -> RunState:
        """Apply changes to the saved record under one exclusive lock.

        Every mutation below is the same read-modify-write, so they share this
        one. Naming only the fields that change also means a new field on
        ``RunState`` is carried through without editing each method.

        Parameters
        ----------
        **changes:
            Fields to replace on the stored record.

        Returns
        -------
        RunState
            The record as it was written.
        """
        with locked_text_file(self._lock_file, "a+", fcntl.LOCK_EX):
            updated = replace(self._read_unlocked(), **changes)
            self._write_unlocked(updated)
            return updated

    def mark_run_started(self, kind: RunKind) -> None:
        """Record that a full queue run just began.

        Parameters
        ----------
        kind:
            Whether the schedule or the operator started this run.
        """
        self._update(started_at=local_now(), kind=kind, is_running=True)

    def mark_run_finished(self) -> None:
        """Record that the run in progress has ended."""
        self._update(finished_at=local_now(), is_running=False)

    def clear_stale_running_flag(self) -> RunState:
        """Drop a leftover "running" flag when the scheduler starts.

        A container killed mid-run leaves ``is_running`` set with no process
        behind it, which would make the interface refuse every later manual run.
        The scheduler is the only writer, so its own startup is the safe moment
        to clear the flag.

        Returns
        -------
        RunState
            The settled record, so the caller does not have to read the file
            again to see what it holds.
        """
        return self._update(is_running=False)
