"""Decide when a finished run is worth interrupting someone about.

The downloader used to report only failed downloads, which left its worst
failure silent. If YouTube refuses to list a channel, no video is ever
attempted, so nothing fails, so nothing is sent. The run ends with "0
successful, 0 failed" and looks exactly like a week with no new episodes.

This module turns the facts of a finished run into an alert, or into nothing.
It sends nothing when the run was ordinary, because a routine "all is well"
message trains a reader to ignore the channel it arrives on, and because a
message that always arrives cannot prove anything by arriving.

It is pure: it reads no files and sends nothing. ``PodcastDownloadService``
collects the facts, and the notifier delivers whatever comes back.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .cookie_file import CookieFileStatus, CookieHealth, cookie_health
from .human_time import format_clock_time, format_time_ago, format_time_until

RUN_ALERT_TITLE = "Podcast downloader needs attention"
MISSED_RUN_TITLE = "Podcast downloader missed a run"
FAILED_RUN_TITLE = "Podcast downloader could not finish a run"
# Written into the alert so the reader knows where to look next. The 403 and
# the cookie file are the two things that break a working deployment.
BLOCKED_LISTING_ADVICE = (
    "Check the cookie file on the Settings page, then youtube_player_client in "
    "config.ini. A listing that returns nothing is usually YouTube refusing the "
    "request, not a channel that has stopped publishing."
)


@dataclass(frozen=True)
class RunFacts:
    """What one whole-queue run did.

    Attributes
    ----------
    listing_source_count:
        How many of those were YouTube channels or playlists, the sources that
        have to be listed before anything can be downloaded.
    listing_sources_without_videos:
        How many of those listings produced no video at all.
    videos_attempted:
        Videos the run tried to download, including ones already in the archive.
    downloads_failed:
        Attempts that did not produce an MP3. Each of these was already
        reported on its own, so this only shades the wording here.
    """

    listing_source_count: int = 0
    listing_sources_without_videos: int = 0
    videos_attempted: int = 0
    downloads_failed: int = 0


@dataclass(frozen=True)
class Concern:
    """One thing wrong with a run.

    Attributes
    ----------
    summary:
        A few words for the activity log, which holds one line per event.
    detail:
        The full sentence for the notification, including what to check.
    """

    summary: str
    detail: str


@dataclass(frozen=True)
class RunAlert:
    """One notification, ready to send.

    Attributes
    ----------
    title:
        Message heading.
    body:
        Message text, listing every concern and what to do about it.
    summary:
        The same concerns in a few words, for the one-line activity log.
    """

    title: str
    body: str
    summary: str


def _listing_concern(facts: RunFacts) -> Concern | None:
    """Return the sentence for a run that could not list its sources.

    The test is "every listing came back empty" rather than "the run
    downloaded nothing". A run that downloads nothing is the normal case: the
    newest episodes are already in the archive. A run where no channel would
    list at all is not normal, and it is the shape a block takes.

    Parameters
    ----------
    facts:
        What the finished run did.

    Returns
    -------
    Concern | None
        The concern, or ``None`` when the listings were fine.
    """
    if facts.listing_source_count == 0:
        return None
    if facts.listing_sources_without_videos < facts.listing_source_count:
        return None

    if facts.listing_source_count == 1:
        opening = "The only monitored channel or playlist returned no videos."
    else:
        opening = (
            f"All {facts.listing_source_count} monitored channels and playlists "
            "returned no videos."
        )
    return Concern(
        "no videos from any monitored source",
        f"{opening} {BLOCKED_LISTING_ADVICE}",
    )


def _cookie_concern(
    cookie_status: CookieFileStatus,
    now: datetime,
    warning_days: int,
) -> Concern | None:
    """Return the sentence for a cookie file that is running out.

    The judgement itself belongs to ``cookie_file.cookie_health``, which the
    settings page also uses. Only the wording is chosen here.

    Parameters
    ----------
    cookie_status:
        What was read from the cookie file.
    now:
        Reference instant, timezone-aware.
    warning_days:
        How many days ahead to warn. Zero turns the early warning off.

    Returns
    -------
    Concern | None
        The concern, or ``None`` when there is nothing to say.
    """
    health = cookie_health(cookie_status, now, warning_days)
    if health is CookieHealth.NO_LOGIN_COOKIES:
        return Concern(
            "the cookie file has no sign-in cookies",
            "The uploaded cookies.txt holds no YouTube sign-in cookies, so it "
            "cannot get past an age check or a sign-in prompt. Export a fresh "
            "one while signed in to YouTube.",
        )

    expiry = cookie_status.earliest_login_expiry
    if expiry is None:
        return None
    if health is CookieHealth.EXPIRED:
        return Concern(
            f"sign-in cookies expired {format_time_ago(expiry, now)}",
            f"The YouTube sign-in cookies expired on {format_clock_time(expiry)}, "
            f"{format_time_ago(expiry, now)}. Export a fresh cookies.txt and "
            "upload it on the Settings page.",
        )
    if health is CookieHealth.EXPIRING_SOON:
        return Concern(
            f"sign-in cookies expire {format_time_until(expiry, now)}",
            f"The YouTube sign-in cookies stop working by {format_clock_time(expiry)}, "
            f"{format_time_until(expiry, now)}. Export a fresh cookies.txt before then.",
        )
    return None


def build_run_alert(
    facts: RunFacts,
    cookie_status: CookieFileStatus,
    *,
    now: datetime,
    cookie_warning_days: int,
) -> RunAlert | None:
    """Return the alert a finished run deserves, or ``None`` for silence.

    Parameters
    ----------
    facts:
        What the finished run did.
    cookie_status:
        What was read from the cookie file the run used.
    now:
        Reference instant, timezone-aware.
    cookie_warning_days:
        How many days before expiry to start warning. Zero turns that warning
        off; an expired file is always reported.

    Returns
    -------
    RunAlert | None
        The message to send, or ``None`` when the run needs no attention.
    """
    concerns = [
        concern
        for concern in (
            _listing_concern(facts),
            _cookie_concern(cookie_status, now, cookie_warning_days),
        )
        if concern is not None
    ]
    if not concerns:
        return None

    details = (
        concerns[0].detail
        if len(concerns) == 1
        else "\n\n".join(
            f"{index}. {concern.detail}" for index, concern in enumerate(concerns, 1)
        )
    )
    run_line = (
        f"Run finished at {format_clock_time(now)}: "
        f"{facts.videos_attempted} videos considered, "
        f"{facts.downloads_failed} failed."
    )
    return RunAlert(
        RUN_ALERT_TITLE,
        f"{details}\n\n{run_line}",
        "; ".join(concern.summary for concern in concerns),
    )


def build_missed_run_alert(
    last_finished_at: datetime | None,
    scheduled_for: datetime,
    now: datetime,
) -> RunAlert:
    """Return the alert for a scheduled run that never happened.

    This is sent when the downloader starts and finds that the run it should
    have made has not been made. It cannot cover a machine that never comes
    back; a watchdog polling ``/api/health`` is what covers that.

    Parameters
    ----------
    last_finished_at:
        When the last whole-queue run finished, or ``None`` if none has.
    scheduled_for:
        The run time that was missed.
    now:
        Reference instant, timezone-aware.
    """
    if last_finished_at is None:
        history = "No run has ever finished on this deployment."
    else:
        history = (
            f"The last finished run was {format_clock_time(last_finished_at)}, "
            f"{format_time_ago(last_finished_at, now)}."
        )
    return RunAlert(
        MISSED_RUN_TITLE,
        f"The run scheduled for {format_clock_time(scheduled_for)} did not "
        f"happen, so the downloader was not running then. {history} "
        "It is catching up now.",
        f"missed the run scheduled for {format_clock_time(scheduled_for)}",
    )


def build_failed_run_alert(exit_code: int, now: datetime) -> RunAlert:
    """Return the alert for a run that stopped before it could download anything.

    A run that ends this way reports nothing on its own: no download was
    attempted, so no download failed, so no failure was sent. A missing
    ``yt-dlp`` and an unreadable ``config.ini`` both look like this.

    Parameters
    ----------
    exit_code:
        Status the downloader process exited with.
    now:
        Reference instant, timezone-aware.
    """
    return RunAlert(
        FAILED_RUN_TITLE,
        f"The run started at {format_clock_time(now)} stopped with exit "
        f"status {exit_code} before downloading anything. Nothing failed, "
        "because nothing was attempted. Check download.log and the container "
        "output: a missing yt-dlp or a rejected config.ini both end this way.",
        f"the run stopped with exit status {exit_code}",
    )
