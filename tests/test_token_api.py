"""Behaviour tests for the bearer-token JSON API used by the browser extension."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.state.archive_store import ArchiveStore
from src.state.bypass_store import BypassStore
from src.state.queue_store import QueueStore
from src.web import token_api
from src.web.api_token import (
    API_TOKEN_ENV_KEY,
    MINIMUM_API_TOKEN_LENGTH,
    load_api_token,
)
from src.web.queue_actions import AddUrlOutcome, add_url_to_queue
from src.web.token_api import AddUrlRequest

VALID_TOKEN = "t" * MINIMUM_API_TOKEN_LENGTH
YOUTUBE_VIDEO_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
YOUTUBE_PLAYLIST_URL = "https://www.youtube.com/playlist?list=PL0000000000"
YOUTUBE_CHANNEL_URL = "https://www.youtube.com/@examplechannel"


class _RecordingDownloadTrigger:
    """Capture scheduler wake-ups instead of touching the shared queues."""

    def __init__(self) -> None:
        self.single_urls: list[str] = []
        self.playlist_urls: list[str] = []

    def queue_single_url_download(self, url: str) -> None:
        """Record one direct-media request."""
        self.single_urls.append(url)

    def queue_full_playlist_download(self, url: str) -> None:
        """Record one full-playlist request."""
        self.playlist_urls.append(url)


def _build_request(
    tmp_path: Path,
    *,
    authorization: str | None = f"Bearer {VALID_TOKEN}",
    api_token: str = VALID_TOKEN,
) -> SimpleNamespace:
    """Return a request double carrying the same state ``create_app`` attaches.

    Parameters
    ----------
    tmp_path:
        Directory that receives the queue, archive, and bypass files.
    authorization:
        Value for the ``Authorization`` header, or ``None`` to omit it.
    api_token:
        Token the server accepts. An empty string means "not configured".

    Returns
    -------
    SimpleNamespace
        Object exposing the ``headers`` and ``app.state`` attributes the routes
        read, plus the recording trigger under ``download_trigger``.
    """
    logger = logging.getLogger("test.web.token_api")
    headers = {} if authorization is None else {"authorization": authorization}
    state = SimpleNamespace(
        api_token=api_token,
        queue_store=QueueStore(tmp_path / "urls.txt", logger),
        archive_store=ArchiveStore(tmp_path / "downloaded_urls.txt", logger),
        bypass_store=BypassStore(tmp_path / "bypass_age_check_urls.txt", logger),
        download_trigger=_RecordingDownloadTrigger(),
    )
    return SimpleNamespace(headers=headers, app=SimpleNamespace(state=state))


def _body(response) -> dict:
    """Decode a JSONResponse body into a dictionary."""
    return json.loads(response.body.decode("utf-8"))


def test_load_api_token_prefers_environment_over_env_file(
    tmp_path: Path, monkeypatch
) -> None:
    """Docker passes the token through the environment, which must win."""
    (tmp_path / ".env").write_text(
        f"{API_TOKEN_ENV_KEY}=" + "f" * MINIMUM_API_TOKEN_LENGTH,
        encoding="utf-8",
    )
    monkeypatch.setenv(API_TOKEN_ENV_KEY, "e" * MINIMUM_API_TOKEN_LENGTH)

    assert load_api_token(tmp_path) == "e" * MINIMUM_API_TOKEN_LENGTH


def test_load_api_token_reads_env_file_when_environment_is_unset(
    tmp_path: Path, monkeypatch
) -> None:
    """A local run keeps the token in .env beside the login accounts."""
    monkeypatch.delenv(API_TOKEN_ENV_KEY, raising=False)
    (tmp_path / ".env").write_text(
        f"UI_USERNAME=admin\n{API_TOKEN_ENV_KEY}={VALID_TOKEN}\n",
        encoding="utf-8",
    )

    assert load_api_token(tmp_path) == VALID_TOKEN


def test_load_api_token_rejects_a_short_token(tmp_path: Path, monkeypatch) -> None:
    """A guessable token must disable the API instead of protecting it weakly."""
    monkeypatch.setenv(API_TOKEN_ENV_KEY, "hunter2")

    assert load_api_token(tmp_path) == ""


def test_load_api_token_tolerates_a_missing_env_file(
    tmp_path: Path, monkeypatch
) -> None:
    """A deployment without .env should report "unset", not raise."""
    monkeypatch.delenv(API_TOKEN_ENV_KEY, raising=False)

    assert load_api_token(tmp_path) == ""


def test_ping_accepts_the_configured_token(tmp_path: Path) -> None:
    """The settings page's connection test should succeed with a good token."""
    response = token_api.ping(_build_request(tmp_path))

    assert response.status_code == 200
    assert _body(response)["ok"] is True


@pytest.mark.parametrize(
    "authorization",
    [None, "Bearer wrong-token", VALID_TOKEN, f"Basic {VALID_TOKEN}"],
)
def test_ping_rejects_missing_wrong_and_malformed_authorization(
    tmp_path: Path, authorization: str | None
) -> None:
    """Only a well-formed bearer header holding the exact token is accepted."""
    request = _build_request(tmp_path, authorization=authorization)

    with pytest.raises(HTTPException) as raised:
        token_api.ping(request)

    assert raised.value.status_code == 401


def test_routes_report_unconfigured_when_no_token_is_set(tmp_path: Path) -> None:
    """Without a token the API says so, rather than accepting any caller."""
    request = _build_request(tmp_path, api_token="")

    with pytest.raises(HTTPException) as raised:
        token_api.ping(request)

    assert raised.value.status_code == 503
    assert "PODCAST_API_TOKEN" in raised.value.detail


