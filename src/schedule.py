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

This module answers only "when", in calendar terms. The wording a person reads
lives in ``human_time.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, time, timedelta

from .human_time import SECONDS_PER_HOUR
from .log_timezone import LOG_TIME_ZONE

# How late a scheduled run may be before something is treated as wrong. A run
# starts on the hour but takes as long as its downloads take, so a health check
# that allowed no slack would report a failure every time a run ran long.
OVERDUE_GRACE_SECONDS = 3 * SECONDS_PER_HOUR


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


def _run_instants(
    reference: datetime,
    run_hour: int,
    interval_days: int,
    day_step: int,
) -> Iterator[datetime]:
    """Yield run instants walking away from ``reference`` one day at a time.

    Both directions are the same scan, so they share one implementation: the
    next run walks forward, the previous run walks backward. The walk covers
    ``interval_days`` days either way, which is far enough to be certain of
    finding a run day.

    Parameters
    ----------
    reference:
        Where the walk starts, already in the operator's timezone.
    run_hour:
        Local hour a run starts, 0 to 23.
    interval_days:
        Days between run days, at least 1.
    day_step:
        ``1`` to walk into the future, ``-1`` into the past.

    Yields
    ------
    datetime.datetime
        Each run instant found, nearest to ``reference`` first.
    """
    for day_offset in range(interval_days + 1):
        candidate_day = reference.date() + timedelta(days=day_offset * day_step)
        if not is_run_day(candidate_day, interval_days):
            continue
        # Built from a date and an hour rather than by adding hours to another
        # run, so a daylight-saving change keeps the run at the same displayed
        # time instead of shifting it by an hour.
        yield datetime.combine(candidate_day, time(hour=run_hour), tzinfo=LOG_TIME_ZONE)


def next_scheduled_run(
    now: datetime,
    *,
    run_hour: int,
    interval_days: int,
) -> datetime:
    """Return the first scheduled run instant strictly after ``now``.

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
    for candidate in _run_instants(reference, run_hour, interval_days, 1):
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

    The overdue check compares this against the last run that actually
    finished. If the recorded run is older, a scheduled run was missed while
    the container was down.

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
    for candidate in _run_instants(reference, run_hour, interval_days, -1):
        if candidate <= reference:
            return candidate
    raise ValueError("Could not find the previous scheduled run day.")


def scheduled_run_is_overdue(
    last_finished_at: datetime | None,
    *,
    now: datetime,
    run_hour: int,
    interval_days: int,
    run_in_progress: bool = False,
    grace_seconds: float = OVERDUE_GRACE_SECONDS,
) -> bool:
    """Return whether the last scheduled run failed to happen.

    This is the one question a watchdog needs answered: did the run that was
    due actually happen? It compares the newest scheduled time that has passed
    against the last run that finished. A downloader that has never run counts
    as overdue, because a deployment that has never worked is not healthy.

    Parameters
    ----------
    last_finished_at:
        When the last whole-queue run finished, or ``None`` if none has.
    now:
        Reference instant, timezone-aware.
    run_hour:
        Local hour a run starts, 0 to 23.
    interval_days:
        Days between run days, at least 1.
    run_in_progress:
        True while a run is going. A long run is not a late run, however far
        past the scheduled hour it gets.
    grace_seconds:
        How long after the scheduled time a run may still be starting or
        running before it counts as missed. Pass ``0`` to ask the strict
        question "has the run that was due already finished?".

    Returns
    -------
    bool
        True when the scheduled run is late or never happened.
    """
    if run_in_progress:
        return False

    reference = now.astimezone(LOG_TIME_ZONE)
    previous_run = previous_scheduled_run(
        reference, run_hour=run_hour, interval_days=interval_days
    )
    if (reference - previous_run).total_seconds() <= grace_seconds:
        # The run that was due is still inside its allowance, so whatever the
        # history says, nothing is late yet.
        return False
    if last_finished_at is None:
        return True
    return last_finished_at < previous_run


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
