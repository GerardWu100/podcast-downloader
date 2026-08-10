"""Contract tests for locked authentication JSON persistence."""

from __future__ import annotations

import json
import time
from pathlib import Path

from src.state.auth_store import AuthStore


def test_auth_store_filters_expired_and_malformed_sessions(tmp_path: Path) -> None:
    """Session reads should expose only valid records within their lifetime."""
    session_file = tmp_path / ".ui_sessions.json"
    current_time = time.time()
    session_file.write_text(
        json.dumps(
            {
                "valid": {"created_at": current_time - 60},
                "expired": {"created_at": current_time - 10_000},
                "malformed": {"created_at": "not-a-time"},
            }
        ),
        encoding="utf-8",
    )
    store = AuthStore(
        session_file=session_file,
        login_state_file=tmp_path / ".login_state.json",
    )

    sessions = store.load_sessions(max_age_seconds=300)

    assert sessions == {"valid": {"created_at": current_time - 60}}


def test_auth_store_login_update_is_atomic_and_leaves_no_temporary_file(
    tmp_path: Path,
) -> None:
    """One update should persist complete JSON through sibling replacement."""
    login_state_file = tmp_path / ".login_state.json"
    store = AuthStore(
        session_file=tmp_path / ".ui_sessions.json",
        login_state_file=login_state_file,
    )

    store.update_login_state(
        lambda state: state.update({"203.0.113.7": {"failed": 1, "last_failed": 100.0}})
    )

    assert store.load_login_state() == {
        "203.0.113.7": {"failed": 1, "last_failed": 100.0}
    }
    assert not (tmp_path / "..login_state.json.tmp").exists()
    assert login_state_file.stat().st_mode & 0o777 == 0o600


def test_auth_store_rejects_future_and_non_finite_sessions(tmp_path: Path) -> None:
    """Persisted sessions must have a finite creation time no later than now."""
    session_file = tmp_path / ".ui_sessions.json"
    current_time = time.time()
    session_file.write_text(
        json.dumps(
            {
                "future": {"created_at": current_time + 60},
                "infinite": {"created_at": float("inf")},
                "valid": {"created_at": current_time - 60},
            }
        ),
        encoding="utf-8",
    )
    store = AuthStore(
        session_file=session_file,
        login_state_file=tmp_path / ".login_state.json",
    )

    sessions = store.load_sessions(max_age_seconds=300)

    assert sessions == {"valid": {"created_at": current_time - 60}}
    assert session_file.stat().st_mode & 0o777 == 0o600
