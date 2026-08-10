"""Save web sign-in state in locked, safely replaced JSON files."""

from __future__ import annotations

import fcntl
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeAlias

from .file_locks import locked_text_file

JsonScalar: TypeAlias = float | int | str
JsonRecord: TypeAlias = dict[str, JsonScalar]
JsonState: TypeAlias = dict[str, JsonRecord]


class AuthStore:
    """Persist remembered sessions and login failures as separate JSON files.

    Parameters
    ----------
    session_file:
        JSON file mapping session identifiers to creation metadata.
    login_state_file:
        JSON file mapping client addresses to rate-limit metadata.
    """

    def __init__(self, session_file: Path, login_state_file: Path) -> None:
        self.session_file = session_file
        self.login_state_file = login_state_file

    @staticmethod
    def _lock_file(state_file: Path) -> Path:
        """Return stable sibling lock path for one replaceable JSON file."""
        return state_file.with_name(f"{state_file.name}.lock")

    @staticmethod
    def _read_unlocked(state_file: Path) -> JsonState:
        """Read one JSON mapping, treating absent or invalid content as empty."""
        if not state_file.exists():
            return {}
        try:
            raw_state = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw_state, dict):
            return {}

        # Keep only dictionary records used by session and login-limit code.
        # Ignore malformed entries without rejecting the healthy records.
        return {
            str(key): value
            for key, value in raw_state.items()
            if isinstance(value, dict)
        }

    @staticmethod
    def _write_unlocked(state_file: Path, state: JsonState) -> None:
        """Write one JSON state file through a temporary sibling, then replace it."""
        state_file.parent.mkdir(parents=True, exist_ok=True)
        temporary_file = state_file.with_name(f".{state_file.name}.tmp")
        temporary_file.write_text(
            json.dumps(state, indent=2),
            encoding="utf-8",
        )
        temporary_file.replace(state_file)

    def _read(self, state_file: Path) -> JsonState:
        """Read state while holding a shared process lock."""
        with locked_text_file(
            self._lock_file(state_file),
            "a+",
            fcntl.LOCK_SH,
        ):
            return self._read_unlocked(state_file)

    def _write(self, state_file: Path, state: JsonState) -> None:
        """Replace state while holding an exclusive process lock."""
        with locked_text_file(
            self._lock_file(state_file),
            "a+",
            fcntl.LOCK_EX,
        ):
            self._write_unlocked(state_file, state)

    def update_login_state(
        self,
        update: Callable[[JsonState], None],
    ) -> JsonState:
        """Apply one read-modify-write login-state transaction."""
        with locked_text_file(
            self._lock_file(self.login_state_file),
            "a+",
            fcntl.LOCK_EX,
        ):
            state = self._read_unlocked(self.login_state_file)
            update(state)
            self._write_unlocked(self.login_state_file, state)
            return state

    def load_login_state(self) -> JsonState:
        """Return current per-client failure and ban records."""
        return self._read(self.login_state_file)

    def save_login_state(self, state: JsonState) -> None:
        """Atomically replace current per-client failure and ban records."""
        self._write(self.login_state_file, state)

    def load_sessions(self, max_age_seconds: int) -> JsonState:
        """Return well-formed sessions that have not expired."""
        raw_sessions = self._read(self.session_file)
        current_time = time.time()
        valid_sessions: JsonState = {}
        for session_id, session in raw_sessions.items():
            try:
                created_at = float(session.get("created_at", 0))
            except (TypeError, ValueError):
                continue
            if current_time - created_at <= max_age_seconds:
                valid_sessions[session_id] = {"created_at": created_at}
        return valid_sessions

    def save_sessions(self, sessions: JsonState) -> None:
        """Atomically replace remembered login sessions."""
        self._write(self.session_file, sessions)
