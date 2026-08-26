"""Queue mutations shared by the browser form and the token API.

Two clients add URLs to the download queue: the HTML form on the queue page and
the JSON endpoint the companion browser extension calls. Both must behave the
same way -- reject unsupported links, normalize YouTube URLs, refuse anything
already downloaded or already queued, and wake the scheduler only for work that
can start right now. Keeping that decision in one function stops the two paths
from drifting apart.
"""

from __future__ import annotations

from enum import StrEnum
from typing import NamedTuple

from ..media.urls import is_supported_media_url
from ..media.youtube import (
    is_channel_or_playlist,
    is_youtube_playlist,
    is_youtube_url,
    normalize_youtube_url,
)
from ..state.archive_store import ArchiveStore
from ..state.bypass_store import BypassStore
from ..state.queue_store import QueueStore
from ..trigger import DownloadTrigger


class AddUrlOutcome(StrEnum):
    """Result of one attempt to add a URL to the queue.

    The values double as the ``?msg=`` keys the queue page reads, so the HTML
    form route can redirect with ``str(outcome)`` unchanged.
    """

    INVALID = "invalid"
    ALREADY_DOWNLOADED = "downloaded"
    DUPLICATE = "duplicate"
    ADDED = "added"


class AddUrlResult(NamedTuple):
    """What happened to one submitted URL.

    Attributes
    ----------
    outcome:
        Which of the four end states the submission reached.
    url:
        Normalized URL as it was written to the queue. Empty when the
        submission was rejected as unsupported.
    scheduler_woken:
        True when the scheduler was asked to start on this URL immediately
        instead of waiting for the next scheduled pass. Channel URLs are never
        immediate; they wait for the run that checks recent channel videos.
    """

    outcome: AddUrlOutcome
    url: str
    scheduler_woken: bool


def add_url_to_queue(
    raw_url: str,
    *,
    skip_age_check: bool,
    queue_store: QueueStore,
    archive_store: ArchiveStore,
    bypass_store: BypassStore,
    download_trigger: DownloadTrigger,
) -> AddUrlResult:
    """Validate one URL, append it to the queue, and wake the scheduler.

    Parameters
    ----------
    raw_url:
        Candidate direct video, YouTube channel, or YouTube playlist URL,
        exactly as the client submitted it. Surrounding whitespace is stripped
        here so callers do not each have to remember.
    skip_age_check:
        True when the client wants the item processed now rather than after the
        configured minimum video age. For a YouTube playlist this requests a
        full-playlist run; for a YouTube video it also writes a one-shot entry
        to the age-bypass file. Channel URLs ignore it.
    queue_store:
        Store that owns ``urls.txt``.
    archive_store:
        Store that owns ``downloaded_urls.txt``, used to skip finished items.
    bypass_store:
        Store that owns ``bypass_age_check_urls.txt``.
    download_trigger:
        Scheduler wake-up interface.

    Returns
    -------
    AddUrlResult
        Outcome, the normalized URL, and whether the scheduler was woken.
    """
    # Reject malformed or non-web URLs before touching any state file.
    cleaned_url = raw_url.strip()
    if not is_supported_media_url(cleaned_url):
        return AddUrlResult(AddUrlOutcome.INVALID, "", False)

    # Normalization collapses the many YouTube URL spellings (youtu.be, extra
    # tracking parameters, /shorts/) onto one canonical form, so the duplicate
    # and archive checks below compare like with like.
    normalized = normalize_youtube_url(cleaned_url)

    if normalized in archive_store.load():
        return AddUrlResult(AddUrlOutcome.ALREADY_DOWNLOADED, normalized, False)

    if not queue_store.append_urls([normalized]):
        return AddUrlResult(AddUrlOutcome.DUPLICATE, normalized, False)

    # Direct-video additions wake the scheduler with the exact new URL, so an
    # immediate run cannot expand channels or reprocess older urls.txt entries.
    # Checked playlist additions wake a full-playlist run instead. Channel URLs
    # ignore the request and stay queued for the scheduled channel_count run.
    is_direct_video = not is_channel_or_playlist(normalized)
    if skip_age_check and is_youtube_playlist(normalized):
        download_trigger.queue_full_playlist_download(normalized)
        return AddUrlResult(AddUrlOutcome.ADDED, normalized, True)

    if is_direct_video:
        # The bypass file only affects YouTube's minimum-age policy. Non-YouTube
        # direct videos are immediate already, so writing them there is noise.
        if skip_age_check and is_youtube_url(normalized):
            bypass_store.add(normalized)
        download_trigger.queue_single_url_download(normalized)
        return AddUrlResult(AddUrlOutcome.ADDED, normalized, True)

    return AddUrlResult(AddUrlOutcome.ADDED, normalized, False)
