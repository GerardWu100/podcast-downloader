"""Sync web UI login accounts from the operator's ``.env`` file.

The operator writes up to :data:`MAX_ACCOUNTS` plain account names and
passwords into ``.env`` in the data directory. The first account uses
``UI_USERNAME`` and ``UI_PASSWORD``; the second and third add a slot number, so
``UI_USERNAME_2`` with ``UI_PASSWORD_2`` and ``UI_USERNAME_3`` with
``UI_PASSWORD_3``. Every account can do the same things: the accounts exist to
give separate people separate passwords, not to grant different rights.

On every startup :func:`sync_ui_credentials` reads that file, hashes each
password with PBKDF2 (see ``src/passwords.py``), verifies the stored hashes
against the plain passwords (a self-test), and writes the result to
``.ui_credentials.json``. The operator never runs a hashing command.

File formats
------------
``.env``
    Plain ``KEY=VALUE`` lines. Blank lines and ``#`` comments are ignored.
    ``UI_USERNAME`` and ``UI_PASSWORD`` are required; the numbered pairs are
    optional.
``.ui_credentials.json``
    ``{"accounts": [{"username": "<plain account name>", "password_hash":
    "pbkdf2_sha256$..."}, ...]}`` written with owner-only (600) permissions.
    The accounts keep the slot order of ``.env``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple

from .passwords import hash_password, verify_password

ENV_FILENAME = ".env"
CREDENTIALS_FILENAME = ".ui_credentials.json"
ENV_USERNAME_KEY = "UI_USERNAME"
ENV_PASSWORD_KEY = "UI_PASSWORD"
# How many login accounts ``.env`` may define. Slot 1 uses the plain keys;
# later slots append their number to both key names.
MAX_ACCOUNTS = 3
# The password shipped in .env.example; startup warns when it is still in use.
EXAMPLE_PASSWORD = "changeme"
CREDENTIALS_FILE_PERMISSION_MODE = 0o600
SESSION_STATE_FILENAME = ".ui_sessions.json"


class StoredAccount(NamedTuple):
    """One login account as it is kept on disk.

    Attributes
    ----------
    username:
        Account name typed into the login form.
    password_hash:
        PBKDF2 hash of that account's password, in the format written by
        :func:`src.passwords.hash_password`.
    """

    username: str
    password_hash: str


def account_env_keys(slot: int) -> tuple[str, str]:
    """Return the ``.env`` key names for one account slot.

    Parameters
    ----------
    slot:
        1-based account number, from 1 to :data:`MAX_ACCOUNTS`.

    Returns
    -------
    tuple[str, str]
        ``(username key, password key)``. Slot 1 is ``("UI_USERNAME",
        "UI_PASSWORD")``; slot 2 is ``("UI_USERNAME_2", "UI_PASSWORD_2")``.
    """
    if slot == 1:
        return ENV_USERNAME_KEY, ENV_PASSWORD_KEY
    return f"{ENV_USERNAME_KEY}_{slot}", f"{ENV_PASSWORD_KEY}_{slot}"


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


def read_configured_accounts(
    env_values: dict[str, str],
) -> tuple[list[tuple[str, str]], list[str]]:
    """Collect the account name and password pairs set in ``.env``.

    Parameters
    ----------
    env_values:
        Parsed ``.env`` contents from :func:`parse_env_file`.

    Returns
    -------
    tuple[list[tuple[str, str]], list[str]]
        The accounts in slot order as ``(username, plain password)`` pairs, and
        a list of complaints about slots that were skipped. A slot is skipped
        when only one of its two values is set, or when its account name
        repeats one already accepted, because two accounts sharing a name would
        make the second unreachable.
    """
    accounts: list[tuple[str, str]] = []
    complaints: list[str] = []
    for slot in range(1, MAX_ACCOUNTS + 1):
        username_key, password_key = account_env_keys(slot)
        username = env_values.get(username_key, "").strip()
        password = env_values.get(password_key, "")
        if not username and not password.strip():
            continue
        if not username or not password.strip():
            complaints.append(
                f"{username_key} and {password_key} must both be set; "
                f"that account is ignored."
            )
            continue
        # HTTP Basic authentication reserves the first colon as the separator
        # between name and password. The web form could accept such a name, but
        # the extension and every other Basic client could never reproduce it.
        if ":" in username:
            complaints.append(
                f"{username_key} must not contain ':'; that account is ignored."
            )
            continue
        if any(username == accepted_name for accepted_name, _ in accounts):
            complaints.append(
                f"{username_key} repeats an account name already in use; "
                f"that account is ignored."
            )
            continue
        accounts.append((username, password))
    return accounts, complaints


def load_ui_accounts(credentials_file: Path) -> list[StoredAccount]:
    """Load the stored accounts and their password hashes.

    Parameters
    ----------
    credentials_file:
        Path to ``.ui_credentials.json``.

    Returns
    -------
    list[StoredAccount]
        Accounts holding a non-empty name and hash, in stored order. A missing,
        damaged, or empty file gives an empty list, which disables login rather
        than raising during a request.
    """
    try:
        raw = json.loads(credentials_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, dict):
        return []
    raw_accounts = raw.get("accounts", [])
    if not isinstance(raw_accounts, list):
        return []

    accounts: list[StoredAccount] = []
    for raw_account in raw_accounts:
        if not isinstance(raw_account, dict):
            continue
        username = raw_account.get("username", "")
        password_hash = raw_account.get("password_hash", "")
        if not isinstance(username, str) or not isinstance(password_hash, str):
            continue
        if not username or not password_hash:
            continue
        accounts.append(StoredAccount(username, password_hash))
    return accounts


def _write_credentials(credentials_file: Path, accounts: list[StoredAccount]) -> None:
    """Atomically write an owner-only credentials file."""
    credentials_file.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = credentials_file.with_name(f".{credentials_file.name}.tmp")
    payload = {
        "accounts": [
            {"username": account.username, "password_hash": account.password_hash}
            for account in accounts
        ]
    }
    temporary_file.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    temporary_file.chmod(CREDENTIALS_FILE_PERMISSION_MODE)
    temporary_file.replace(credentials_file)
    credentials_file.chmod(CREDENTIALS_FILE_PERMISSION_MODE)


def _disable_stale_credentials(credentials_file: Path) -> None:
    """Remove credentials that no longer have a valid ``.env`` source."""
    credentials_file.unlink(missing_ok=True)


def _revoke_existing_sessions(data_dir: Path) -> None:
    """Remove remembered sessions after authentication settings change."""
    (data_dir / SESSION_STATE_FILENAME).unlink(missing_ok=True)


def _reuse_or_hash(
    configured_accounts: list[tuple[str, str]],
    stored_accounts: list[StoredAccount],
) -> tuple[list[StoredAccount], bool]:
    """Match the configured accounts against what is already stored.

    Hashing is deliberately slow, so an account whose stored hash still
    verifies against its ``.env`` password keeps that hash instead of paying
    for a new one. Verifying the stored hash is also the per-boot self-test.

    Parameters
    ----------
    configured_accounts:
        ``(username, plain password)`` pairs read from ``.env``.
    stored_accounts:
        Accounts currently in ``.ui_credentials.json``.

    Returns
    -------
    tuple[list[StoredAccount], bool]
        The accounts to store, and whether they match what is already stored
        exactly, name for name and hash for hash. ``True`` means the file needs
        no rewrite and no session has to be dropped.
    """
    stored_hash_for_username = {
        account.username: account.password_hash for account in stored_accounts
    }
    accounts: list[StoredAccount] = []
    every_account_reused = True
    for username, password in configured_accounts:
        stored_hash = stored_hash_for_username.get(username, "")
        if stored_hash and verify_password(password, stored_hash):
            accounts.append(StoredAccount(username, stored_hash))
            continue
        every_account_reused = False
        accounts.append(StoredAccount(username, hash_password(password)))

    # A removed account still sits in the file until it is rewritten, so the
    # counts must agree as well before the file can be left alone.
    unchanged = every_account_reused and len(accounts) == len(stored_accounts)
    return accounts, unchanged


def sync_ui_credentials(data_dir: Path) -> str:
    """Refresh ``.ui_credentials.json`` from ``.env`` and self-test the hashes.

    Reads up to :data:`MAX_ACCOUNTS` account slots from ``<data_dir>/.env``.
    Accounts whose stored hash already matches their ``.env`` password are left
    as they are, and that check doubles as the per-boot self-test. Otherwise
    the file is rewritten, remembered sessions are dropped so a removed or
    changed account cannot stay signed in, and every new hash is verified
    before success is reported.

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

    configured_accounts, complaints = read_configured_accounts(parse_env_file(env_file))
    complaint_text = "".join(f" WARNING: {complaint}" for complaint in complaints)

    if not configured_accounts:
        _disable_stale_credentials(credentials_file)
        _revoke_existing_sessions(data_dir)
        return (
            f"{env_file} is missing {ENV_USERNAME_KEY} or {ENV_PASSWORD_KEY}; "
            f"web UI login stays unconfigured.{complaint_text}"
        )

    if any(password == EXAMPLE_PASSWORD for _, password in configured_accounts):
        complaint_text += (
            f" WARNING: a password is still the example value "
            f"'{EXAMPLE_PASSWORD}'; change it in {env_file}."
        )

    accounts, unchanged = _reuse_or_hash(
        configured_accounts,
        load_ui_accounts(credentials_file),
    )
    account_names = ", ".join(f"'{account.username}'" for account in accounts)

    if unchanged:
        return (
            f"UI credentials for {account_names} verified against "
            f"{env_file}.{complaint_text}"
        )

    _write_credentials(credentials_file, accounts)
    _revoke_existing_sessions(data_dir)

    # Self-test: re-read what was written and prove every hash verifies.
    written_accounts = load_ui_accounts(credentials_file)
    written_hash_for_username = {
        account.username: account.password_hash for account in written_accounts
    }
    for username, password in configured_accounts:
        written_hash = written_hash_for_username.get(username, "")
        if not written_hash or not verify_password(password, written_hash):
            raise RuntimeError(
                f"Credential self-test failed after writing {credentials_file}."
            )

    return (
        f"Hashed UI passwords for {account_names} from {env_file} and "
        f"passed the hash self-test.{complaint_text}"
    )
