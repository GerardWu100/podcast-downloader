"""Write times and durations the way a person reads them.

The queue page, the settings page, and the notification texts all need to say
"7 hours ago" or "in 4 days". That wording is not scheduling and not download
logic, so it lives on its own rather than inside the module that happens to
have needed it first.

Every function takes the reference instant as an argument instead of reading
the clock, so the wording can be tested without freezing time.
"""

from __future__ import annotations

from datetime import datetime

from .log_timezone import LOG_TIME_ZONE, OPERATOR_LOG_TIMESTAMP_FORMAT

MINUTES_PER_HOUR = 60
SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = MINUTES_PER_HOUR * SECONDS_PER_MINUTE
HOURS_PER_DAY = 24
SECONDS_PER_DAY = HOURS_PER_DAY * SECONDS_PER_HOUR
# Below this, hours read better than days: "in 30 hours" is clearer than
# "in 1 day". Above it, hours stop being meaningful ("in 1920 hours").
HOURS_BEFORE_SWITCHING_TO_DAYS = 48

JUST_NOW_LABEL = "just now"
NOW_LABEL = "now"


def format_clock_time(moment: datetime) -> str:
    """Return one instant as ``YYYY-MM-DD HH:MM`` on the operator's clock."""
    return moment.astimezone(LOG_TIME_ZONE).strftime(OPERATOR_LOG_TIMESTAMP_FORMAT)


def _format_duration(total_seconds: float) -> str:
    """Return a rounded, plain-language length of time.

    Durations under an hour are reported in minutes, then in hours, then in
    days, because the interface only needs enough precision to answer "is this
    recent?" or "how long have I got?". An empty string means "less than a
    minute", which the two callers below turn into their own wording.

    Parameters
    ----------
    total_seconds:
        Length of time in seconds. Negative values are treated as zero.
    """
    seconds = max(0.0, total_seconds)
    if seconds < SECONDS_PER_HOUR:
        minutes = int(seconds // SECONDS_PER_MINUTE)
        if minutes < 1:
            return ""
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours = int(seconds // SECONDS_PER_HOUR)
    if hours < HOURS_BEFORE_SWITCHING_TO_DAYS:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    days = int(seconds // SECONDS_PER_DAY)
    return f"{days} day{'s' if days != 1 else ''}"


def format_time_ago(moment: datetime, now: datetime) -> str:
    """Return how long ago an instant was, such as ``7 hours ago``.

    Parameters
    ----------
    moment:
        Past instant, timezone-aware.
    now:
        Reference instant, timezone-aware.
    """
    duration = _format_duration(
        (now.astimezone(LOG_TIME_ZONE) - moment).total_seconds()
    )
    if not duration:
        return JUST_NOW_LABEL
    return f"{duration} ago"


def format_time_until(moment: datetime, now: datetime) -> str:
    """Return how long until an instant, such as ``in 41 hours``.

    Parameters
    ----------
    moment:
        Future instant, timezone-aware.
    now:
        Reference instant, timezone-aware.
    """
    duration = _format_duration(
        (moment - now.astimezone(LOG_TIME_ZONE)).total_seconds()
    )
    if not duration:
        return NOW_LABEL
    return f"in {duration}"
