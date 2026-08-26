"""Account checking and the failed-attempt ban ledger, shared by every client.

Two things sign in with the same accounts from ``.env``: the login form in the
browser, and the JSON API that the browser extension calls. Both must apply the
same rules, or the API would quietly become the weaker door -- no ban after
repeated failures, or a wrong username answering faster than a wrong password
and so leaking which names exist.

The ban ledger lives in ``.login_state.json`` through ``AuthStore``. It maps a
client address to how many times it has failed recently and until when it is
banned. Records that can no longer change any decision are dropped on the next
failure, so the file cannot grow without limit.
"""

from __future__ import annotations

import math
import secrets
import threading
import time
from enum import StrEnum

from ..credentials import StoredAccount
from ..passwords import verify_password
from ..state.auth_store import AuthStore

MAX_FAILED_ATTEMPTS = 5
FAIL_WINDOW_SECONDS = 10 * 60
BAN_SECONDS = 15 * 60
# A failure record is useless once its window has passed and its ban has
# expired, so records older than this are dropped on the next failed attempt.
FAILURE_RECORD_LIFETIME_SECONDS = FAIL_WINDOW_SECONDS + BAN_SECONDS
# Longest name or password worth reading. Real credentials are far shorter, and
# stopping here keeps an absurd submission from reaching the password hash.
MAX_CREDENTIAL_LENGTH = 1000

# One lock for the whole process. The login form and the API both read the ban
# ledger, decide, and write it back; without a shared lock two simultaneous
# failures could each read "1 failure" and both write "2".
LOGIN_STATE_LOCK = threading.Lock()


class CredentialCheck(StrEnum):
    """Outcome of one sign-in attempt.

    The values are the ``?msg=`` keys the login page already understands, so
    the form route can redirect with the outcome unchanged.
    """

    NO_ACCOUNTS_CONFIGURED = "unconfigured"
    OVERSIZED = "request"
    BANNED = "banned"
    WRONG = "bad_credentials"
    ACCEPTED = "ok"


def check_credentials(
    username: str,
    password: str,
    *,
    accounts: list[StoredAccount],
    auth_store: AuthStore,
    client_address: str,
) -> CredentialCheck:
    """Check one name and password, and update the ban ledger accordingly.

    Parameters
    ----------
    username:
        Account name submitted by the client.
    password:
        Plain-text password submitted by the client.
    accounts:
        Accounts loaded from ``.ui_credentials.json``.
    auth_store:
        Store that owns the ban ledger.
    client_address:
        Client IP address, used as the key in that ledger.

    Returns
    -------
    CredentialCheck
        ``ACCEPTED`` only when the name matched an account and its password
        verified. Every other value describes why the attempt was refused.
    """
    with LOGIN_STATE_LOCK:
        already_banned, _deadline = is_banned(
            auth_store.load_login_state(), client_address
        )
    if already_banned:
        return CredentialCheck.BANNED

    if (
        len(password) > MAX_CREDENTIAL_LENGTH
        or len(username) > MAX_CREDENTIAL_LENGTH
    ):
        return CredentialCheck.OVERSIZED

    if not accounts:
        return CredentialCheck.NO_ACCOUNTS_CONFIGURED

    matched_account = None
    for account in accounts:
        # compare_digest, not ==, so the time taken does not reveal how many
        # leading characters of a real account name were guessed.
        if secrets.compare_digest(
            username.encode("utf-8"), account.username.encode("utf-8")
        ):
            matched_account = account
            break

    # Hash exactly one password either way, using the first account as a decoy
    # when no name matched, so a wrong username costs the same time as a wrong
    # password. PBKDF2 is deliberately slow, which is what makes the difference
    # measurable if you skip this.
    hash_to_check = (
        matched_account.password_hash
        if matched_account is not None
        else accounts[0].password_hash
    )
    password_verified = verify_password(password, hash_to_check)

    if matched_account is None or not password_verified:
        with LOGIN_STATE_LOCK:
            updated_state = auth_store.update_login_state(
                lambda state: record_failure(state, client_address),
            )
            now_banned, _deadline = is_banned(updated_state, client_address)
        return CredentialCheck.BANNED if now_banned else CredentialCheck.WRONG

    auth_store.update_login_state(
        lambda state: clear_failures(state, client_address),
    )
    return CredentialCheck.ACCEPTED


def is_banned(state: dict, ip: str) -> tuple[bool, float]:
    """Return whether an IP is banned and when that ban ends."""
    record = state.get(ip, {})
    try:
        banned_until = float(record.get("banned_until", 0))
    except (TypeError, ValueError):
        banned_until = 0.0
    if not math.isfinite(banned_until):
        banned_until = 0.0
    return time.time() < banned_until, banned_until


def record_failure(state: dict, ip: str) -> None:
    """Update the failure counters and ban deadline for one IP address.

    Parameters
    ----------
    state:
        Mutable mapping of client IP addresses to login-failure metadata.
    ip:
        Client IP address whose failed attempt should be recorded.
    """
    now = time.time()
    _drop_stale_failure_records(state, now)
    record = state.get(ip, {})
    try:
        last_failed = float(record.get("last_failed", 0))
        failed = int(record.get("failed", 0))
    except (TypeError, ValueError):
        last_failed = 0.0
        failed = 0
    if not math.isfinite(last_failed) or failed < 0:
        last_failed = 0.0
        failed = 0

    # A failure outside the rolling window starts a fresh count.
    if now - last_failed > FAIL_WINDOW_SECONDS:
        failed = 0

    failed += 1
    record.update({"failed": failed, "last_failed": now})

    # Reaching the threshold sets a deadline checked by later attempts.
    if failed >= MAX_FAILED_ATTEMPTS:
        record["banned_until"] = now + BAN_SECONDS

    state[ip] = record


def clear_failures(state: dict, ip: str) -> None:
    """Reset the failure counters for one IP address."""
    record = state.get(ip)
    if record:
        record.update({"failed": 0, "last_failed": 0, "banned_until": 0})
        state[ip] = record


def _failure_record_is_stale(record: dict, now: float) -> bool:
    """Return whether one failure record can no longer affect any decision.

    Parameters
    ----------
    record:
        One address's stored ``failed``, ``last_failed``, and ``banned_until``
        values.
    now:
        Current Unix time in seconds.

    Returns
    -------
    bool
        ``True`` when the address is outside the rolling failure window and is
        not still banned, or when the record cannot be read at all.
    """
    try:
        last_failed = float(record.get("last_failed", 0) or 0)
        banned_until = float(record.get("banned_until", 0) or 0)
    except (TypeError, ValueError):
        # A record that cannot be read is a record that cannot be trusted.
        return True
    if not math.isfinite(last_failed) or not math.isfinite(banned_until):
        return True
    if banned_until > now:
        return False
    return now - last_failed > FAILURE_RECORD_LIFETIME_SECONDS


def _drop_stale_failure_records(state: dict, now: float) -> None:
    """Remove failure records that no longer change any sign-in decision.

    Without this, one row per address that ever failed stays in
    .login_state.json forever, and every later failure has to read and rewrite
    the whole file. A caller with no password could therefore grow that file
    from many addresses and make each attempt slower. A record matters only
    while its address is inside the rolling failure window or still banned.

    Parameters
    ----------
    state:
        Mapping of client addresses to failure records, edited in place.
    now:
        Current Unix time in seconds.
    """
    stale_addresses = [
        address
        for address, record in state.items()
        if not isinstance(record, dict) or _failure_record_is_stale(record, now)
    ]
    for address in stale_addresses:
        del state[address]
