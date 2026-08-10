"""Behavioral tests for queue-file utilities."""

from __future__ import annotations

import fcntl
import logging
import multiprocessing
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from src.media import youtube
from src.media.youtube import (
    expand_channel_or_playlist,
    get_youtube_playlist_folder_name,
    is_youtube_short_url,
    is_youtube_url,
    normalize_youtube_url,
)
from src.state.archive_store import ArchiveStore
from src.state.bypass_store import BypassStore
from src.state.queue_store import QueueStore


def _lock_then_rewrite_queue(
    urls_file: str,
    ready_file: str,
    release_file: str,
) -> None:
    """Hold an exclusive lock, then rewrite the queue once released by the test."""
    queue_path = Path(urls_file)
    ready_path = Path(ready_file)
    release_path = Path(release_file)

    with open(queue_path, "r+", encoding="utf-8") as file_handle:
        fcntl.flock(file_handle.fileno(), fcntl.LOCK_EX)
        ready_path.write_text("ready", encoding="utf-8")

        while not release_path.exists():
            time.sleep(0.01)

        file_handle.seek(0)
        file_handle.truncate()

        fcntl.flock(file_handle.fileno(), fcntl.LOCK_UN)


def test_queue_store_create_sample_file_creates_parent_directories(tmp_path) -> None:
    """Creating the sample queue file should work for nested config paths."""
    urls_file = tmp_path / "nested" / "queue" / "urls.txt"

    QueueStore(urls_file, logging.getLogger("test")).create_sample_file()

    assert urls_file.exists()
    assert "Podcast URLs" in urls_file.read_text(encoding="utf-8")


def test_queue_store_append_waits_for_lock_and_preserves_new_entry(tmp_path) -> None:
    """Appending should block on an in-progress rewrite instead of losing new URLs."""
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text("https://www.youtube.com/watch?v=abc123\n", encoding="utf-8")
    ready_file = tmp_path / "ready"
    release_file = tmp_path / "release"

    process = multiprocessing.Process(
        target=_lock_then_rewrite_queue,
        args=(str(urls_file), str(ready_file), str(release_file)),
    )
    process.start()

    try:
        deadline = time.time() + 5
        while not ready_file.exists() and time.time() < deadline:
            time.sleep(0.01)

        assert ready_file.exists(), (
            "helper process did not acquire the queue lock in time"
        )

        result: dict[str, int] = {}
        store = QueueStore(urls_file, logging.getLogger("test"))

        def append_in_thread() -> None:
            result["added"] = store.append_urls(
                ["https://www.youtube.com/watch?v=new456"],
            )

        thread = threading.Thread(target=append_in_thread)
        thread.start()

        time.sleep(0.1)
        release_file.write_text("release", encoding="utf-8")

        thread.join(timeout=5)
        process.join(timeout=5)

        assert not thread.is_alive(), "QueueStore.append_urls did not finish"
        assert process.exitcode == 0
        assert result["added"] == 1
        assert (
            urls_file.read_text(encoding="utf-8")
            == "https://www.youtube.com/watch?v=new456\n"
        )
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)


def test_queue_store_accepts_non_youtube_video_urls(tmp_path) -> None:
    """The queue should accept direct videos from any yt-dlp-supported website URL."""
    urls_file = tmp_path / "urls.txt"
    non_youtube_url = "https://videos.example.com/watch/episode-1"
    store = QueueStore(urls_file, logging.getLogger("test"))

    added = store.append_urls([non_youtube_url])
    loaded_urls = store.read_urls()

    assert added == 1
    assert loaded_urls == [non_youtube_url]


def test_queue_store_appends_reads_and_removes_normalized_urls(tmp_path) -> None:
    """QueueStore should own queue mutation without changing wrapper behavior."""
    urls_file = tmp_path / "urls.txt"
    store = QueueStore(urls_file, logging.getLogger("test"))

    added = store.append_urls(
        [
            "https://youtu.be/abc123",
            "https://videos.example.com/watch/episode-1",
            "not-a-url",
        ]
    )
    loaded_urls = store.read_urls()
    removed = store.remove_url("https://www.youtube.com/watch?v=abc123")

    assert added == 2
    assert loaded_urls == [
        "https://www.youtube.com/watch?v=abc123",
        "https://videos.example.com/watch/episode-1",
    ]
    assert removed is True
    assert urls_file.read_text(encoding="utf-8") == (
        "https://videos.example.com/watch/episode-1\n"
    )


