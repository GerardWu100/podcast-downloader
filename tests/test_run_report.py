"""Tests for the alerts that turn a silent failure into a message."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from src.cookie_file import CookieFileStatus
from src.log_timezone import LOG_TIME_ZONE
from src.run_report import (
    MISSED_RUN_TITLE,
    RUN_ALERT_TITLE,
    RunFacts,
    build_missed_run_alert,
    build_run_alert,
)
from src.schedule import scheduled_run_is_overdue

NOW = datetime(2026, 9, 3, 7, 0, tzinfo=LOG_TIME_ZONE)
HEALTHY_COOKIES = CookieFileStatus(
    exists=True,
    cookie_count=8,
    login_cookie_count=3,
    earliest_login_expiry=NOW + timedelta(days=200),
)
NO_COOKIES = CookieFileStatus()
WARNING_DAYS = 14


def build(facts: RunFacts, cookies: CookieFileStatus = NO_COOKIES):
    """Return the alert for one run, using the standard warning window."""
    return build_run_alert(facts, cookies, now=NOW, cookie_warning_days=WARNING_DAYS)


def test_an_ordinary_run_sends_nothing() -> None:
    """A working run must stay quiet, or the channel becomes noise."""
    facts = RunFacts(
        listing_source_count=4,
        listing_sources_without_videos=0,
        videos_attempted=8,
        downloads_failed=0,
    )

    assert build(facts, HEALTHY_COOKIES) is None


def test_a_run_that_downloaded_nothing_new_still_sends_nothing() -> None:
    """Most runs find every recent episode already downloaded. That is normal."""
    facts = RunFacts(
        listing_source_count=4,
        listing_sources_without_videos=0,
        videos_attempted=8,
        downloads_failed=0,
    )

    assert build(facts, HEALTHY_COOKIES) is None


def test_every_listing_coming_back_empty_raises_an_alert() -> None:
    """This is the silent failure: nothing runs, so nothing fails, so nothing is sent."""
    facts = RunFacts(
        listing_source_count=4,
        listing_sources_without_videos=4,
        videos_attempted=0,
        downloads_failed=0,
    )

    alert = build(facts, HEALTHY_COOKIES)

    assert alert is not None
    assert alert.title == RUN_ALERT_TITLE
    assert "All 4 monitored channels and playlists returned no videos." in alert.body
    # The message has to say what to check, or it is just an alarm.
    assert "cookie file" in alert.body
    assert "youtube_player_client" in alert.body


def test_one_empty_listing_among_several_stays_quiet() -> None:
    """A single channel with nothing eligible is ordinary, not a failure."""
    facts = RunFacts(
        listing_source_count=4,
        listing_sources_without_videos=1,
        videos_attempted=6,
        downloads_failed=0,
    )

    assert build(facts, HEALTHY_COOKIES) is None


def test_a_queue_of_direct_videos_only_never_raises_a_listing_alert() -> None:
    """With nothing to list, an empty listing count proves nothing."""
    facts = RunFacts(
        listing_source_count=0,
        listing_sources_without_videos=0,
        videos_attempted=0,
        downloads_failed=0,
    )

    assert build(facts, HEALTHY_COOKIES) is None


def test_expired_cookies_are_reported_even_when_the_run_worked() -> None:
    """Expired cookies are the next outage, so they are worth saying early."""
    expired = CookieFileStatus(
        exists=True,
        cookie_count=8,
        login_cookie_count=3,
        earliest_login_expiry=NOW - timedelta(days=2),
    )
    facts = RunFacts(listing_source_count=2, videos_attempted=4)

    alert = build(facts, expired)

    assert alert is not None
    assert "expired on" in alert.body
    assert "Settings page" in alert.body


def test_cookies_close_to_expiry_are_reported_once_inside_the_window() -> None:
    """The warning window is what turns a surprise outage into a chore."""
    closing = CookieFileStatus(
        exists=True,
        cookie_count=8,
        login_cookie_count=3,
        earliest_login_expiry=NOW + timedelta(days=5),
    )
    facts = RunFacts(listing_source_count=2, videos_attempted=4)

    alert = build(facts, closing)

    assert alert is not None
    assert "stop working by" in alert.body

    # Outside the window there is nothing to say yet.
    far_off = CookieFileStatus(
        exists=True,
        cookie_count=8,
        login_cookie_count=3,
        earliest_login_expiry=NOW + timedelta(days=30),
    )
    assert build(facts, far_off) is None


def test_a_zero_warning_window_turns_the_early_cookie_notice_off() -> None:
    """The nag is configurable, but an expired file still gets reported."""
    closing = CookieFileStatus(
        exists=True,
        cookie_count=8,
        login_cookie_count=3,
        earliest_login_expiry=NOW + timedelta(days=5),
    )
    facts = RunFacts(listing_source_count=2, videos_attempted=4)

    assert build_run_alert(facts, closing, now=NOW, cookie_warning_days=0) is None

    expired = CookieFileStatus(
        exists=True,
        cookie_count=8,
        login_cookie_count=3,
        earliest_login_expiry=NOW - timedelta(hours=1),
    )
    assert build_run_alert(facts, expired, now=NOW, cookie_warning_days=0) is not None


def test_two_problems_arrive_in_one_numbered_message() -> None:
    """One message per run keeps the channel readable when things go wrong."""
    expired = CookieFileStatus(
        exists=True,
        cookie_count=8,
        login_cookie_count=3,
        earliest_login_expiry=NOW - timedelta(days=1),
    )
    facts = RunFacts(
        listing_source_count=3,
        listing_sources_without_videos=3,
        videos_attempted=0,
    )

    alert = build(facts, expired)

    assert alert is not None
    assert alert.body.startswith("1. ")
    assert "\n\n2. " in alert.body


def test_the_missed_run_alert_names_the_run_that_did_not_happen() -> None:
    """After downtime, the operator needs the date, not just "something failed"."""
    scheduled_for = datetime(2026, 9, 3, 6, 0, tzinfo=LOG_TIME_ZONE)
    last_finished = datetime(2026, 8, 30, 6, 4, tzinfo=LOG_TIME_ZONE)

    alert = build_missed_run_alert(last_finished, scheduled_for, NOW)

    assert alert.title == MISSED_RUN_TITLE
    assert "2026-09-03 06:00" in alert.body
    assert "2026-08-30 06:04" in alert.body
    assert "catching up now" in alert.body


@pytest.mark.parametrize(
    ("last_finished", "now", "expected"),
    [
        # The 06:00 run happened; nothing is late.
        (
            datetime(2026, 9, 3, 6, 5, tzinfo=LOG_TIME_ZONE),
            datetime(2026, 9, 3, 12, 0, tzinfo=LOG_TIME_ZONE),
            False,
        ),
        # The 06:00 run never happened and the allowance has passed.
        (
            datetime(2026, 9, 1, 6, 5, tzinfo=LOG_TIME_ZONE),
            datetime(2026, 9, 3, 12, 0, tzinfo=LOG_TIME_ZONE),
            True,
        ),
        # Still inside the allowance, so a long-running run is not a failure.
        (
            datetime(2026, 9, 1, 6, 5, tzinfo=LOG_TIME_ZONE),
            datetime(2026, 9, 3, 7, 0, tzinfo=LOG_TIME_ZONE),
            False,
        ),
        # A deployment that has never run is not healthy.
        (None, datetime(2026, 9, 3, 12, 0, tzinfo=LOG_TIME_ZONE), True),
    ],
)
def test_overdue_rule(last_finished, now, expected: bool) -> None:
    """The watchdog answers one question: did the due run actually happen?"""
    assert (
        scheduled_run_is_overdue(last_finished, now=now, run_hour=6, interval_days=2)
        is expected
    )
