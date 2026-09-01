"""Tests for the fixed wall-clock run schedule and the last-run record."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from src.log_timezone import LOG_TIME_ZONE
from src.human_time import format_clock_time
from src.schedule import (
    is_run_day,
    next_scheduled_run,
    previous_scheduled_run,
    seconds_until_next_scheduled_run,
)
from src.state.run_state_store import (
    RunKind,
    RunState,
    RunStateStore,
    run_state_file_for,
)

RUN_HOUR = 6
INTERVAL_DAYS = 2


def _toronto(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """Return one Toronto-local instant, the clock the schedule runs on."""
    return datetime(year, month, day, hour, minute, tzinfo=LOG_TIME_ZONE)


def test_run_days_alternate_and_do_not_depend_on_a_start_date() -> None:
    """Run days come from the calendar, so consecutive days never both qualify."""
    first_day = _toronto(2026, 9, 1, 12).date()
    qualifying = [
        is_run_day(first_day + timedelta(days=offset), INTERVAL_DAYS)
        for offset in range(6)
    ]

    assert qualifying in ([True, False] * 3, [False, True] * 3)


def test_next_run_is_today_when_the_hour_has_not_passed() -> None:
    """Before 06:00 on a run day, the next run is later the same morning."""
    run_day = _toronto(2026, 9, 3, 5, 0)
    assert is_run_day(run_day.date(), INTERVAL_DAYS)

    next_run = next_scheduled_run(
        run_day, run_hour=RUN_HOUR, interval_days=INTERVAL_DAYS
    )

    assert next_run == _toronto(2026, 9, 3, 6, 0)


def test_next_run_skips_to_the_following_run_day_after_the_hour_passes() -> None:
    """After 06:00 the next run is two days out, not the next morning."""
    run_day = _toronto(2026, 9, 3, 6, 1)

    next_run = next_scheduled_run(
        run_day, run_hour=RUN_HOUR, interval_days=INTERVAL_DAYS
    )

    assert next_run == _toronto(2026, 9, 5, 6, 0)


def test_next_run_is_the_same_whatever_time_the_process_started() -> None:
    """Two reference times in one gap must produce the identical next run."""
    from_morning = next_scheduled_run(
        _toronto(2026, 9, 3, 7, 0), run_hour=RUN_HOUR, interval_days=INTERVAL_DAYS
    )
    from_evening = next_scheduled_run(
        _toronto(2026, 9, 4, 23, 30), run_hour=RUN_HOUR, interval_days=INTERVAL_DAYS
    )

    assert from_morning == from_evening == _toronto(2026, 9, 5, 6, 0)


def test_previous_run_is_the_newest_run_time_not_in_the_future() -> None:
    """The missed-run check needs the most recent scheduled time behind it."""
    previous_run = previous_scheduled_run(
        _toronto(2026, 9, 4, 12, 0), run_hour=RUN_HOUR, interval_days=INTERVAL_DAYS
    )

    assert previous_run == _toronto(2026, 9, 3, 6, 0)


def test_previous_run_is_this_morning_once_the_hour_has_passed() -> None:
    """On a run day after 06:00, that morning is the most recent run time."""
    previous_run = previous_scheduled_run(
        _toronto(2026, 9, 3, 6, 30), run_hour=RUN_HOUR, interval_days=INTERVAL_DAYS
    )

    assert previous_run == _toronto(2026, 9, 3, 6, 0)


def test_the_run_hour_survives_a_daylight_saving_change() -> None:
    """Toronto clocks move on 2026-11-01; the run must still be at 06:00."""
    before_change = _toronto(2026, 10, 31, 12, 0)

    next_run = next_scheduled_run(before_change, run_hour=RUN_HOUR, interval_days=1)

    assert next_run == _toronto(2026, 11, 1, 6, 0)
    assert format_clock_time(next_run).endswith("06:00")


def test_seconds_until_next_run_counts_real_seconds() -> None:
    """The scheduler sleeps on this number, so it must be the true gap."""
    remaining = seconds_until_next_scheduled_run(
        _toronto(2026, 9, 3, 5, 0), run_hour=RUN_HOUR, interval_days=INTERVAL_DAYS
    )

    assert remaining == 3600.0


def test_run_state_round_trips_through_the_file(tmp_path: Path) -> None:
    """A finished run must be readable by the web process that displays it."""
    store = RunStateStore(run_state_file_for(tmp_path))

    assert store.load() == RunState()

    store.mark_run_started(RunKind.MANUAL)
    while_running = store.load()
    assert while_running.is_running is True
    assert while_running.started_at is not None
    assert while_running.kind is RunKind.MANUAL

    store.mark_run_finished()
    after_run = store.load()
    assert after_run.is_running is False
    assert after_run.finished_at is not None
    assert after_run.finished_at >= after_run.started_at
    assert after_run.kind is RunKind.MANUAL


def test_a_damaged_run_state_file_reads_as_no_runs_yet(tmp_path: Path) -> None:
    """A truncated file must not stop the queue page from rendering."""
    state_file = run_state_file_for(tmp_path)
    state_file.write_text("{not json", encoding="utf-8")

    assert RunStateStore(state_file).load() == RunState()


def test_a_leftover_running_flag_is_cleared_at_startup(tmp_path: Path) -> None:
    """A container killed mid-run must not block later runs forever."""
    store = RunStateStore(run_state_file_for(tmp_path))
    store.mark_run_started(RunKind.SCHEDULED)

    store.clear_stale_running_flag()

    assert store.load().is_running is False
