"""Behaviour tests for the JSON API used by the browser extension."""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.credentials import CREDENTIALS_FILENAME
from src.passwords import hash_password
from src.state.archive_store import ArchiveStore
from src.state.auth_store import AuthStore
from src.state.bypass_store import BypassStore
from src.state.queue_store import QueueStore
from src.state.run_state_store import RunKind, RunStateStore, run_state_file_for
from src.web import api_routes, routes
from src.web.account_auth import (
    MAX_CREDENTIAL_LENGTH,
    MAX_FAILED_ATTEMPTS,
    CredentialCheck,
    check_credentials,
)
from src.web.api_routes import AddUrlRequest
from src.web.queue_actions import AddUrlOutcome, add_url_to_queue

ACCOUNT_NAME = "listener"
ACCOUNT_PASSWORD = "a-real-password"
YOUTUBE_VIDEO_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
YOUTUBE_PLAYLIST_URL = "https://www.youtube.com/playlist?list=PL0000000000"
YOUTUBE_CHANNEL_URL = "https://www.youtube.com/@examplechannel"


class _RecordingDownloadTrigger:
    """Capture scheduler wake-ups instead of touching the shared queues."""

    def __init__(self) -> None:
        self.single_urls: list[str] = []
        self.playlist_urls: list[str] = []
        self.full_queue_runs = 0

    def queue_single_url_download(self, url: str) -> None:
        """Record one direct-media request."""
        self.single_urls.append(url)

    def queue_full_playlist_download(self, url: str) -> None:
        """Record one full-playlist request."""
        self.playlist_urls.append(url)

    def queue_full_queue_run(self) -> None:
        """Record one whole-queue request."""
        self.full_queue_runs += 1


def _basic_header(username: str, password: str) -> str:
    """Return the ``Authorization`` value a client sends for these credentials."""
    encoded = base64.b64encode(f"{username}:{password}".encode("utf-8"))
    return f"Basic {encoded.decode('ascii')}"


def _write_accounts(tmp_path: Path) -> Path:
    """Write one account file the way startup credential syncing does."""
    credentials_file = tmp_path / CREDENTIALS_FILENAME
    credentials_file.write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "username": ACCOUNT_NAME,
                        "password_hash": hash_password(ACCOUNT_PASSWORD),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return credentials_file


def _build_request(
    tmp_path: Path,
    *,
    authorization: str | None = None,
    with_accounts: bool = True,
) -> SimpleNamespace:
    """Return a request double carrying the state ``create_app`` attaches.

    Parameters
    ----------
    tmp_path:
        Directory that receives the queue, archive, bypass, and account files.
    authorization:
        Value for the ``Authorization`` header. ``None`` sends the correct
        credentials; pass a string to send something else, or ``""`` to omit
        the header.
    with_accounts:
        False writes no account file, which is how a server that has never been
        configured behaves.

    Returns
    -------
    SimpleNamespace
        Object exposing the ``headers``, ``client``, and ``app.state``
        attributes the routes read.
    """
    logger = logging.getLogger("test.web.api_routes")
    credentials_file = (
        _write_accounts(tmp_path) if with_accounts else tmp_path / CREDENTIALS_FILENAME
    )

    if authorization is None:
        authorization = _basic_header(ACCOUNT_NAME, ACCOUNT_PASSWORD)
    headers = {"authorization": authorization} if authorization else {}

    state = SimpleNamespace(
        config=replace(routes.CONFIG, trust_x_forwarded_for=False),
        credentials_file=credentials_file,
        auth_store=AuthStore(
            session_file=tmp_path / ".ui_sessions.json",
            login_state_file=tmp_path / ".login_state.json",
        ),
        queue_store=QueueStore(tmp_path / "urls.txt", logger),
        archive_store=ArchiveStore(tmp_path / "downloaded_urls.txt", logger),
        bypass_store=BypassStore(tmp_path / "bypass_age_check_urls.txt", logger),
        run_state_store=RunStateStore(run_state_file_for(tmp_path)),
        download_trigger=_RecordingDownloadTrigger(),
    )
    return SimpleNamespace(
        headers=headers,
        client=SimpleNamespace(host="127.0.0.1"),
        app=SimpleNamespace(state=state),
    )


