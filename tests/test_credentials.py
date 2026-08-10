"""Tests for the .env driven UI credential sync."""

from __future__ import annotations

import json
from pathlib import Path

from src.credentials import (
    CREDENTIALS_FILENAME,
    load_ui_accounts,
    parse_env_file,
    sync_ui_credentials,
)
from src.passwords import is_password_hash, verify_password


def _write_env(data_dir: Path, *accounts: tuple[str, str]) -> Path:
    """Write ``.env`` with one ``KEY=VALUE`` pair per account slot.

    Parameters
    ----------
    data_dir:
        Directory that stands in for the operator's data directory.
    *accounts:
        ``(username, password)`` per slot, in slot order. Slot 1 uses the plain
        keys; later slots append their number.

    Returns
    -------
    Path
        Path of the written ``.env`` file.
    """
    lines: list[str] = []
    for slot, (username, password) in enumerate(accounts, start=1):
        suffix = "" if slot == 1 else f"_{slot}"
        lines.append(f"UI_USERNAME{suffix}={username}")
        lines.append(f"UI_PASSWORD{suffix}={password}")
    env_file = data_dir / ".env"
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return env_file


def test_parse_env_file_handles_comments_quotes_and_blank_lines(
    tmp_path: Path,
) -> None:
    """Parsing should skip noise lines, split on the first =, and strip quotes."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n"
        "\n"
        "UI_USERNAME=alice\n"
        'UI_PASSWORD="p=ss word"\n'
        "not a key value line\n",
        encoding="utf-8",
    )

    values = parse_env_file(env_file)

    assert values == {"UI_USERNAME": "alice", "UI_PASSWORD": "p=ss word"}


def test_sync_creates_hashed_credentials_and_passes_self_test(
    tmp_path: Path,
) -> None:
    """First sync should write a verified hash file with owner-only access."""
    _write_env(tmp_path, ("alice", "correct-password"))

    message = sync_ui_credentials(tmp_path)

    credentials_file = tmp_path / CREDENTIALS_FILENAME
    stored = load_ui_accounts(credentials_file)
    assert len(stored) == 1
    assert stored[0].username == "alice"
    assert is_password_hash(stored[0].password_hash) is True
    assert verify_password("correct-password", stored[0].password_hash) is True
    assert oct(credentials_file.stat().st_mode & 0o777) == "0o600"
    assert "self-test" in message


def test_sync_stores_every_configured_account(tmp_path: Path) -> None:
    """All three slots should become accounts, each with its own hash."""
    _write_env(
        tmp_path,
        ("alice", "alice-password"),
        ("bob", "bob-password"),
        ("carol", "carol-password"),
    )

    sync_ui_credentials(tmp_path)

    stored = load_ui_accounts(tmp_path / CREDENTIALS_FILENAME)
    assert [account.username for account in stored] == ["alice", "bob", "carol"]
    assert verify_password("bob-password", stored[1].password_hash) is True
    assert verify_password("bob-password", stored[2].password_hash) is False


def test_sync_ignores_half_filled_and_repeated_slots(tmp_path: Path) -> None:
    """An account without a password, or with a used name, must be skipped."""
    (tmp_path / ".env").write_text(
        "UI_USERNAME=alice\n"
        "UI_PASSWORD=alice-password\n"
        "UI_USERNAME_2=bob\n"
        "UI_PASSWORD_2=\n"
        "UI_USERNAME_3=alice\n"
        "UI_PASSWORD_3=another-password\n",
        encoding="utf-8",
    )

    message = sync_ui_credentials(tmp_path)

    stored = load_ui_accounts(tmp_path / CREDENTIALS_FILENAME)
    assert [account.username for account in stored] == ["alice"]
    assert verify_password("alice-password", stored[0].password_hash) is True
    assert "WARNING" in message


def test_sync_leaves_matching_credentials_untouched(tmp_path: Path) -> None:
    """A second sync with the same .env should keep the same salts and hashes."""
    _write_env(tmp_path, ("alice", "correct-password"), ("bob", "bob-password"))
    sync_ui_credentials(tmp_path)
    first_contents = (tmp_path / CREDENTIALS_FILENAME).read_text(encoding="utf-8")

    message = sync_ui_credentials(tmp_path)

    second_contents = (tmp_path / CREDENTIALS_FILENAME).read_text(encoding="utf-8")
    assert second_contents == first_contents
    assert "verified" in message


def test_sync_rehashes_when_env_password_changes(tmp_path: Path) -> None:
    """Editing .env and restarting should replace the stored hash."""
    _write_env(tmp_path, ("alice", "old-password"))
    sync_ui_credentials(tmp_path)

    session_file = tmp_path / ".ui_sessions.json"
    session_file.write_text('{"old-session": {"created_at": 1}}', encoding="utf-8")
    _write_env(tmp_path, ("alice", "new-password"))
    sync_ui_credentials(tmp_path)

    stored = load_ui_accounts(tmp_path / CREDENTIALS_FILENAME)
    assert verify_password("new-password", stored[0].password_hash) is True
    assert verify_password("old-password", stored[0].password_hash) is False
    assert not session_file.exists()


def test_sync_drops_a_removed_account_and_its_sessions(tmp_path: Path) -> None:
    """Deleting an account from .env must revoke it on the next startup."""
    _write_env(tmp_path, ("alice", "alice-password"), ("bob", "bob-password"))
    sync_ui_credentials(tmp_path)

    session_file = tmp_path / ".ui_sessions.json"
    session_file.write_text('{"old-session": {"created_at": 1}}', encoding="utf-8")
    _write_env(tmp_path, ("alice", "alice-password"))
    sync_ui_credentials(tmp_path)

    stored = load_ui_accounts(tmp_path / CREDENTIALS_FILENAME)
    assert [account.username for account in stored] == ["alice"]
    assert not session_file.exists()


def test_sync_without_env_file_reports_unconfigured(tmp_path: Path) -> None:
    """A missing .env should warn instead of raising or writing credentials."""
    message = sync_ui_credentials(tmp_path)

    assert "unconfigured" in message
    assert not (tmp_path / CREDENTIALS_FILENAME).exists()


def test_sync_with_blank_values_reports_unconfigured(tmp_path: Path) -> None:
    """Blank username or password values should not produce a credentials file."""
    _write_env(tmp_path, ("", "correct-password"))

    message = sync_ui_credentials(tmp_path)

    assert "unconfigured" in message
    assert not (tmp_path / CREDENTIALS_FILENAME).exists()


def test_sync_warns_when_example_password_still_in_use(tmp_path: Path) -> None:
    """Keeping the .env.example password should produce a startup warning."""
    _write_env(tmp_path, ("admin", "changeme"))

    message = sync_ui_credentials(tmp_path)

    assert "WARNING" in message


def test_load_ui_accounts_rejects_malformed_files(tmp_path: Path) -> None:
    """Missing, non-JSON, and incomplete files should all read as unconfigured."""
    credentials_file = tmp_path / CREDENTIALS_FILENAME

    assert load_ui_accounts(credentials_file) == []

    credentials_file.write_text("not json", encoding="utf-8")
    assert load_ui_accounts(credentials_file) == []

    credentials_file.write_text(
        json.dumps({"accounts": [{"username": "alice"}]}), encoding="utf-8"
    )
    assert load_ui_accounts(credentials_file) == []

    credentials_file.write_text("[]", encoding="utf-8")
    assert load_ui_accounts(credentials_file) == []


def test_missing_env_disables_previously_valid_credentials(tmp_path: Path) -> None:
    """Deleting ``.env`` must not leave the old password active."""
    env_file = _write_env(tmp_path, ("alice", "correct-password"))
    sync_ui_credentials(tmp_path)
    env_file.unlink()

    message = sync_ui_credentials(tmp_path)

    assert "unconfigured" in message
    assert not (tmp_path / CREDENTIALS_FILENAME).exists()


def test_blank_env_disables_previously_valid_credentials(tmp_path: Path) -> None:
    """Invalid replacement settings must fail closed instead of using stale data."""
    _write_env(tmp_path, ("alice", "correct-password"))
    sync_ui_credentials(tmp_path)
    _write_env(tmp_path, ("", "replacement-password"))

    sync_ui_credentials(tmp_path)

    assert not (tmp_path / CREDENTIALS_FILENAME).exists()