def test_archive_store_append_returns_true_only_once(tmp_path) -> None:
    """ArchiveStore.append should record one normalized expanded URL once."""
    archive_file = tmp_path / "downloaded_urls.txt"
    store = ArchiveStore(archive_file, logging.getLogger("test"))

    first_append = store.append("https://youtu.be/abc123")
    second_append = store.append("https://www.youtube.com/watch?v=abc123")

    assert first_append is True
    assert second_append is False
    assert store.load() == {"https://www.youtube.com/watch?v=abc123"}


def test_archive_store_remove_deletes_only_matching_normalized_url(tmp_path) -> None:
    """ArchiveStore.remove should rewrite the archive without duplicating entries."""
    archive_file = tmp_path / "downloaded_urls.txt"
    archive_file.write_text(
        "https://youtu.be/abc123\nhttps://www.youtube.com/watch?v=keep456\n",
        encoding="utf-8",
    )
    store = ArchiveStore(archive_file, logging.getLogger("test"))

    removed = store.remove("https://www.youtube.com/watch?v=abc123")

    assert removed is True
    assert archive_file.read_text(encoding="utf-8") == (
        "https://www.youtube.com/watch?v=keep456\n"
    )


def test_bypass_store_adds_loads_and_removes_normalized_urls(tmp_path) -> None:
    """BypassStore should own one-shot age-bypass state."""
    bypass_file = tmp_path / "bypass_age_check_urls.txt"
    store = BypassStore(bypass_file, logging.getLogger("test"))

    store.add("https://youtu.be/abc123")
    loaded_before_remove = store.load()
    store.remove("https://www.youtube.com/watch?v=abc123")

    assert loaded_before_remove == {"https://www.youtube.com/watch?v=abc123"}
    assert store.load() == set()


def test_bypass_store_consumes_url_exactly_once(tmp_path: Path) -> None:
    """A one-use age override should disappear during its first claim."""
    bypass_file = tmp_path / "bypass_age_check_urls.txt"
    store = BypassStore(bypass_file, logging.getLogger("test"))
    store.add("https://youtu.be/abc123")

    first_claim = store.consume("https://www.youtube.com/watch?v=abc123")
    second_claim = store.consume("https://www.youtube.com/watch?v=abc123")

    assert first_claim is True
    assert second_claim is False


def test_queue_store_remove_deletes_matching_normalized_entry(tmp_path) -> None:
    """Removing from the monitored queue should match normalized YouTube URLs."""
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(
        "\n".join(
            [
                "# comment",
                "https://youtu.be/abc123",
                "https://www.youtube.com/@channelname",
                "",
            ]
        ),
        encoding="utf-8",
    )

    store = QueueStore(urls_file, logging.getLogger("test"))
    removed = store.remove_url("https://www.youtube.com/watch?v=abc123")

    assert removed is True
    assert (
        urls_file.read_text(encoding="utf-8")
        == "# comment\nhttps://www.youtube.com/@channelname\n"
    )


def test_queue_store_remove_returns_false_when_missing(tmp_path) -> None:
    """Removing a missing URL should report failure without changing the file."""
    urls_file = tmp_path / "urls.txt"
    original_text = "https://www.youtube.com/watch?v=keepme\n"
    urls_file.write_text(original_text, encoding="utf-8")

    store = QueueStore(urls_file, logging.getLogger("test"))
    removed = store.remove_url("https://www.youtube.com/watch?v=missing")

    assert removed is False
    assert urls_file.read_text(encoding="utf-8") == original_text


def test_date_only_age_check_respects_configured_hour_threshold(monkeypatch) -> None:
    """Date-only metadata should not pass a multi-hour gate just because the day changed."""

    class FixedDateTime(datetime):
        """Datetime test double with a fixed current time."""

        @classmethod
        def now(cls, tz=None) -> datetime:
            current_time = datetime(2026, 5, 3, 1, 0, tzinfo=timezone.utc)
            if tz is None:
                return current_time.replace(tzinfo=None)
            return current_time.astimezone(tz)

    monkeypatch.setattr(youtube, "datetime", FixedDateTime)

    age_ok = youtube.is_old_enough(
        timestamp_raw="",
        upload_date="20260502",
        min_channel_video_age_hours=24,
    )

    assert age_ok is False