def test_add_url_queues_a_video_and_wakes_the_scheduler(tmp_path: Path) -> None:
    """The extension's normal case: one video URL, queued and started."""
    request = _build_request(tmp_path)

    response = token_api.add_url(request, AddUrlRequest(url=YOUTUBE_VIDEO_URL))
    body = _body(response)

    assert response.status_code == 200
    assert body["outcome"] == AddUrlOutcome.ADDED
    assert body["immediate"] is True
    assert body["url"] == YOUTUBE_VIDEO_URL
    assert request.app.state.download_trigger.single_urls == [YOUTUBE_VIDEO_URL]
    assert YOUTUBE_VIDEO_URL in request.app.state.queue_store.read_urls()


def test_add_url_reports_a_duplicate_without_a_second_queue_entry(
    tmp_path: Path,
) -> None:
    """Sending the same page twice must not queue it twice."""
    request = _build_request(tmp_path)
    token_api.add_url(request, AddUrlRequest(url=YOUTUBE_VIDEO_URL))

    response = token_api.add_url(request, AddUrlRequest(url=YOUTUBE_VIDEO_URL))

    assert _body(response)["outcome"] == AddUrlOutcome.DUPLICATE
    assert request.app.state.queue_store.read_urls().count(YOUTUBE_VIDEO_URL) == 1


def test_add_url_reports_an_already_downloaded_url(tmp_path: Path) -> None:
    """A finished episode should be reported, not silently re-queued."""
    request = _build_request(tmp_path)
    request.app.state.archive_store.append(YOUTUBE_VIDEO_URL)

    response = token_api.add_url(request, AddUrlRequest(url=YOUTUBE_VIDEO_URL))

    assert _body(response)["outcome"] == AddUrlOutcome.ALREADY_DOWNLOADED
    assert request.app.state.queue_store.read_urls() == []


def test_add_url_rejects_an_unsupported_link_with_status_400(tmp_path: Path) -> None:
    """Clicking the button on a settings page must not write junk to urls.txt."""
    request = _build_request(tmp_path)

    response = token_api.add_url(
        request, AddUrlRequest(url="chrome://extensions")
    )

    assert response.status_code == 400
    assert _body(response)["outcome"] == AddUrlOutcome.INVALID
    assert request.app.state.queue_store.read_urls() == []


def test_add_url_writes_a_bypass_entry_only_when_asked(tmp_path: Path) -> None:
    """The immediate-download option is what creates the one-shot age bypass."""
    patient_request = _build_request(tmp_path / "patient")
    (tmp_path / "patient").mkdir()
    token_api.add_url(patient_request, AddUrlRequest(url=YOUTUBE_VIDEO_URL))
    assert patient_request.app.state.bypass_store.load() == set()

    impatient_request = _build_request(tmp_path / "impatient")
    (tmp_path / "impatient").mkdir()
    token_api.add_url(
        impatient_request,
        AddUrlRequest(url=YOUTUBE_VIDEO_URL, skip_age_check=True),
    )
    assert impatient_request.app.state.bypass_store.load() == {YOUTUBE_VIDEO_URL}


def test_add_url_starts_a_full_playlist_run_for_a_checked_playlist(
    tmp_path: Path,
) -> None:
    """A playlist with the immediate option wakes the playlist path, not the video path."""
    request = _build_request(tmp_path)

    token_api.add_url(
        request,
        AddUrlRequest(url=YOUTUBE_PLAYLIST_URL, skip_age_check=True),
    )

    trigger = request.app.state.download_trigger
    assert trigger.playlist_urls == [YOUTUBE_PLAYLIST_URL]
    assert trigger.single_urls == []


def test_add_url_leaves_a_channel_for_the_scheduled_pass(tmp_path: Path) -> None:
    """Channels ignore the immediate option so one click cannot pull a whole archive."""
    request = _build_request(tmp_path)

    response = token_api.add_url(
        request,
        AddUrlRequest(url=YOUTUBE_CHANNEL_URL, skip_age_check=True),
    )
    body = _body(response)

    assert body["outcome"] == AddUrlOutcome.ADDED
    assert body["immediate"] is False
    trigger = request.app.state.download_trigger
    assert trigger.single_urls == []
    assert trigger.playlist_urls == []


def test_shared_helper_normalizes_before_the_duplicate_check(tmp_path: Path) -> None:
    """Two spellings of one video must collapse to a single queue entry.

    This is the reason the form route and the API call the same helper: a
    youtu.be link pasted in the browser and a watch link sent by the extension
    are the same episode.
    """
    logger = logging.getLogger("test.web.queue_actions")
    stores = {
        "queue_store": QueueStore(tmp_path / "urls.txt", logger),
        "archive_store": ArchiveStore(tmp_path / "downloaded_urls.txt", logger),
        "bypass_store": BypassStore(tmp_path / "bypass.txt", logger),
        "download_trigger": _RecordingDownloadTrigger(),
    }

    first = add_url_to_queue(
        "https://youtu.be/dQw4w9WgXcQ?t=42", skip_age_check=False, **stores
    )
    second = add_url_to_queue(
        f"  {YOUTUBE_VIDEO_URL}  ", skip_age_check=False, **stores
    )

    assert first.outcome == AddUrlOutcome.ADDED
    assert second.outcome == AddUrlOutcome.DUPLICATE
    assert stores["queue_store"].read_urls() == [first.url]
