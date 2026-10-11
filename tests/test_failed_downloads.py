"""Tests for dropping videos after repeated failures that blame the video."""

from __future__ import annotations

import subprocess

import src.downloads.service as downloads_service_module
from src.downloads.service import DownloadTarget, PodcastDownloadService

VIDEO_URL = "https://www.youtube.com/watch?v=dead123"
DEAD_VIDEO_ERROR = "ERROR: [youtube] dead123: Video unavailable"
BLOCKED_ERROR = "ERROR: unable to download video data: HTTP Error 403: Forbidden"


def _service(tmp_path, monkeypatch, stderr: str) -> PodcastDownloadService:
    """Return a service whose every yt-dlp run fails with ``stderr``."""
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(f"{VIDEO_URL}\n", encoding="utf-8")
    service = PodcastDownloadService(
        urls_file=urls_file,
        downloads_dir=tmp_path / "downloads",
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
        max_download_attempts=2,
    )

    def fake_run(command: list[str], *args, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr=stderr)

    monkeypatch.setattr(downloads_service_module.subprocess, "run", fake_run)
    return service


def _attempt_direct(service: PodcastDownloadService) -> None:
    service._download_video(VIDEO_URL, index=1, total=1, use_archive=False)


def test_direct_video_leaves_the_queue_after_two_dead_video_failures(
    tmp_path, monkeypatch
) -> None:
    service = _service(tmp_path, monkeypatch, DEAD_VIDEO_ERROR)

    _attempt_direct(service)
    assert service.queue_store.read_urls() == [VIDEO_URL]

    _attempt_direct(service)
    assert service.queue_store.read_urls() == []
    # Forgetting the count gives a re-added URL a fresh set of attempts.
    assert service.failed_download_store.load() == {}
    activity = (tmp_path / "activity.log").read_text(encoding="utf-8")
    assert "removed from the queue after 2 failed attempts" in activity


def test_youtube_block_never_counts_toward_dropping(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch, BLOCKED_ERROR)

    for _ in range(3):
        _attempt_direct(service)

    assert service.queue_store.read_urls() == [VIDEO_URL]
    assert service.failed_download_store.load() == {}


def test_dropped_channel_video_is_skipped_on_later_runs(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch, DEAD_VIDEO_ERROR)
    channel_target = DownloadTarget(
        video_url=VIDEO_URL, output_dir=tmp_path / "downloads", use_archive=True
    )

    assert service._download_targets([channel_target]) == (0, 1)
    assert service._download_targets([channel_target]) == (0, 1)
    assert service.failed_download_store.load() == {VIDEO_URL: 2}

    # The third listing offers the video again; it is skipped, not attempted.
    assert service._download_targets([channel_target]) == (0, 0)