def _body(response) -> dict:
    """Decode a JSONResponse body into a dictionary."""
    return json.loads(response.body.decode("utf-8"))


def test_ping_accepts_a_correct_username_and_password(tmp_path: Path) -> None:
    """The settings page's connection test should succeed with real credentials."""
    response = api_routes.ping(_build_request(tmp_path))

    assert response.status_code == 200
    assert _body(response)["ok"] is True


@pytest.mark.parametrize(
    ("authorization", "reason"),
    [
        ("", "no header at all"),
        (_basic_header(ACCOUNT_NAME, "wrong-password"), "wrong password"),
        (_basic_header("nobody", ACCOUNT_PASSWORD), "unknown account"),
    ],
)
def test_ping_rejects_bad_credentials_with_status_401(
    tmp_path: Path, authorization: str, reason: str
) -> None:
    """A wrong name and a wrong password must be refused the same way."""
    request = _build_request(tmp_path, authorization=authorization)

    with pytest.raises(HTTPException) as raised:
        api_routes.ping(request)

    assert raised.value.status_code == 401, reason


@pytest.mark.parametrize(
    "authorization",
    [
        "Bearer abc123",
        "Basic not-valid-base64!!",
        "Basic " + base64.b64encode(b"no-colon-here").decode("ascii"),
    ],
)
def test_ping_rejects_a_malformed_authorization_header(
    tmp_path: Path, authorization: str
) -> None:
    """Anything that is not a decodable Basic header is refused, not crashed on."""
    request = _build_request(tmp_path, authorization=authorization)

    with pytest.raises(HTTPException) as raised:
        api_routes.ping(request)

    assert raised.value.status_code == 401


def test_wrong_password_does_not_reveal_whether_the_account_exists(
    tmp_path: Path,
) -> None:
    """Both refusals must carry the identical message.

    A different message for "no such user" would let anyone enumerate the
    account names on the server.
    """
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    wrong_password = _build_request(
        tmp_path / "a", authorization=_basic_header(ACCOUNT_NAME, "nope")
    )
    unknown_account = _build_request(
        tmp_path / "b", authorization=_basic_header("ghost", ACCOUNT_PASSWORD)
    )

    with pytest.raises(HTTPException) as first:
        api_routes.ping(wrong_password)
    with pytest.raises(HTTPException) as second:
        api_routes.ping(unknown_account)

    assert first.value.detail == second.value.detail


def test_repeated_failures_ban_the_address(tmp_path: Path) -> None:
    """The API shares the login page's ban, so it cannot be brute-forced freely."""
    request = _build_request(
        tmp_path, authorization=_basic_header(ACCOUNT_NAME, "wrong")
    )

    for _attempt in range(MAX_FAILED_ATTEMPTS):
        with pytest.raises(HTTPException):
            api_routes.ping(request)

    # The ban now applies even to the correct password.
    request.headers["authorization"] = _basic_header(ACCOUNT_NAME, ACCOUNT_PASSWORD)
    with pytest.raises(HTTPException) as raised:
        api_routes.ping(request)

    assert raised.value.status_code == 429


def test_a_successful_sign_in_clears_earlier_failures(tmp_path: Path) -> None:
    """One typo must not count toward a ban once the real password works."""
    request = _build_request(
        tmp_path, authorization=_basic_header(ACCOUNT_NAME, "typo")
    )
    with pytest.raises(HTTPException):
        api_routes.ping(request)

    request.headers["authorization"] = _basic_header(ACCOUNT_NAME, ACCOUNT_PASSWORD)
    api_routes.ping(request)

    login_state = request.app.state.auth_store.load_login_state()
    assert login_state["127.0.0.1"]["failed"] == 0


def test_routes_report_when_no_accounts_are_configured(tmp_path: Path) -> None:
    """A server with no accounts says so instead of accepting any caller."""
    request = _build_request(tmp_path, with_accounts=False)

    with pytest.raises(HTTPException) as raised:
        api_routes.ping(request)

    assert raised.value.status_code == 503
    assert "UI_USERNAME" in raised.value.detail


