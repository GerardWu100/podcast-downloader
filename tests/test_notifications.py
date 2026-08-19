"""Tests for Apprise settings storage and notification delivery."""

from __future__ import annotations

import io
import json
import logging
import urllib.error
from pathlib import Path

from src.notifications.apprise_client import (
    AppriseNotifier,
    AppriseSettings,
    validate_server_url,
)
from src.state.notification_store import (
    NotificationStore,
    notification_settings_file_for,
)

_LOGGER = logging.getLogger("test.notifications")


class FakeResponse:
    """Stand-in for the context manager returned by ``urlopen``."""

    def __init__(self, status: int = 200) -> None:
        self.status = status

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_: object) -> bool:
        return False


def recording_opener(
    captured_requests: list[object],
    status: int = 200,
):
    """Return a fake ``urlopen`` that records requests instead of sending them."""

    def open_url(request: object, timeout: int = 0) -> FakeResponse:
        captured_requests.append(request)
        return FakeResponse(status)

    return open_url


def test_persistent_mode_sends_only_the_message() -> None:
    """With no destination URLs, the body carries just the message."""
    captured_requests: list[object] = []
    notifier = AppriseNotifier(
        AppriseSettings(enabled=True, server_url="http://apprise.test/notify/key"),
        _LOGGER,
        open_url=recording_opener(captured_requests),
    )

    result = notifier.notify_download_failure("https://example.test/v", "403 refused")

    assert result.ok is True
    assert result.status_code == 200
    request = captured_requests[0]
    payload = json.loads(request.data.decode("utf-8"))
    assert payload["title"] == "Podcast download failed"
    assert "403 refused" in payload["body"]
    assert payload["type"] == "failure"
    assert "urls" not in payload
    assert request.get_header("Content-type") == "application/json"


def test_stateless_mode_sends_destinations_and_tag() -> None:
    """Destination URLs and a tag travel with the message when configured."""
    captured_requests: list[object] = []
    notifier = AppriseNotifier(
        AppriseSettings(
            enabled=True,
            server_url="http://apprise.test/notify",
            notification_urls="tgram://token/chatid",
            tag="podcasts",
        ),
        _LOGGER,
        open_url=recording_opener(captured_requests),
    )

    notifier.send("title", "body")

    payload = json.loads(captured_requests[0].data.decode("utf-8"))
    assert payload["urls"] == "tgram://token/chatid"
    assert payload["tag"] == "podcasts"


def test_disabled_notifier_sends_nothing() -> None:
    """Turning notifications off must stop the request from being made."""
    captured_requests: list[object] = []
    notifier = AppriseNotifier(
        AppriseSettings(enabled=False, server_url="http://apprise.test/notify/key"),
        _LOGGER,
        open_url=recording_opener(captured_requests),
    )

    result = notifier.send("title", "body")

    assert result.ok is False
    assert captured_requests == []


def test_rejected_notification_reports_the_server_message() -> None:
    """An Apprise rejection should surface its own explanation."""

    def open_url(request: object, timeout: int = 0):
        raise urllib.error.HTTPError(
            "http://apprise.test/notify/key",
            424,
            "Failed Dependency",
            {},
            io.BytesIO(b'{"error": "no notifications could be sent"}'),
        )

    notifier = AppriseNotifier(
        AppriseSettings(enabled=True, server_url="http://apprise.test/notify/key"),
        _LOGGER,
        open_url=open_url,
    )

    result = notifier.send("title", "body")

    assert result.ok is False
    assert result.status_code == 424
    assert "no notifications could be sent" in result.detail


def test_unreachable_instance_reports_the_cause_without_raising() -> None:
    """A dead Apprise instance must not raise into the download code."""

    def open_url(request: object, timeout: int = 0):
        raise urllib.error.URLError("Connection refused")

    notifier = AppriseNotifier(
        AppriseSettings(enabled=True, server_url="http://apprise.test/notify/key"),
        _LOGGER,
        open_url=open_url,
    )

    result = notifier.send("title", "body")

    assert result.ok is False
    assert result.status_code is None
    assert "Connection refused" in result.detail


def test_only_http_urls_are_accepted() -> None:
    """Non-HTTP schemes are refused before any request is attempted."""
    assert validate_server_url("http://apprise.test/notify/key") == ""
    assert validate_server_url("https://apprise.test/notify/key") == ""
    assert validate_server_url("") != ""
    assert validate_server_url("ftp://apprise.test/notify") != ""
    assert validate_server_url("file:///etc/passwd") != ""
    assert validate_server_url("http://") != ""


def test_settings_survive_a_save_and_load_round_trip(tmp_path: Path) -> None:
    """The web server writes the file and the downloader process reads it."""
    store = NotificationStore(notification_settings_file_for(tmp_path))
    saved_settings = AppriseSettings(
        enabled=True,
        server_url="  http://apprise.test/notify/key  ",
        notification_urls=" tgram://token/chatid ",
        tag=" podcasts ",
    )

    store.save(saved_settings)
    loaded_settings = NotificationStore(
        notification_settings_file_for(tmp_path)
    ).load()

    assert loaded_settings.enabled is True
    assert loaded_settings.server_url == "http://apprise.test/notify/key"
    assert loaded_settings.notification_urls == "tgram://token/chatid"
    assert loaded_settings.tag == "podcasts"


def test_settings_file_is_owner_only(tmp_path: Path) -> None:
    """The endpoint usually embeds a key, so the file must not be world-readable."""
    settings_file = notification_settings_file_for(tmp_path)
    NotificationStore(settings_file).save(
        AppriseSettings(enabled=True, server_url="http://apprise.test/notify/secret")
    )

    assert settings_file.stat().st_mode & 0o077 == 0


def test_missing_or_damaged_settings_fall_back_to_defaults(tmp_path: Path) -> None:
    """A missing or corrupt file must not stop the downloader from starting."""
    settings_file = notification_settings_file_for(tmp_path)

    assert NotificationStore(settings_file).load() == AppriseSettings()

    settings_file.write_text("not json at all", encoding="utf-8")
    assert NotificationStore(settings_file).load() == AppriseSettings()


def test_settings_are_not_ready_without_an_endpoint() -> None:
    """Enabling notifications with no URL must not attempt a request."""
    assert AppriseSettings(enabled=True, server_url="").is_ready() is False
    assert AppriseSettings(enabled=False, server_url="http://x.test/n").is_ready() is False
    assert AppriseSettings(enabled=True, server_url="http://x.test/n").is_ready() is True
