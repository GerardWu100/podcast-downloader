"""Read a Netscape cookies.txt well enough to describe it on the settings page.

YouTube sign-in cookies expire. When they do, downloads start failing with
messages about age gates and forbidden requests, and the only fix is to export
a fresh file from the browser. The settings page therefore needs to answer one
question: how much longer is this file good for?

A Netscape cookie file is one cookie per line, seven tab-separated fields:

    domain  include_subdomains  path  secure  expires  name  value

``expires`` is a Unix timestamp in seconds. A zero means a session cookie, one
the browser would have dropped when it closed. Lines starting with ``#`` are
comments, except that some exporters write ``#HttpOnly_`` in front of a real
cookie line, so that prefix is stripped rather than skipped.

This module only reads. It never rewrites the file, and a line it cannot parse
is ignored rather than treated as an error, because the file is meant to be
handed to yt-dlp, not to this code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path

from .log_timezone import LOG_TIME_ZONE

HTTP_ONLY_PREFIX = "#HttpOnly_"
COOKIE_FIELD_COUNT = 7
EXPIRY_FIELD_INDEX = 4
NAME_FIELD_INDEX = 5
SESSION_COOKIE_EXPIRY = 0
# A cookie file is not a document; anything this large is not one of ours.
# The web upload refuses the same size, so a file the page accepted can always
# be read back by the code that describes it.
MAX_COOKIE_FILE_BYTES = 5 * 1024 * 1024

# The cookies that carry a YouTube sign-in. When the earliest of these expires,
# the file stops proving who you are, whatever else it still contains. Names
# come from Google's own cookie set; ``__Secure-`` variants are the ones modern
# exports actually contain.
YOUTUBE_LOGIN_COOKIE_NAMES = frozenset(
    {
        "SID",
        "HSID",
        "SSID",
        "APISID",
        "SAPISID",
        "LOGIN_INFO",
        "__Secure-1PSID",
        "__Secure-3PSID",
        "__Secure-1PAPISID",
        "__Secure-3PAPISID",
    }
)


class CookieHealth(StrEnum):
    """How much use the cookie file still is.

    The settings page and the after-run alert both need this judgement, and
    they used to make it separately with different thresholds. Deciding it once
    here means the page and the notification can never disagree; they only
    choose their own wording for the same answer.
    """

    ABSENT = "absent"
    NO_LOGIN_COOKIES = "no_login_cookies"
    NO_EXPIRY_DATE = "no_expiry_date"
    EXPIRED = "expired"
    EXPIRING_SOON = "expiring_soon"
    GOOD = "good"


@dataclass(frozen=True)
class CookieFileStatus:
    """What the settings page knows about the cookie file in use.

    Attributes
    ----------
    exists:
        Whether a cookie file is present at the configured path.
    cookie_count:
        Cookies the file contains, session cookies included.
    login_cookie_count:
        How many of those are YouTube sign-in cookies.
    earliest_login_expiry:
        When the first sign-in cookie expires, which is when the file stops
        proving who you are. ``None`` when the file holds no dated sign-in
        cookie.
    updated_at:
        When the file was last written.
    """

    exists: bool = False
    cookie_count: int = 0
    login_cookie_count: int = 0
    earliest_login_expiry: datetime | None = None
    updated_at: datetime | None = None


def _parse_cookie_line(line: str) -> tuple[str, int] | None:
    """Return one cookie's ``(name, expiry)``, or ``None`` for a non-cookie line.

    Parameters
    ----------
    line:
        One raw line from the cookie file, without its newline.

    Returns
    -------
    tuple[str, int] | None
        The cookie name and its Unix expiry timestamp, or ``None`` when the
        line is a comment, blank, or does not have the seven expected fields.
    """
    if line.startswith(HTTP_ONLY_PREFIX):
        line = line[len(HTTP_ONLY_PREFIX) :]
    if not line.strip() or line.startswith("#"):
        return None

    fields = line.split("\t")
    if len(fields) < COOKIE_FIELD_COUNT:
        return None

    try:
        # Some exporters write a fractional timestamp, so parse through float.
        expiry_seconds = int(float(fields[EXPIRY_FIELD_INDEX]))
    except ValueError:
        return None

    return fields[NAME_FIELD_INDEX].strip(), expiry_seconds


def describe_cookie_file(cookie_file: Path | None) -> CookieFileStatus:
    """Summarize the cookie file for display.

    Parameters
    ----------
    cookie_file:
        Configured cookie path, or ``None`` when cookies are not configured.

    Returns
    -------
    CookieFileStatus
        Counts and the earliest sign-in expiry. A missing, oversized, or
        unreadable file reports as absent rather than raising, because this
        runs while rendering a page.
    """
    if cookie_file is None:
        return CookieFileStatus()

    try:
        if not cookie_file.is_file():
            return CookieFileStatus()
        file_stat = cookie_file.stat()
        if file_stat.st_size > MAX_COOKIE_FILE_BYTES:
            return CookieFileStatus()
        raw_text = cookie_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return CookieFileStatus()

    updated_at = datetime.fromtimestamp(file_stat.st_mtime, tz=LOG_TIME_ZONE)
    cookie_count = 0
    login_cookie_count = 0
    earliest_login_expiry_seconds: int | None = None

    for line in raw_text.splitlines():
        parsed = _parse_cookie_line(line)
        if parsed is None:
            continue
        name, expiry_seconds = parsed
        cookie_count += 1
        if name not in YOUTUBE_LOGIN_COOKIE_NAMES:
            continue
        login_cookie_count += 1
        # A session cookie has no date to report, so it cannot be the earliest.
        if expiry_seconds <= SESSION_COOKIE_EXPIRY:
            continue
        if (
            earliest_login_expiry_seconds is None
            or expiry_seconds < earliest_login_expiry_seconds
        ):
            earliest_login_expiry_seconds = expiry_seconds

    earliest_login_expiry = (
        datetime.fromtimestamp(earliest_login_expiry_seconds, tz=LOG_TIME_ZONE)
        if earliest_login_expiry_seconds is not None
        else None
    )

    return CookieFileStatus(
        exists=True,
        cookie_count=cookie_count,
        login_cookie_count=login_cookie_count,
        earliest_login_expiry=earliest_login_expiry,
        updated_at=updated_at,
    )


def cookie_health(
    status: CookieFileStatus,
    now: datetime,
    warning_days: int,
) -> CookieHealth:
    """Judge how much use the cookie file still is.

    Parameters
    ----------
    status:
        What was read from the cookie file.
    now:
        Reference instant, timezone-aware.
    warning_days:
        How many days before expiry to start calling the file
        ``EXPIRING_SOON``. Zero turns that early state off; an expired file is
        always reported as expired.

    Returns
    -------
    CookieHealth
        One of the six states, from "there is no file" to "good".
    """
    if not status.exists:
        return CookieHealth.ABSENT
    if status.login_cookie_count == 0:
        return CookieHealth.NO_LOGIN_COOKIES
    if status.earliest_login_expiry is None:
        return CookieHealth.NO_EXPIRY_DATE
    if status.earliest_login_expiry <= now:
        return CookieHealth.EXPIRED
    if warning_days > 0 and status.earliest_login_expiry <= now + timedelta(
        days=warning_days
    ):
        return CookieHealth.EXPIRING_SOON
    return CookieHealth.GOOD