def test_add_url_queues_a_video_and_wakes_the_scheduler(tmp_path: Path) -> None:
    """The extension's normal case: one video URL, queued and started."""
    request = _build_request(tmp_path)

    response = api_routes.add_url(request, AddUrlRequest(url=YOUTUBE_VIDEO_URL))
    body = _body(response)

    assert response.status_code == 200
    assert body["outcome"] == AddUrlOutcome.ADDED
    assert body["immediate"] is True
    assert body["url"] == YOUTUBE_VIDEO_URL
    assert request.app.state.download_trigger.single_urls == [YOUTUBE_VIDEO_URL]
    assert YOUTUBE_VIDEO_URL in request.app.state.queue_store.read_urls()


def test_add_url_does_not_log_the_submitted_url(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Signed query strings and URL user information must stay out of API logs."""
    secret_url = "https://videos.example.com/watch/episode?token=private-value"
    request = _build_request(tmp_path)

    with caplog.at_level(logging.INFO, logger="web.api_routes"):
        api_routes.add_url(request, AddUrlRequest(url=secret_url))

    assert "private-value" not in caplog.text
    assert "API add-url outcome" in caplog.text


def test_add_url_refuses_a_bad_password_before_touching_the_queue(
    tmp_path: Path,
) -> None:
    """Sign-in is checked first, so a stranger cannot write to urls.txt."""
    request = _build_request(
        tmp_path, authorization=_basic_header(ACCOUNT_NAME, "wrong")
    )

    with pytest.raises(HTTPException):
        api_routes.add_url(request, AddUrlRequest(url=YOUTUBE_VIDEO_URL))

    assert request.app.state.queue_store.read_urls() == []


def test_add_url_reports_a_duplicate_without_a_second_queue_entry(
    tmp_path: Path,
) -> None:
    """Sending the same page twice must not queue it twice."""
    request = _build_request(tmp_path)
    api_routes.add_url(request, AddUrlRequest(url=YOUTUBE_VIDEO_URL))

    response = api_routes.add_url(request, AddUrlRequest(url=YOUTUBE_VIDEO_URL))

    assert _body(response)["outcome"] == AddUrlOutcome.DUPLICATE
    assert request.app.state.queue_store.read_urls().count(YOUTUBE_VIDEO_URL) == 1


def test_add_url_reports_an_already_downloaded_url(tmp_path: Path) -> None:
    """A finished episode should be reported, not silently re-queued."""
    request = _build_request(tmp_path)
    request.app.state.archive_store.append(YOUTUBE_VIDEO_URL)

    response = api_routes.add_url(request, AddUrlRequest(url=YOUTUBE_VIDEO_URL))

    assert _body(response)["outcome"] == AddUrlOutcome.ALREADY_DOWNLOADED
    assert request.app.state.queue_store.read_urls() == []


def test_add_url_rejects_an_unsupported_link_with_status_400(tmp_path: Path) -> None:
    """Clicking the button on a settings page must not write junk to urls.txt."""
    request = _build_request(tmp_path)

    response = api_routes.add_url(request, AddUrlRequest(url="chrome://extensions"))

    assert response.status_code == 400
    assert _body(response)["outcome"] == AddUrlOutcome.INVALID
    assert request.app.state.queue_store.read_urls() == []


def test_add_url_writes_a_bypass_entry_only_when_asked(tmp_path: Path) -> None:
    """The immediate-download option is what creates the one-shot age bypass."""
    (tmp_path / "patient").mkdir()
    (tmp_path / "impatient").mkdir()

    patient_request = _build_request(tmp_path / "patient")
    api_routes.add_url(patient_request, AddUrlRequest(url=YOUTUBE_VIDEO_URL))
    assert patient_request.app.state.bypass_store.load() == set()

    impatient_request = _build_request(tmp_path / "impatient")
    api_routes.add_url(
        impatient_request,
        AddUrlRequest(url=YOUTUBE_VIDEO_URL, skip_age_check=True),
    )
    assert impatient_request.app.state.bypass_store.load() == {YOUTUBE_VIDEO_URL}


def test_add_url_starts_a_full_playlist_run_for_a_checked_playlist(
    tmp_path: Path,
) -> None:
    """A playlist with the immediate option wakes the playlist path, not the video path."""
    request = _build_request(tmp_path)

    api_routes.add_url(
        request,
        AddUrlRequest(url=YOUTUBE_PLAYLIST_URL, skip_age_check=True),
    )

    trigger = request.app.state.download_trigger
    assert trigger.playlist_urls == [YOUTUBE_PLAYLIST_URL]
    assert trigger.single_urls == []


def test_add_url_leaves_a_channel_for_the_scheduled_pass(tmp_path: Path) -> None:
    """Channels ignore the immediate option so one click cannot pull a whole archive."""
    request = _build_request(tmp_path)

    response = api_routes.add_url(
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


def test_cheap_refusals_never_read_the_account_file(tmp_path: Path) -> None:
    """A banned or absurd submission must not cost a disk read.

    ``check_credentials`` takes a callable rather than a ready list precisely so
    the ban check and the length check run first. Without this, anyone could
    make every attempt read ``.ui_credentials.json`` from disk.
    """
    reads: list[str] = []

    def counting_loader() -> list:
        reads.append("read")
        return []

    auth_store = AuthStore(
        session_file=tmp_path / ".ui_sessions.json",
        login_state_file=tmp_path / ".login_state.json",
    )

    # An oversized password is refused before the file is consulted.
    oversized = check_credentials(
        "someone",
        "x" * (MAX_CREDENTIAL_LENGTH + 1),
        load_accounts=counting_loader,
        auth_store=auth_store,
        client_address="10.0.0.9",
    )
    assert oversized is CredentialCheck.OVERSIZED
    assert reads == []

    # A normal attempt does read it, which is what makes the check above mean
    # something.
    check_credentials(
        "someone",
        "short-enough",
        load_accounts=counting_loader,
        auth_store=auth_store,
        client_address="10.0.0.9",
    )
    assert reads == ["read"]


def test_health_reports_ok_after_a_run_that_finished_on_time(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A monitor polling this needs a 200 while the schedule is being kept."""
    from datetime import timedelta

    request = _build_request(tmp_path)
    store = RunStateStore(run_state_file_for(tmp_path))
    store.mark_run_started(RunKind.SCHEDULED)
    store.mark_run_finished()

    # The store stamps the real clock, so the reference instant is taken from
    # what it wrote. That keeps the test correct on any day of the year.
    finished_at = store.load().finished_at
    assert finished_at is not None
    monkeypatch.setattr(
        api_routes, "local_now", lambda: finished_at + timedelta(minutes=30)
    )

    response = api_routes.health(request)
    body = _body(response)

    assert response.status_code == 200
    assert body["ok"] is True
    assert body["status"] == "ok"
    assert body["last_run_finished_at"] == finished_at.isoformat()
    assert body["next_run_at"] > finished_at.isoformat()


def test_health_returns_503_when_the_scheduled_run_never_happened(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """The status code carries the answer, so a monitor needs no JSON parsing.

    This is the case nothing inside the container can report: a scheduler that
    stopped sends no failure, because no download was ever attempted.
    """
    from datetime import datetime

    from src.log_timezone import LOG_TIME_ZONE

    request = _build_request(tmp_path)
    # Well past the 06:00 run on 2026-09-03, with the last run two days before.
    monkeypatch.setattr(
        api_routes,
        "local_now",
        lambda: datetime(2026, 9, 3, 20, 0, tzinfo=LOG_TIME_ZONE),
    )

    response = api_routes.health(request)
    body = _body(response)

    assert response.status_code == 503
    assert body["ok"] is False
    assert body["status"] == "overdue"
    assert body["last_run_finished_at"] is None


def test_health_treats_a_run_in_progress_as_healthy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A long run is not a failed run, whatever the clock says."""
    from datetime import datetime

    from src.log_timezone import LOG_TIME_ZONE

    request = _build_request(tmp_path)
    monkeypatch.setattr(
        api_routes,
        "local_now",
        lambda: datetime(2026, 9, 3, 20, 0, tzinfo=LOG_TIME_ZONE),
    )
    RunStateStore(run_state_file_for(tmp_path)).mark_run_started(RunKind.SCHEDULED)

    response = api_routes.health(request)

    assert response.status_code == 200
    assert _body(response)["status"] == "running"


def test_health_requires_an_account(tmp_path: Path) -> None:
    """The endpoint reports deployment state, so it stays behind the accounts."""
    request = _build_request(tmp_path, authorization="")

    with pytest.raises(HTTPException) as refusal:
        api_routes.health(request)

    assert refusal.value.status_code == 401