def test_playlist_expansion_limits_ytdlp_fetch_to_channel_count(monkeypatch) -> None:
    """Playlist expansion should fetch only the configured latest entries."""
    playlist_url = "https://www.youtube.com/playlist?list=PL123"
    captured_command: list[str] = []

    def fake_run(
        command: list[str],
        *args,
        **kwargs,
    ) -> subprocess.CompletedProcess[str]:
        captured_command.extend(command)
        stdout = "\n".join(
            [
                "https://www.youtube.com/watch?v=video001\tNA\t20260501",
                "https://www.youtube.com/watch?v=video002\tNA\t20260430",
            ]
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(youtube.subprocess, "run", fake_run)

    video_urls = expand_channel_or_playlist(
        playlist_url,
        channel_count=2,
        min_channel_video_age_hours=24,
        logger=logging.getLogger("test"),
    )

    assert video_urls == [
        "https://www.youtube.com/watch?v=video001",
        "https://www.youtube.com/watch?v=video002",
    ]
    assert "--playlist-end" in captured_command
    assert captured_command[captured_command.index("--playlist-end") + 1] == "2"


def test_playlist_expansion_can_fetch_every_entry_when_full_playlist_enabled(
    monkeypatch,
) -> None:
    """Full playlist expansion should omit the playlist-end cap."""
    playlist_url = "https://www.youtube.com/playlist?list=PL123"
    captured_command: list[str] = []

    def fake_run(
        command: list[str],
        *args,
        **kwargs,
    ) -> subprocess.CompletedProcess[str]:
        captured_command.extend(command)
        stdout = "\n".join(
            [
                "https://www.youtube.com/watch?v=video001\tNA\t20260501",
                "https://www.youtube.com/watch?v=video002\tNA\t20260430",
                "https://www.youtube.com/watch?v=video003\tNA\t20260429",
            ]
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(youtube.subprocess, "run", fake_run)

    video_urls = expand_channel_or_playlist(
        playlist_url,
        channel_count=2,
        min_channel_video_age_hours=24,
        logger=logging.getLogger("test"),
        full_playlist=True,
    )

    assert video_urls == [
        "https://www.youtube.com/watch?v=video001",
        "https://www.youtube.com/watch?v=video002",
        "https://www.youtube.com/watch?v=video003",
    ]
    assert "--playlist-end" not in captured_command


def test_playlist_title_lookup_fetches_only_one_metadata_entry(monkeypatch) -> None:
    """Playlist folder naming should not enumerate a full large playlist."""
    playlist_url = "https://www.youtube.com/playlist?list=PL123"
    captured_command: list[str] = []

    def fake_run(
        command: list[str],
        *args,
        **kwargs,
    ) -> subprocess.CompletedProcess[str]:
        captured_command.extend(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="Readable Playlist\n",
            stderr="",
        )

    monkeypatch.setattr(youtube.subprocess, "run", fake_run)

    folder_name = get_youtube_playlist_folder_name(
        playlist_url,
        logging.getLogger("test"),
    )

    assert folder_name == "Readable Playlist"
    assert "--playlist-end" in captured_command
    assert captured_command[captured_command.index("--playlist-end") + 1] == "1"


def test_na_timestamp_falls_back_to_upload_date(monkeypatch) -> None:
    """The yt-dlp NA placeholder should not hide usable date-only metadata."""

    class FixedDateTime(datetime):
        """Datetime test double with a fixed current time."""

        @classmethod
        def now(cls, tz=None) -> datetime:
            current_time = datetime(2026, 5, 3, 1, 0, tzinfo=timezone.utc)
            if tz is None:
                return current_time.replace(tzinfo=None)
            return current_time.astimezone(tz)

    monkeypatch.setattr(youtube, "datetime", FixedDateTime)

    age_ok = youtube.is_old_enough(
        timestamp_raw="NA",
        upload_date="20260502",
        min_channel_video_age_hours=24,
    )

    assert age_ok is False


def test_youtube_short_url_detection_is_youtube_only() -> None:
    """A non-YouTube URL with a /shorts/ path should remain a normal direct URL."""
    assert is_youtube_short_url("https://www.youtube.com/shorts/abc123") is True
    assert is_youtube_short_url("https://videos.example.com/shorts/abc123") is False


def test_youtube_host_normalization_accepts_case_default_port_and_mobile_host() -> None:
    """YouTube host checks should tolerate common host variants before normalization."""
    assert is_youtube_url("https://WWW.YOUTUBE.COM/watch?v=abc123") is True
    assert is_youtube_url("https://www.youtube.com:443/watch?v=abc123") is True
    assert is_youtube_url("https://m.youtube.com/watch?v=abc123") is True

    assert (
        normalize_youtube_url("https://WWW.YOUTUBE.COM/watch?v=abc123")
        == "https://www.youtube.com/watch?v=abc123"
    )
    assert (
        normalize_youtube_url("https://www.youtube.com:443/watch?v=abc123")
        == "https://www.youtube.com/watch?v=abc123"
    )
    assert (
        normalize_youtube_url("https://m.youtube.com/watch?v=abc123")
        == "https://www.youtube.com/watch?v=abc123"
    )


def test_youtube_live_url_normalizes_to_watch_url() -> None:
    """A completed livestream should use the same identity as a normal video."""
    assert (
        normalize_youtube_url("https://www.youtube.com/live/hPwmCl_nLiQ")
        == "https://www.youtube.com/watch?v=hPwmCl_nLiQ"
    )
    assert (
        normalize_youtube_url("https://youtube.com/live/hPwmCl_nLiQ?si=share-token")
        == "https://www.youtube.com/watch?v=hPwmCl_nLiQ"
    )


def test_youtube_trailing_slash_gives_the_same_identity_as_the_clean_url() -> None:
    """A pasted trailing slash must not create a second identity for one video.

    The queue, the one-shot bypass file, and the downloaded-URL archive all
    compare normalized URLs. If ``youtu.be/ID/`` normalized to a watch URL whose
    video id still carried the slash, the same video could sit in the queue
    twice and be downloaded twice.
    """
    canonical = "https://www.youtube.com/watch?v=hPwmCl_nLiQ"

    assert normalize_youtube_url("https://youtu.be/hPwmCl_nLiQ/") == canonical
    assert normalize_youtube_url("https://www.youtube.com/watch/?v=hPwmCl_nLiQ") == (
        canonical
    )
    assert normalize_youtube_url("https://www.youtube.com/live/hPwmCl_nLiQ/") == (
        canonical
    )


def test_non_youtube_host_is_not_misclassified_as_youtube() -> None:
    """A lookalike domain should stay a normal direct URL."""
    url = "https://notyoutube.com/watch?v=abc123"

    assert is_youtube_url(url) is False
    assert normalize_youtube_url(url) == url


def test_get_youtube_channel_folder_name_prefers_handle(
    monkeypatch,
) -> None:
    """Opaque channel IDs should resolve to stable ``@`` handles when available."""
    captured_commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        *args,
        **kwargs,
    ) -> subprocess.CompletedProcess[str]:
        captured_commands.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="The Compound\t@TheCompoundNews\n",
            stderr="",
        )

    monkeypatch.setattr(youtube.subprocess, "run", fake_run)

    folder_name = youtube.get_youtube_channel_folder_name(
        "https://www.youtube.com/channel/UCBRpqrzuuqE8TZcWw75JSdw/videos",
        logging.getLogger("test.channel.folder"),
        None,
    )

    assert folder_name == "TheCompoundNews"
    assert captured_commands[0][captured_commands[0].index("--print") + 1] == (
        "%(channel)s\t%(uploader_id)s"
    )


def test_get_youtube_channel_display_name_avoids_channel_id(
    monkeypatch,
) -> None:
    """Display names should not fall back to opaque YouTube channel IDs."""

    def fake_run(
        command: list[str],
        *args,
        **kwargs,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="UCBRpqrzuuqE8TZcWw75JSdw\tThe Compound\n",
            stderr="",
        )

    monkeypatch.setattr(youtube.subprocess, "run", fake_run)

    display_name = youtube.get_youtube_channel_display_name(
        "https://www.youtube.com/watch?v=LgmzAXMBbu4",
        logging.getLogger("test.channel.display"),
        None,
    )

    assert display_name == "The Compound"
