"""Sync web UI login credentials from the operator's ``.env`` file.

The operator writes a plain account name and password into ``.env`` in the
data directory. On every startup :func:`sync_ui_credentials` reads that file,
hashes the password with PBKDF2 (see ``src/passwords.py``), verifies the
stored hash against the plain password (a self-test), and writes the result
to ``.ui_credentials.json``. The operator never runs a hashing command.

File formats
------------
``.env``
    Plain ``KEY=VALUE`` lines. Blank lines and ``#`` comments are ignored.
    Required keys: ``UI_USERNAME`` and ``UI_PASSWORD``.
``.ui_credentials.json``
    ``{"username": "<plain account name>", "password_hash": "pbkdf2_sha256$..."}``
    written with owner-only (600) permissions.
"""

from __future__ import annotations

import json
from pathlib import Path

from .passwords import hash_password, verify_password

ENV_FILENAME = ".env"
CREDENTIALS_FILENAME = ".ui_credentials.json"
ENV_USERNAME_KEY = "UI_USERNAME"
ENV_PASSWORD_KEY = "UI_PASSWORD"
# The password shipped in .env.example; startup warns when it is still in use.
EXAMPLE_PASSWORD = "changeme"
CREDENTIALS_FILE_PERMISSION_MODE = 0o600
SESSION_STATE_FILENAME = ".ui_sessions.json"


def parse_env_file(env_file: Path) -> dict[str, str]:
    """Parse a simple ``KEY=VALUE`` environment file.

    Parameters
    ----------
    env_file:
        Path to the ``.env`` file.

    Returns
    -------
    dict[str, str]
        Mapping of keys to values. Blank lines and ``#`` comment lines are
        skipped, values are split on the first ``=`` only, and one pair of
        matching single or double quotes around a value is removed.
    """
    values: dict[str, str] = {}
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, raw_value = line.partition("=")
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def load_ui_credentials(credentials_file: Path) -> tuple[str, str] | None:
    """Load the stored account name and password hash.

    Parameters
    ----------
    credentials_file:
        Path to ``.ui_credentials.json``.

    Returns
    -------
    tuple[str, str] | None
        ``(username, password_hash)`` when the file exists and holds both
        non-empty values, otherwise ``None``.
    """
    try:
        raw = json.loads(credentials_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    username = raw.get("username", "")
    password_hash = raw.get("password_hash", "")
    if not isinstance(username, str) or not isinstance(password_hash, str):
        return None
    if not username or not password_hash:
        return None
    return username, password_hash


def _write_credentials(
    credentials_file: Path, username: str, password_hash: str
) -> None:
    """Atomically write an owner-only credentials file."""
    credentials_file.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = credentials_file.with_name(f".{credentials_file.name}.tmp")
    temporary_file.write_text(
        json.dumps({"username": username, "password_hash": password_hash}) + "\n",
        encoding="utf-8",
    )
    temporary_file.chmod(CREDENTIALS_FILE_PERMISSION_MODE)
    temporary_file.replace(credentials_file)
    credentials_file.chmod(CREDENTIALS_FILE_PERMISSION_MODE)


def _disable_stale_credentials(credentials_file: Path) -> None:
    """Remove credentials that no longer have a valid ``.env`` source."""
    credentials_file.unlink(missing_ok=True)


def _revoke_existing_sessions(data_dir: Path) -> None:
    """Remove remembered sessions after authentication settings change."""
    (data_dir / SESSION_STATE_FILENAME).unlink(missing_ok=True)


def sync_ui_credentials(data_dir: Path) -> str:
    """Refresh ``.ui_credentials.json`` from ``.env`` and self-test the hash.

    Reads ``UI_USERNAME`` and ``UI_PASSWORD`` from ``<data_dir>/.env``. When
    the existing stored hash already matches the ``.env`` password, the file
    is left untouched (that check doubles as the per-boot self-test). When it
    does not match — first boot or a changed password — a new hash is written
    and then verified against the plain password before reporting success.

    Parameters
    ----------
    data_dir:
        Directory holding ``.env`` and ``.ui_credentials.json``.

    Returns
    -------
    str
        Human-readable status line for the startup log. Missing or invalid
        ``.env`` files produce a warning message instead of an exception so
        the downloader can keep running with the web UI login disabled.

    Raises
    ------
    RuntimeError
        If a freshly written hash fails verification. This indicates a bug,
        never an operator mistake.
    """
    env_file = data_dir / ENV_FILENAME
    credentials_file = data_dir / CREDENTIALS_FILENAME

    if not env_file.exists():
        _disable_stale_credentials(credentials_file)
        _revoke_existing_sessions(data_dir)
        return (
            f"No {ENV_FILENAME} found in {data_dir}; web UI login stays "
            f"unconfigured until {ENV_USERNAME_KEY} and {ENV_PASSWORD_KEY} are set."
        )

    env_values = parse_env_file(env_file)
    username = env_values.get(ENV_USERNAME_KEY, "").strip()
    password = env_values.get(ENV_PASSWORD_KEY, "")
    if not username or not password.strip():
        _disable_stale_credentials(credentials_file)
        _revoke_existing_sessions(data_dir)
        return (
            f"{env_file} is missing {ENV_USERNAME_KEY} or {ENV_PASSWORD_KEY}; "
            "web UI login stays unconfigured."
        )

    default_password_warning = (
        f" WARNING: {ENV_PASSWORD_KEY} is still the example value "
        f"'{EXAMPLE_PASSWORD}'; change it in {env_file}."
        if password == EXAMPLE_PASSWORD
        else ""
    )

    # Matching stored credentials mean nothing to do. Verifying the stored
    # hash against the .env password on every boot is the ongoing self-test.
    stored = load_ui_credentials(credentials_file)
    if stored is not None:
        stored_username, stored_hash = stored
        if stored_username == username and verify_password(password, stored_hash):
            return (
                f"UI credentials for '{username}' verified against "
                f"{env_file}.{default_password_warning}"
            )

    _write_credentials(credentials_file, username, hash_password(password))
    _revoke_existing_sessions(data_dir)

    # Self-test: re-read what was written and prove the hash verifies.
    written = load_ui_credentials(credentials_file)
    if written is None or not verify_password(password, written[1]):
        raise RuntimeError(
            f"Credential self-test failed after writing {credentials_file}."
        )

    return (
        f"Hashed UI password for '{username}' from {env_file} and "
        f"passed the hash self-test.{default_password_warning}"
    )
