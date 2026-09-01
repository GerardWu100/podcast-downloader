"""Fixed wall-clock schedule for automatic download runs.

The scheduler used to sleep for a fixed number of hours after each run, so the
time of day drifted with every restart, deployment, or manual run. This module
replaces that with a calendar rule: a run starts at the same local hour, on
every Nth calendar day, no matter when the container was last started. Both
numbers come from ``config.ini`` (``scheduled_run_hour`` and
``scheduled_run_interval_days``); the defaults are 06:00 every other day.

Which calendar days are run days comes from the date itself. ``date.toordinal``
counts days since 0001-01-01, so a day is a run day when that count divides
evenly by the interval. With the default interval of two days this means every
other calendar day, and the answer never depends on process state.

Times are Toronto local time (``LOG_TIME_ZONE``), the same clock the activity
log and the detailed log already use, so "06:00" in the interface means 06:00
on the operator's clock even though the container runs on UTC.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from .log_timezone import LOG_TIME_ZONE

MINUTES_PER_HOUR = 60
SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = MINUTES_PER_HOUR * SECONDS_PER_MINUTE

SCHEDULE_TIME_FORMAT = "%Y-%m-%d %H:%M"
JUST_NOW_LABEL = "just now"
NOW_LABEL = "now"


def local_now() -> datetime:
    """Return the current time on the operator's clock."""
    return datetime.now(LOG_TIME_ZONE)


def is_run_day(day: date, interval_days: int) -> bool:
    """Return whether scheduled runs happen on this calendar day.

    Parameters
    ----------
    day:
        Calendar day to test.
    interval_days:
        Days between run days. ``2`` means every other day.
    """
    return day.toordinal() % interval_days == 0


def next_scheduled_run(
    now: datetime,
    *,
    run_hour: int,
    interval_days: int,
) -> datetime:
    """Return the first scheduled run instant strictly after ``now``.

    The result is built from a calendar date plus a wall-clock hour rather than
    by adding hours to the previous run, so a daylight-saving change keeps the
    run at the same displayed time instead of shifting it by an hour.

    Parameters
    ----------
    now:
        Reference instant, timezone-aware.
    run_hour:
        Local hour a run starts, 0 to 23.
    interval_days:
        Days between run days, at least 1.

    Returns
    -------
    datetime.datetime
        Toronto-local time of the next scheduled run.

    Examples
    --------
    With ``run_hour=6`` and ``interval_days=2``, a reference of 07:30 on a run
    day returns 06:00 two days later: today's run time has already passed and
    tomorrow is not a run day.
    """
    reference = now.astimezone(LOG_TIME_ZONE)

    # Scan forward day by day. The first run day strictly after `reference` is
    # at most `interval_days` days out, so this loop always finds one.
    for day_offset in range(interval_days + 1):
        candidate_day = reference.date() + timedelta(days=day_offset)
        if not is_run_day(candidate_day, interval_days):
            continue
        candidate = datetime.combine(
            candidate_day, time(hour=run_hour), tzinfo=LOG_TIME_ZONE
        )
        if candidate > reference:
            return candidate

    raise ValueError("Could not find the next scheduled run day.")


def previous_scheduled_run(
    now: datetime,
    *,
    run_hour: int,
    interval_days: int,
) -> datetime:
    """Return the most recent scheduled run instant at or before ``now``.

    The scheduler compares this against the last run it actually finished. If
    the recorded run is older, a scheduled run was missed while the container
    was down and it can catch up instead of waiting for the next run day.

    Parameters
    ----------
    now:
        Reference instant, timezone-aware.
    run_hour:
        Local hour a run starts, 0 to 23.
    interval_days:
        Days between run days, at least 1.

    Returns
    -------
    datetime.datetime
        Toronto-local time of the newest run instant that is not in the future.
    """
    reference = now.astimezone(LOG_TIME_ZONE)

    # Scan backwards day by day; the newest past run day is at most
    # `interval_days` days behind.
    for day_offset in range(interval_days + 1):
        candidate_day = reference.date() - timedelta(days=day_offset)
        if not is_run_day(candidate_day, interval_days):
            continue
        candidate = datetime.combine(
            candidate_day, time(hour=run_hour), tzinfo=LOG_TIME_ZONE
        )
        if candidate <= reference:
            return candidate

    raise ValueError("Could not find the previous scheduled run day.")


def seconds_until_next_scheduled_run(
    now: datetime,
    *,
    run_hour: int,
    interval_days: int,
) -> float:
    """Return how many seconds remain before the next scheduled run.

    Parameters
    ----------
    now:
        Reference instant, timezone-aware.
    run_hour:
        Local hour a run starts, 0 to 23.
    interval_days:
        Days between run days, at least 1.
    """
    reference = now.astimezone(LOG_TIME_ZONE)
    next_run = next_scheduled_run(
        reference, run_hour=run_hour, interval_days=interval_days
    )
    return (next_run - reference).total_seconds()


def format_schedule_time(moment: datetime) -> str:
    """Return one instant as ``YYYY-MM-DD HH:MM`` on the operator's clock."""
    return moment.astimezone(LOG_TIME_ZONE).strftime(SCHEDULE_TIME_FORMAT)


def _format_duration(total_seconds: float) -> str:
    """Return a rounded, plain-language length of time.

    Durations under an hour are reported in minutes and the rest in hours,
    because the interface only needs enough precision to answer "is this
    recent?". An empty string means "less than a minute", which the two callers
    below turn into their own wording.

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
    return f"{hours} hour{'s' if hours != 1 else ''}"


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
