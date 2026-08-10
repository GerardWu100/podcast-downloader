"""Tests for the .env driven UI credential sync."""

from __future__ import annotations

import json
from pathlib import Path

from src.credentials import (
    CREDENTIALS_FILENAME,
    load_ui_credentials,
    parse_env_file,
    sync_ui_credentials,
)
from src.passwords import is_password_hash, verify_password


def _write_env(data_dir: Path, username: str, password: str) -> Path:
    env_file = data_dir / ".env"
    env_file.write_text(
        f"UI_USERNAME={username}\nUI_PASSWORD={password}\n", encoding="utf-8"
    )
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
    _write_env(tmp_path, "alice", "correct-password")

    message = sync_ui_credentials(tmp_path)

    credentials_file = tmp_path / CREDENTIALS_FILENAME
    stored = load_ui_credentials(credentials_file)
    assert stored is not None
    username, password_hash = stored
    assert username == "alice"
    assert is_password_hash(password_hash) is True
    assert verify_password("correct-password", password_hash) is True
    assert oct(credentials_file.stat().st_mode & 0o777) == "0o600"
    assert "self-test" in message


def test_sync_leaves_matching_credentials_untouched(tmp_path: Path) -> None:
    """A second sync with the same .env should keep the same salt and hash."""
    _write_env(tmp_path, "alice", "correct-password")
    sync_ui_credentials(tmp_path)
    first_contents = (tmp_path / CREDENTIALS_FILENAME).read_text(encoding="utf-8")

    message = sync_ui_credentials(tmp_path)

    second_contents = (tmp_path / CREDENTIALS_FILENAME).read_text(encoding="utf-8")
    assert second_contents == first_contents
    assert "verified" in message


def test_sync_rehashes_when_env_password_changes(tmp_path: Path) -> None:
    """Editing .env and restarting should replace the stored hash."""
    _write_env(tmp_path, "alice", "old-password")
    sync_ui_credentials(tmp_path)

    _write_env(tmp_path, "alice", "new-password")
    sync_ui_credentials(tmp_path)

    stored = load_ui_credentials(tmp_path / CREDENTIALS_FILENAME)
    assert stored is not None
    assert verify_password("new-password", stored[1]) is True
    assert verify_password("old-password", stored[1]) is False


def test_sync_without_env_file_reports_unconfigured(tmp_path: Path) -> None:
    """A missing .env should warn instead of raising or writing credentials."""
    message = sync_ui_credentials(tmp_path)

    assert "unconfigured" in message
    assert not (tmp_path / CREDENTIALS_FILENAME).exists()


def test_sync_with_blank_values_reports_unconfigured(tmp_path: Path) -> None:
    """Blank username or password values should not produce a credentials file."""
    _write_env(tmp_path, "", "correct-password")

    message = sync_ui_credentials(tmp_path)

    assert "unconfigured" in message
    assert not (tmp_path / CREDENTIALS_FILENAME).exists()


def test_sync_warns_when_example_password_still_in_use(tmp_path: Path) -> None:
    """Keeping the .env.example password should produce a startup warning."""
    _write_env(tmp_path, "admin", "changeme")

    message = sync_ui_credentials(tmp_path)

    assert "WARNING" in message


def test_load_ui_credentials_rejects_malformed_files(tmp_path: Path) -> None:
    """Missing, non-JSON, and incomplete files should all read as unconfigured."""
    credentials_file = tmp_path / CREDENTIALS_FILENAME

    assert load_ui_credentials(credentials_file) is None

    credentials_file.write_text("not json", encoding="utf-8")
    assert load_ui_credentials(credentials_file) is None

    credentials_file.write_text(json.dumps({"username": "alice"}), encoding="utf-8")
    assert load_ui_credentials(credentials_file) is None
