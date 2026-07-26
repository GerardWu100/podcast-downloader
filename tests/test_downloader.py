"""Regression tests for downloader success detection."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import src.downloads.service as downloads_service_module
from src.downloads.audio_metadata import AudioMetadataWriter
from src.downloads.service import PodcastDownloadService as PodcastDownloader


def write_fake_ffmpeg_output(command: list[str], audio_text: str) -> None:
    """Write the temp audio path used by the downloader's ffmpeg metadata pass."""
    temp_audio_file = Path(command[-1])
    temp_audio_file.write_text(audio_text, encoding="utf-8")


def disable_youtube_channel_display_name_lookup(monkeypatch) -> None:
    """Keep legacy downloader tests from issuing extra yt-dlp metadata lookups."""
    monkeypatch.setattr(
        downloads_service_module,
        "get_youtube_channel_display_name",
        lambda *args, **kwargs: None,
    )


def ffmpeg_command_from(commands: list[list[str]]) -> list[str]:
    """Return the ffmpeg command captured by a downloader subprocess monkeypatch."""
    return next(command for command in commands if command[0] == "ffmpeg")


def test_download_video_treats_overwritten_mp3_as_success(
    tmp_path,
    monkeypatch,
) -> None:
    """A successful download can update an existing MP3 without increasing file count."""
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text("https://www.youtube.com/watch?v=abc123\n", encoding="utf-8")
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    existing_mp3 = downloads_dir / "singles" / "channel - episode.mp3"
    existing_mp3.parent.mkdir()
    existing_mp3.write_text("old audio", encoding="utf-8")
    original_mtime_ns = existing_mp3.stat().st_mtime_ns

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
    )

    def fake_run(
        command: list[str], *args, **kwargs
    ) -> subprocess.CompletedProcess[str]:
        if command[0] == "ffmpeg":
            write_fake_ffmpeg_output(command, "new audio with date tag")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        existing_mp3.write_text("new audio", encoding="utf-8")
        os.utime(
            existing_mp3,
            ns=(original_mtime_ns + 5_000_000, original_mtime_ns + 5_000_000),
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(downloads_service_module.subprocess, "run", fake_run)

    _, success = downloader._download_video(
        "https://www.youtube.com/watch?v=abc123",
        index=1,
        total=1,
        use_archive=False,
    )

    assert success is True


def test_write_audio_download_date_metadata_updates_mp3_date_tag(
    tmp_path,
) -> None:
    """The ffmpeg copy pass should overwrite the embedded MP3 date tag."""
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise AssertionError("ffmpeg and ffprobe are required for MP3 metadata tests")

    urls_file = tmp_path / "urls.txt"
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    audio_file = downloads_dir / "episode.mp3"

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
    )

    create_result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono",
            "-t",
            "0.1",
            "-codec:a",
            "libmp3lame",
            str(audio_file),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert create_result.returncode == 0, create_result.stderr
    original_inode = audio_file.stat().st_ino

    downloader._write_audio_download_date_metadata(
        audio_file,
        "2026-04-30T12:34:56-04:00",
        "https://videos.example.com/watch/episode-1",
    )

    probe_result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format_tags=date",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_file),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert probe_result.returncode == 0, probe_result.stderr
    assert probe_result.stdout.strip() == "2026-04-30T12:34:56-04:00"
    assert audio_file.stat().st_ino == original_inode


def test_write_audio_download_date_metadata_avoids_scannable_temp_mp3(
    tmp_path,
    monkeypatch,
) -> None:
    """The metadata pass must not expose a second MP3 to library scanners."""
    urls_file = tmp_path / "urls.txt"
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    audio_file = downloads_dir / "episode.mp3"
    audio_file.write_text("audio before metadata", encoding="utf-8")

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
    )

    def fake_run(
        command: list[str],
        *args,
        **kwargs,
    ) -> subprocess.CompletedProcess[str]:
        output_file = Path(command[-1])
        output_file.write_text("audio after metadata", encoding="utf-8")

        scanned_mp3_names = sorted(path.name for path in downloads_dir.glob("*.mp3"))
        assert scanned_mp3_names == ["episode.mp3"]

        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(downloads_service_module.subprocess, "run", fake_run)

    downloader._write_audio_download_date_metadata(
        audio_file,
        "2026-04-30T12:34:56-04:00",
        "https://videos.example.com/watch/episode-1",
    )

    assert audio_file.read_text(encoding="utf-8") == "audio after metadata"


def test_write_download_metadata_tolerates_non_utf8_ffmpeg_stderr(
    tmp_path,
) -> None:
    """ffmpeg stderr can echo ID3 bytes that are not valid UTF-8."""
    audio_file = tmp_path / "episode.mp3"
    audio_file.write_bytes(b"audio")

    captured_kwargs: dict[str, object] = {}

    def fake_run(
        command: list[str],
        **kwargs,
    ) -> subprocess.CompletedProcess[str]:
        captured_kwargs.update(kwargs)
        temp_audio_file = Path(command[-1])
        temp_audio_file.write_bytes(b"audio after metadata")
        invalid_utf8_stderr = b"metadata dump: \xff\xfe invalid bytes"
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="",
            stderr=invalid_utf8_stderr.decode("utf-8", errors="replace"),
        )

    writer = AudioMetadataWriter(run_command=fake_run)
    writer.write_download_metadata(
        audio_file,
        "2026-04-30T12:34:56-04:00",
        "https://www.youtube.com/watch?v=abc123",
    )

    assert captured_kwargs["encoding"] == "utf-8"
    assert captured_kwargs["errors"] == "replace"
    assert audio_file.read_bytes() == b"audio after metadata"


def test_ytdlp_command_disables_source_mtime(
    tmp_path,
    monkeypatch,
) -> None:
    """yt-dlp should not preserve source/release timestamps on output files."""
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(
        "https://videos.example.com/watch/episode-1\n", encoding="utf-8"
    )
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    output_mp3 = downloads_dir / "singles" / "creator - episode.mp3"
    output_mp3.parent.mkdir()
    commands: list[list[str]] = []

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
    )

    def fake_run(
        command: list[str],
        *args,
        **kwargs,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command[0] == "ffmpeg":
            write_fake_ffmpeg_output(command, "audio with date tag")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        output_mp3.write_text("audio", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(downloads_service_module.subprocess, "run", fake_run)

    result, changed = downloader._run_ytdlp(
        "https://videos.example.com/watch/episode-1",
        cookies_file=None,
    )

    assert result.returncode == 0
    assert changed == [output_mp3]
    assert "--no-mtime" in commands[0]


def test_finished_mp3_is_published_from_intermediate_dir_to_library_dir(
    tmp_path,
    monkeypatch,
) -> None:
    """Scratch downloads should be fully removed after publish."""
    video_url = "https://videos.example.com/watch/episode-1"
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(f"{video_url}\n", encoding="utf-8")
    downloads_dir = tmp_path / "downloads"
    intermediate_dir = tmp_path / "download_work"
    work_mp3 = intermediate_dir / "singles" / "creator - episode.mp3"
    library_mp3 = downloads_dir / "singles" / "creator - episode.mp3"

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        intermediate_dir=intermediate_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
    )

    def fake_run_ytdlp(
        self: PodcastDownloader,
        url: str,
        cookies_file: Path | None,
        work_dir: Path | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], list[Path]]:
        target_dir = work_dir or intermediate_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        work_mp3.parent.mkdir(parents=True, exist_ok=True)
        work_mp3.write_text("audio", encoding="utf-8")
        (target_dir / "cover.webp").write_text("thumb", encoding="utf-8")
        return subprocess.CompletedProcess(["yt-dlp"], 0, stdout="", stderr=""), [
            work_mp3
        ]

    monkeypatch.setattr(PodcastDownloader, "_run_ytdlp", fake_run_ytdlp)
    monkeypatch.setattr(
        PodcastDownloader,
        "_stamp_audio_files_with_download_time",
        lambda *args, **kwargs: None,
    )

    _, success = downloader._download_video(
        video_url,
        index=1,
        total=1,
        use_archive=False,
    )

    assert success is True
    assert library_mp3.is_file()
    assert not work_mp3.exists()
    assert not work_mp3.parent.exists()
    assert not (intermediate_dir / "singles" / "cover.webp").exists()


def test_ytdlp_uses_work_dir_for_temp_path(tmp_path, monkeypatch) -> None:
    """yt-dlp temp files should stay inside the per-download work folder."""
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(
        "https://videos.example.com/watch/episode-1\n", encoding="utf-8"
    )
    downloads_dir = tmp_path / "downloads"
    intermediate_dir = tmp_path / "download_work"
    commands: list[list[str]] = []

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        intermediate_dir=intermediate_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
    )
    work_dir = intermediate_dir / "singles"

    def fake_run(
        command: list[str],
        *args,
        **kwargs,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        output_mp3 = work_dir / "creator - episode.mp3"
        output_mp3.parent.mkdir(parents=True, exist_ok=True)
        output_mp3.write_text("audio", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(downloads_service_module.subprocess, "run", fake_run)

    downloader._run_ytdlp(
        "https://videos.example.com/watch/episode-1",
        cookies_file=None,
        work_dir=work_dir,
    )

    assert commands
    temp_path_argument = next(
        argument for argument in commands[0] if argument.startswith("temp:")
    )
    assert temp_path_argument == f"temp:{work_dir}"


def test_failed_download_removes_intermediate_work_dir(
    tmp_path,
    monkeypatch,
) -> None:
    """Failed downloads should not leave scratch folders behind."""
    video_url = "https://videos.example.com/watch/episode-1"
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(f"{video_url}\n", encoding="utf-8")
    downloads_dir = tmp_path / "downloads"
    intermediate_dir = tmp_path / "download_work"
    work_dir = intermediate_dir / "singles"

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        intermediate_dir=intermediate_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
    )

    def fake_run_ytdlp(
        self: PodcastDownloader,
        url: str,
        cookies_file: Path | None,
        work_dir: Path | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], list[Path]]:
        target_dir = work_dir or intermediate_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "partial.part").write_text("partial", encoding="utf-8")
        (target_dir / "cover.webp").write_text("thumb", encoding="utf-8")
        return subprocess.CompletedProcess(["yt-dlp"], 1, stdout="", stderr="fail"), []

    monkeypatch.setattr(PodcastDownloader, "_run_ytdlp", fake_run_ytdlp)

    _, success = downloader._download_video(
        video_url,
        index=1,
        total=1,
        use_archive=False,
    )

    assert success is False
    assert not work_dir.exists()


def test_metadata_stamp_failure_preserves_mp3_but_removes_artifacts(
    tmp_path,
    monkeypatch,
) -> None:
    """A retryable stamp failure should keep the MP3 and drop other scratch files."""
    video_url = "https://videos.example.com/watch/episode-1"
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(f"{video_url}\n", encoding="utf-8")
    downloads_dir = tmp_path / "downloads"
    intermediate_dir = tmp_path / "download_work"
    work_mp3 = intermediate_dir / "singles" / "creator - episode.mp3"

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        intermediate_dir=intermediate_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
    )

    def fake_run_ytdlp(
        self: PodcastDownloader,
        url: str,
        cookies_file: Path | None,
        work_dir: Path | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], list[Path]]:
        target_dir = work_dir or intermediate_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        work_mp3.parent.mkdir(parents=True, exist_ok=True)
        work_mp3.write_text("audio", encoding="utf-8")
        (target_dir / "cover.webp").write_text("thumb", encoding="utf-8")
        return subprocess.CompletedProcess(["yt-dlp"], 0, stdout="", stderr=""), [
            work_mp3
        ]

    def fail_stamp(*args, **kwargs) -> None:
        raise RuntimeError("ffmpeg failed")

    monkeypatch.setattr(PodcastDownloader, "_run_ytdlp", fake_run_ytdlp)
    monkeypatch.setattr(
        PodcastDownloader,
        "_stamp_audio_files_with_download_time",
        fail_stamp,
    )

    _, success = downloader._download_video(
        video_url,
        index=1,
        total=1,
        use_archive=False,
    )

    assert success is False
    assert work_mp3.is_file()
    assert work_mp3.parent.is_dir()
    assert not (work_mp3.parent / "cover.webp").exists()


def test_publish_failure_still_cleans_intermediate_work_dir(
    tmp_path,
    monkeypatch,
) -> None:
    """Publish errors should still remove leftover scratch files."""
    video_url = "https://videos.example.com/watch/episode-1"
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(f"{video_url}\n", encoding="utf-8")
    downloads_dir = tmp_path / "downloads"
    intermediate_dir = tmp_path / "download_work"
    work_mp3 = intermediate_dir / "singles" / "creator - episode.mp3"
    work_dir = work_mp3.parent

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        intermediate_dir=intermediate_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
    )

    def fake_run_ytdlp(
        self: PodcastDownloader,
        url: str,
        cookies_file: Path | None,
        work_dir: Path | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], list[Path]]:
        target_dir = work_dir or intermediate_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        work_mp3.write_text("audio", encoding="utf-8")
        (target_dir / "cover.webp").write_text("thumb", encoding="utf-8")
        return subprocess.CompletedProcess(["yt-dlp"], 0, stdout="", stderr=""), [
            work_mp3
        ]

    def fail_publish(*args, **kwargs) -> list[Path]:
        raise OSError("move failed")

    monkeypatch.setattr(PodcastDownloader, "_run_ytdlp", fake_run_ytdlp)
    monkeypatch.setattr(
        PodcastDownloader,
        "_stamp_audio_files_with_download_time",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        PodcastDownloader,
        "_publish_audio_files_to_output_dir",
        fail_publish,
    )

    _, success = downloader._download_video(
        video_url,
        index=1,
        total=1,
        use_archive=False,
    )

    assert success is False
    assert not work_dir.exists()


def test_intermediate_root_temp_files_are_removed(tmp_path) -> None:
    """Legacy yt-dlp temp files at the intermediate root should be swept."""
    downloads_dir = tmp_path / "downloads"
    intermediate_dir = tmp_path / "download_work"
    intermediate_dir.mkdir()
    stale_part = intermediate_dir / "video-id.f140.mp4.part"
    stale_part.write_text("partial", encoding="utf-8")
    work_dir = intermediate_dir / "singles"
    work_dir.mkdir()
    preserved_mp3 = work_dir / "creator - episode.mp3"
    preserved_mp3.write_text("audio", encoding="utf-8")

    downloader = PodcastDownloader(
        urls_file=tmp_path / "urls.txt",
        downloads_dir=downloads_dir,
        intermediate_dir=intermediate_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
    )

    downloader._finalize_intermediate_cleanup(
        work_dir,
        preserve_mp3_files=[preserved_mp3],
    )

    assert preserved_mp3.is_file()
    assert not stale_part.exists()


def test_youtube_download_does_not_use_cookie_file_when_plain_attempt_succeeds(
    tmp_path,
    monkeypatch,
) -> None:
    """A working normal YouTube request should not spend the cookie file."""
    video_url = "https://www.youtube.com/watch?v=abc123"
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(f"{video_url}\n", encoding="utf-8")
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    cookies_file = tmp_path / "cookies.txt"
    cookies_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    output_mp3 = downloads_dir / "singles" / "creator - episode.mp3"
    cookie_attempts: list[Path | None] = []

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
        cookies_file=cookies_file,
    )

    def fake_run_ytdlp(
        self: PodcastDownloader,
        url: str,
        cookies_file: Path | None,
        output_dir: Path | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], list[Path]]:
        cookie_attempts.append(cookies_file)
        target_dir = output_dir or downloads_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        output_mp3.write_text("audio", encoding="utf-8")
        return subprocess.CompletedProcess(["yt-dlp"], 0, stdout="", stderr=""), [
            output_mp3
        ]

    monkeypatch.setattr(PodcastDownloader, "_run_ytdlp", fake_run_ytdlp)
    monkeypatch.setattr(
        PodcastDownloader,
        "_stamp_audio_files_with_download_time",
        lambda *args, **kwargs: None,
    )

    _, success = downloader._download_video(
        video_url,
        index=1,
        total=1,
        use_archive=False,
    )

    assert success is True
    assert cookie_attempts == [None]


def test_youtube_download_uses_cookies_on_first_attempt_when_always_use_cookies(
    tmp_path,
    monkeypatch,
) -> None:
    """Always-on cookie mode should skip the plain unauthenticated attempt."""
    video_url = "https://www.youtube.com/watch?v=abc123"
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(f"{video_url}\n", encoding="utf-8")
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    cookies_file = tmp_path / "cookies.txt"
    cookies_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    output_mp3 = downloads_dir / "singles" / "creator - episode.mp3"
    cookie_attempts: list[Path | None] = []

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
        cookies_file=cookies_file,
        always_use_cookies=True,
    )

    def fake_run_ytdlp(
        self: PodcastDownloader,
        url: str,
        cookies_file: Path | None,
        output_dir: Path | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], list[Path]]:
        cookie_attempts.append(cookies_file)
        target_dir = output_dir or downloads_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        output_mp3.write_text("audio", encoding="utf-8")
        return subprocess.CompletedProcess(["yt-dlp"], 0, stdout="", stderr=""), [
            output_mp3
        ]

    monkeypatch.setattr(PodcastDownloader, "_run_ytdlp", fake_run_ytdlp)
    monkeypatch.setattr(
        PodcastDownloader,
        "_stamp_audio_files_with_download_time",
        lambda *args, **kwargs: None,
    )

    _, success = downloader._download_video(
        video_url,
        index=1,
        total=1,
        use_archive=False,
    )

    assert success is True
    assert cookie_attempts == [cookies_file]


def test_non_youtube_download_does_not_retry_with_youtube_cookie_file(
    tmp_path,
    monkeypatch,
) -> None:
    """The cookie fallback is a YouTube-specific escape hatch."""
    video_url = "https://videos.example.com/watch/missing-episode"
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(f"{video_url}\n", encoding="utf-8")
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    cookies_file = tmp_path / "cookies.txt"
    cookies_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    cookie_attempts: list[Path | None] = []

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
        cookies_file=cookies_file,
    )

    def fake_run_ytdlp(
        self: PodcastDownloader,
        url: str,
        cookies_file: Path | None,
        output_dir: Path | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], list[Path]]:
        cookie_attempts.append(cookies_file)
        return (
            subprocess.CompletedProcess(["yt-dlp"], 1, stdout="", stderr="missing"),
            [],
        )

    monkeypatch.setattr(PodcastDownloader, "_run_ytdlp", fake_run_ytdlp)

    _, success = downloader._download_video(
        video_url,
        index=1,
        total=1,
        use_archive=False,
    )

    assert success is False
    assert cookie_attempts == [None]
    assert urls_file.read_text(encoding="utf-8") == f"{video_url}\n"


def test_download_video_writes_mp3_date_metadata_to_download_time(
    tmp_path,
    monkeypatch,
) -> None:
    """Changed MP3 files should receive an embedded ID3 date for Audiobookshelf."""
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(
        "https://videos.example.com/watch/episode-1\n", encoding="utf-8"
    )
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    output_mp3 = downloads_dir / "singles" / "creator - episode.mp3"
    output_mp3.parent.mkdir()
    download_timestamp = 1_800_000_000.25
    commands: list[list[str]] = []

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
    )

    def fake_run(
        command: list[str],
        *args,
        **kwargs,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command[0] == "yt-dlp":
            output_mp3.write_text("audio", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        write_fake_ffmpeg_output(command, "audio with date tag")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(downloads_service_module.subprocess, "run", fake_run)
    monkeypatch.setattr(
        downloads_service_module.time, "time", lambda: download_timestamp
    )

    _, success = downloader._download_video(
        "https://videos.example.com/watch/episode-1",
        index=1,
        total=1,
        use_archive=False,
    )

    ffmpeg_command = commands[1]

    assert success is True
    assert ffmpeg_command[:4] == ["ffmpeg", "-y", "-i", str(output_mp3)]
    assert "-codec" in ffmpeg_command
    assert "copy" in ffmpeg_command
    assert "-id3v2_version" in ffmpeg_command
    assert "4" in ffmpeg_command
    assert "-metadata" in ffmpeg_command
    assert "date=2027-01-15T03:00:00.250000-05:00" in ffmpeg_command
    assert "comment=https://videos.example.com/watch/episode-1" in ffmpeg_command
    assert "-f" in ffmpeg_command
    assert "mp3" in ffmpeg_command
    assert Path(ffmpeg_command[-1]).suffix != ".mp3"
    assert Path(ffmpeg_command[-1]).parent == output_mp3.parent
    assert output_mp3.read_text(encoding="utf-8") == "audio with date tag"


def test_download_video_writes_normalized_youtube_url_to_mp3_comment_metadata(
    tmp_path,
    monkeypatch,
) -> None:
    """YouTube URL metadata should use the canonical stripped watch URL."""
    disable_youtube_channel_display_name_lookup(monkeypatch)
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text("https://youtu.be/abc123\n", encoding="utf-8")
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    output_mp3 = downloads_dir / "singles" / "creator - episode.mp3"
    output_mp3.parent.mkdir()
    commands: list[list[str]] = []

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
    )

    def fake_run(
        command: list[str],
        *args,
        **kwargs,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command[0] == "yt-dlp":
            output_mp3.write_text("audio", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        write_fake_ffmpeg_output(command, "audio with date and source URL tags")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(downloads_service_module.subprocess, "run", fake_run)

    _, success = downloader._download_video(
        "https://youtu.be/abc123?si=tracking",
        index=1,
        total=1,
        use_archive=False,
    )

    ffmpeg_command = ffmpeg_command_from(commands)

    assert success is True
    assert "comment=https://www.youtube.com/watch?v=abc123" in ffmpeg_command


def test_live_url_writes_watch_url_to_mp3_comment_metadata(
    tmp_path,
    monkeypatch,
) -> None:
    """Live URLs should share one canonical watch URL in queue and MP3 metadata."""
    disable_youtube_channel_display_name_lookup(monkeypatch)
    live_url = "https://www.youtube.com/live/abc123"
    watch_url = "https://www.youtube.com/watch?v=abc123"
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(f"{live_url}\n", encoding="utf-8")
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    output_mp3 = downloads_dir / "singles" / "creator - episode.mp3"
    output_mp3.parent.mkdir()
    commands: list[list[str]] = []

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
    )

    def fake_run(
        command: list[str],
        *args,
        **kwargs,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command[0] == "yt-dlp":
            output_mp3.write_text("audio", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        write_fake_ffmpeg_output(command, "audio with date and source URL tags")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(downloads_service_module.subprocess, "run", fake_run)

    _, success = downloader._download_video(
        live_url,
        index=1,
        total=1,
        use_archive=False,
    )

    ffmpeg_command = ffmpeg_command_from(commands)

    assert success is True
    assert f"comment={watch_url}" in ffmpeg_command
    assert urls_file.read_text(encoding="utf-8") == ""


def test_stamp_audio_files_updates_metadata_without_restamping_filesystem_times(
    tmp_path,
    monkeypatch,
) -> None:
    """The ABS-visible date comes from MP3 metadata, not a separate mtime pass."""
    urls_file = tmp_path / "urls.txt"
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    output_mp3 = downloads_dir / "creator - episode.mp3"
    output_mp3.write_text("audio", encoding="utf-8")
    metadata_values: list[str] = []

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
    )

    def fake_metadata_write(
        audio_file: Path,
        download_date_metadata: str,
        source_url_metadata: str,
        channel_display_name: str | None = None,
    ) -> None:
        assert audio_file == output_mp3
        metadata_values.append(download_date_metadata)
        assert source_url_metadata == "https://videos.example.com/watch/episode-1"

    def fail_if_filesystem_timestamp_is_restamped(*args, **kwargs) -> None:
        raise AssertionError("filesystem timestamp restamping is not needed for ABS")

    monkeypatch.setattr(
        downloader.audio_metadata_writer,
        "write_download_metadata",
        fake_metadata_write,
    )
    monkeypatch.setattr(downloads_service_module.time, "time", lambda: 1_800_000_000.25)

    downloader._stamp_audio_files_with_download_time(
        [output_mp3],
        "https://videos.example.com/watch/episode-1",
    )

    assert metadata_values == ["2027-01-15T03:00:00.250000-05:00"]


def test_stamp_audio_files_writes_channel_name_to_mp3_artist(
    tmp_path,
    monkeypatch,
) -> None:
    """YouTube downloads should stamp a readable channel name into artist/album tags."""
    output_mp3 = tmp_path / "downloads" / "creator - episode.mp3"
    output_mp3.parent.mkdir()
    output_mp3.write_text("audio", encoding="utf-8")
    captured_commands: list[list[str]] = []

    downloader = PodcastDownloader(
        urls_file=tmp_path / "urls.txt",
        downloads_dir=tmp_path / "downloads",
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
    )

    def fake_run(
        command: list[str],
        *args,
        **kwargs,
    ) -> subprocess.CompletedProcess[str]:
        captured_commands.append(command)
        write_fake_ffmpeg_output(command, "audio with channel tags")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(downloads_service_module.subprocess, "run", fake_run)
    monkeypatch.setattr(
        downloads_service_module,
        "get_youtube_channel_display_name",
        lambda *args, **kwargs: "The Compound",
    )

    downloader._stamp_audio_files_with_download_time(
        [output_mp3],
        "https://www.youtube.com/watch?v=LgmzAXMBbu4",
    )

    ffmpeg_command = captured_commands[0]
    assert "artist=The Compound" in ffmpeg_command
    assert "album=The Compound" in ffmpeg_command


def test_source_folder_name_resolves_opaque_youtube_channel_id(
    tmp_path,
    monkeypatch,
) -> None:
    """Channel URLs with ``/channel/UC...`` should not create opaque folder names."""
    opaque_channel_url = (
        "https://www.youtube.com/channel/UCBRpqrzuuqE8TZcWw75JSdw/videos"
    )
    downloader = PodcastDownloader(
        urls_file=tmp_path / "urls.txt",
        downloads_dir=tmp_path / "downloads",
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
    )

    monkeypatch.setattr(
        downloads_service_module,
        "get_youtube_channel_folder_name",
        lambda *args, **kwargs: "TheCompoundNews",
    )

    folder_name = downloader._source_folder_name(opaque_channel_url)

    assert folder_name == "TheCompoundNews"


def test_source_folder_name_uses_youtube_playlist_title(
    tmp_path,
    monkeypatch,
) -> None:
    """Playlist URLs should prefer readable playlist titles over opaque IDs."""
    playlist_url = (
        "https://www.youtube.com/playlist?list=PLZgCX3KJ3XGAq-6Ewy4ClI88EIYDxJsaS"
    )
    downloader = PodcastDownloader(
        urls_file=tmp_path / "urls.txt",
        downloads_dir=tmp_path / "downloads",
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
    )

    monkeypatch.setattr(
        downloads_service_module,
        "get_youtube_playlist_folder_name",
        lambda *args, **kwargs: "Top Traders Unplugged",
        raising=False,
    )

    folder_name = downloader._source_folder_name(playlist_url)

    assert folder_name == "Top-Traders-Unplugged"


def test_ytdlp_command_prefers_channel_name_in_output_template(
    tmp_path,
    monkeypatch,
) -> None:
    """Filenames should prefer the YouTube channel field over opaque uploader IDs."""
    urls_file = tmp_path / "urls.txt"
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    commands: list[list[str]] = []

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
    )

    def fake_run(
        command: list[str],
        *args,
        **kwargs,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(downloads_service_module.subprocess, "run", fake_run)

    downloader._run_ytdlp(
        "https://www.youtube.com/watch?v=abc123",
        cookies_file=None,
    )

    output_template = commands[0][commands[0].index("--output") + 1]
    assert "%(channel,uploader)s" in output_template
    assert "[%(id)s]" in output_template


def test_download_video_reports_failure_when_mp3_date_metadata_fails(
    tmp_path,
    monkeypatch,
) -> None:
    """A metadata write failure should leave the URL queued for retry."""
    video_url = "https://videos.example.com/watch/episode-1"
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(f"{video_url}\n", encoding="utf-8")
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    output_mp3 = downloads_dir / "singles" / "creator - episode.mp3"
    output_mp3.parent.mkdir()

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
    )

    def fake_run(
        command: list[str],
        *args,
        **kwargs,
    ) -> subprocess.CompletedProcess[str]:
        if command[0] == "yt-dlp":
            output_mp3.write_text("audio", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="metadata write failed",
        )

    monkeypatch.setattr(downloads_service_module.subprocess, "run", fake_run)

    _, success = downloader._download_video(
        video_url,
        index=1,
        total=1,
        use_archive=False,
    )

    assert success is False
    assert output_mp3.exists()
    assert urls_file.read_text(encoding="utf-8") == f"{video_url}\n"


def test_download_video_can_retry_after_metadata_stamp_failure_using_existing_mp3(
    tmp_path,
    monkeypatch,
) -> None:
    """A failed metadata stamp should not make the existing MP3 unrecoverable."""
    video_url = "https://videos.example.com/watch/episode-1"
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(f"{video_url}\n", encoding="utf-8")
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    output_mp3 = downloads_dir / "singles" / "creator - episode.mp3"
    output_mp3.parent.mkdir()

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
    )

    command_counts = {"yt-dlp": 0, "ffmpeg": 0}

    def fake_run(
        command: list[str],
        *args,
        **kwargs,
    ) -> subprocess.CompletedProcess[str]:
        if command[0] == "yt-dlp":
            command_counts["yt-dlp"] += 1
            if command_counts["yt-dlp"] == 1:
                output_mp3.write_text("audio", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        command_counts["ffmpeg"] += 1
        if command_counts["ffmpeg"] == 1:
            return subprocess.CompletedProcess(
                command,
                1,
                stdout="",
                stderr="metadata write failed",
            )

        write_fake_ffmpeg_output(command, "audio with date tag")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(downloads_service_module.subprocess, "run", fake_run)

    _, first_success = downloader._download_video(
        video_url,
        index=1,
        total=1,
        use_archive=False,
    )
    _, second_success = downloader._download_video(
        video_url,
        index=1,
        total=1,
        use_archive=False,
    )

    assert first_success is False
    assert second_success is True
    assert urls_file.read_text(encoding="utf-8") == ""


def test_download_video_reports_failure_when_no_mp3_changes(
    tmp_path,
    monkeypatch,
) -> None:
    """A zero-delta run should still be treated as a failure even with exit code 0."""
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text("https://www.youtube.com/watch?v=abc123\n", encoding="utf-8")
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
    )

    def fake_run(*args, **kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="")

    monkeypatch.setattr(downloads_service_module.subprocess, "run", fake_run)

    _, success = downloader._download_video(
        "https://www.youtube.com/watch?v=abc123",
        index=1,
        total=1,
        use_archive=False,
    )

    assert success is False


def test_zero_delta_recovery_ignores_mp3_from_another_source(
    tmp_path,
    monkeypatch,
) -> None:
    """Recovery must not stamp an unrelated MP3 from another work folder."""
    video_url = "https://videos.example.com/watch/episode-2"
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(f"{video_url}\n", encoding="utf-8")
    downloads_dir = tmp_path / "downloads"
    intermediate_dir = tmp_path / "download_work"
    unrelated_mp3 = intermediate_dir / "another-source" / "episode-1.mp3"
    unrelated_mp3.parent.mkdir(parents=True)
    unrelated_mp3.write_text("unrelated audio", encoding="utf-8")

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        intermediate_dir=intermediate_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
    )

    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        *args,
        **kwargs,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(downloads_service_module.subprocess, "run", fake_run)

    _, success = downloader._download_video(
        video_url,
        index=1,
        total=1,
        use_archive=False,
    )

    assert success is False
    assert all(command[0] != "ffmpeg" for command in commands)
    assert unrelated_mp3.read_text(encoding="utf-8") == "unrelated audio"
    assert urls_file.read_text(encoding="utf-8") == f"{video_url}\n"


def test_download_video_removes_direct_short_from_queue_when_skipped(
    tmp_path,
) -> None:
    """A direct Shorts URL should be discarded once the downloader skips it."""
    short_url = "https://www.youtube.com/shorts/abc123"
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(f"{short_url}\n", encoding="utf-8")
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
    )

    _, success = downloader._download_video(
        short_url,
        index=1,
        total=1,
        use_archive=False,
    )

    assert success is True
    assert urls_file.read_text(encoding="utf-8") == ""


def test_non_youtube_download_does_not_use_sponsorblock(
    tmp_path,
    monkeypatch,
) -> None:
    """SponsorBlock flags are YouTube-specific and should be skipped elsewhere."""
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(
        "https://videos.example.com/watch/episode-1\n", encoding="utf-8"
    )
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    output_mp3 = downloads_dir / "singles" / "creator - episode.mp3"
    output_mp3.parent.mkdir()
    commands: list[list[str]] = []

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
    )

    def fake_run(
        command: list[str],
        *args,
        **kwargs,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command[0] == "ffmpeg":
            write_fake_ffmpeg_output(command, "audio with date tag")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        output_mp3.write_text("audio", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(downloads_service_module.subprocess, "run", fake_run)

    _, success = downloader._download_video(
        "https://videos.example.com/watch/episode-1",
        index=1,
        total=1,
        use_archive=False,
    )

    assert success is True
    assert "--sponsorblock-remove" not in commands[0]


def test_non_youtube_download_failure_is_logged_and_left_in_queue(
    tmp_path,
    monkeypatch,
) -> None:
    """Failed non-YouTube downloads should be logged without deleting the URL."""
    non_youtube_url = "https://videos.example.com/watch/missing-episode"
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(f"{non_youtube_url}\n", encoding="utf-8")
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    log_file = tmp_path / "download.log"

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        log_file=log_file,
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
    )

    def fake_run(
        command: list[str],
        *args,
        **kwargs,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="unsupported URL",
        )

    monkeypatch.setattr(downloads_service_module.subprocess, "run", fake_run)

    _, success = downloader._download_video(
        non_youtube_url,
        index=1,
        total=1,
        use_archive=False,
    )

    assert success is False
    assert urls_file.read_text(encoding="utf-8") == f"{non_youtube_url}\n"
    assert f"Failed: {non_youtube_url}" in log_file.read_text(encoding="utf-8")


def test_second_downloader_instance_reloads_archived_state_before_download(
    tmp_path,
    monkeypatch,
) -> None:
    """A second downloader object should not redownload an archived expanded URL."""
    disable_youtube_channel_display_name_lookup(monkeypatch)
    video_url = "https://www.youtube.com/watch?v=abc123"
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(f"{video_url}\n", encoding="utf-8")
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    output_mp3 = downloads_dir / "singles" / "creator - episode.mp3"
    output_mp3.parent.mkdir()
    archive_file = tmp_path / "downloaded_urls.txt"

    downloader_one = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        log_file=tmp_path / "download-one.log",
        downloaded_urls_file=archive_file,
    )
    downloader_two = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        log_file=tmp_path / "download-two.log",
        downloaded_urls_file=archive_file,
    )

    yt_dlp_calls = 0

    def fake_run(
        command: list[str],
        *args,
        **kwargs,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal yt_dlp_calls
        if command[0] == "yt-dlp":
            yt_dlp_calls += 1
            output_mp3.write_text("audio", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        write_fake_ffmpeg_output(command, "audio with date tag")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(downloads_service_module.subprocess, "run", fake_run)

    first_result = downloader_one._download_video(
        video_url,
        index=1,
        total=1,
        use_archive=True,
    )

    assert (
        archive_file.read_text(encoding="utf-8")
        == "https://www.youtube.com/watch?v=abc123\n"
    )
    assert downloader_two.downloaded_urls == {"https://www.youtube.com/watch?v=abc123"}

    second_result = downloader_two._download_video(
        video_url,
        index=1,
        total=1,
        use_archive=True,
    )

    assert first_result[1] is True
    assert second_result[1] is True
    assert yt_dlp_calls == 1


def test_concurrent_archive_backed_downloads_do_not_duplicate_work(
    tmp_path,
    monkeypatch,
) -> None:
    """Two downloader objects should not download the same expanded URL at once."""
    video_url = "https://www.youtube.com/watch?v=abc123"
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(f"{video_url}\n", encoding="utf-8")
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    archive_file = tmp_path / "downloaded_urls.txt"
    yt_dlp_calls: list[str] = []
    errors: list[BaseException] = []

    def fake_run_ytdlp(
        self: PodcastDownloader,
        url: str,
        cookies_file: Path | None,
        output_dir: Path | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], list[Path]]:
        """Simulate a slow download so a concurrent duplicate has time to start."""
        threading.Event().wait(timeout=0.1)
        target_dir = output_dir or downloads_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        output_mp3 = target_dir / f"creator - episode-{len(yt_dlp_calls)}.mp3"
        output_mp3.write_text("audio", encoding="utf-8")
        yt_dlp_calls.append(url)
        return subprocess.CompletedProcess(["yt-dlp"], 0, stdout="", stderr=""), [
            output_mp3
        ]

    def run_one(name: str) -> None:
        try:
            downloader = PodcastDownloader(
                urls_file=urls_file,
                downloads_dir=downloads_dir,
                log_file=tmp_path / f"download-{name}.log",
                downloaded_urls_file=archive_file,
            )
            downloader._download_video(video_url, index=1, total=1, use_archive=True)
        except BaseException as exc:
            errors.append(exc)

    monkeypatch.setattr(PodcastDownloader, "_run_ytdlp", fake_run_ytdlp)
    monkeypatch.setattr(
        PodcastDownloader,
        "_stamp_audio_files_with_download_time",
        lambda *args, **kwargs: None,
    )

    threads = [
        threading.Thread(target=run_one, args=("one",)),
        threading.Thread(target=run_one, args=("two",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    assert yt_dlp_calls == [video_url]
    assert archive_file.read_text(encoding="utf-8") == f"{video_url}\n"


def test_download_video_writes_concise_failure_activity_event(
    tmp_path,
    monkeypatch,
) -> None:
    """The browser activity feed should get concise failure entries."""
    failed_url = "https://videos.example.com/watch/missing-episode"
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(f"{failed_url}\n", encoding="utf-8")
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    log_file = tmp_path / "download.log"
    activity_log_file = tmp_path / "activity.log"

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        log_file=log_file,
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
    )

    def fake_run(
        command: list[str],
        *args,
        **kwargs,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command, 1, stdout="", stderr="unsupported URL"
        )

    monkeypatch.setattr(downloads_service_module.subprocess, "run", fake_run)

    _, success = downloader._download_video(
        failed_url,
        index=1,
        total=1,
        use_archive=False,
    )

    assert success is False
    activity_text = activity_log_file.read_text(encoding="utf-8")
    assert "Failed:" in activity_text
    assert "unsupported URL" not in activity_text


def test_download_video_writes_concise_success_activity_event(
    tmp_path,
    monkeypatch,
) -> None:
    """The browser activity feed should get concise success entries."""
    video_url = "https://videos.example.com/watch/episode-1"
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(f"{video_url}\n", encoding="utf-8")
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    output_mp3 = downloads_dir / "singles" / "creator - episode.mp3"
    output_mp3.parent.mkdir()
    log_file = tmp_path / "download.log"
    activity_log_file = tmp_path / "activity.log"

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        log_file=log_file,
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
    )

    def fake_run(
        command: list[str],
        *args,
        **kwargs,
    ) -> subprocess.CompletedProcess[str]:
        if command[0] == "yt-dlp":
            output_mp3.write_text("audio", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        write_fake_ffmpeg_output(command, "audio with date tag")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(downloads_service_module.subprocess, "run", fake_run)

    _, success = downloader._download_video(
        video_url,
        index=1,
        total=1,
        use_archive=False,
    )

    assert success is True
    activity_text = activity_log_file.read_text(encoding="utf-8")
    assert "Downloaded: creator - episode.mp3" in activity_text


def test_download_all_removes_successful_direct_url_without_archiving_it(
    tmp_path,
    monkeypatch,
) -> None:
    """Direct queue URLs should be removed after success without entering the archive."""
    video_url = "https://videos.example.com/watch/episode-1"
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(f"{video_url}\n", encoding="utf-8")
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    output_mp3 = downloads_dir / "singles" / "creator - episode.mp3"
    output_mp3.parent.mkdir()
    archive_file = tmp_path / "downloaded_urls.txt"

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=archive_file,
    )

    def fake_run(
        command: list[str],
        *args,
        **kwargs,
    ) -> subprocess.CompletedProcess[str]:
        if command[0] == "yt-dlp":
            output_mp3.write_text("audio", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        write_fake_ffmpeg_output(command, "audio with date tag")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(downloads_service_module.subprocess, "run", fake_run)

    successful, failed = downloader.download_all()

    assert (successful, failed) == (1, 0)
    assert urls_file.read_text(encoding="utf-8") == ""
    assert not archive_file.exists()


def test_single_queue_url_removes_successful_direct_url_without_archiving_it(
    tmp_path,
    monkeypatch,
) -> None:
    """Immediate single-video runs should not archive one-off direct URLs."""
    video_url = "https://videos.example.com/watch/episode-1"
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(f"{video_url}\n", encoding="utf-8")
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    output_mp3 = downloads_dir / "singles" / "creator - episode.mp3"
    output_mp3.parent.mkdir()
    archive_file = tmp_path / "downloaded_urls.txt"

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=archive_file,
    )

    def fake_run(
        command: list[str],
        *args,
        **kwargs,
    ) -> subprocess.CompletedProcess[str]:
        if command[0] == "yt-dlp":
            output_mp3.write_text("audio", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        write_fake_ffmpeg_output(command, "audio with date tag")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(downloads_service_module.subprocess, "run", fake_run)

    successful, failed = downloader.download_single_queue_url(video_url)

    assert (successful, failed) == (1, 0)
    assert urls_file.read_text(encoding="utf-8") == ""


def test_watch_url_success_removes_matching_live_url_from_queue_without_archiving(
    tmp_path,
    monkeypatch,
) -> None:
    """Live and normal YouTube URLs for the same video should be one queue item."""
    live_url = "https://www.youtube.com/live/hPwmCl_nLiQ"
    watch_url = "https://www.youtube.com/watch?v=hPwmCl_nLiQ"
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(f"{live_url}\n", encoding="utf-8")
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    output_mp3 = downloads_dir / "singles" / "Top Traders Unplugged - episode.mp3"
    output_mp3.parent.mkdir()
    archive_file = tmp_path / "downloaded_urls.txt"

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=archive_file,
    )

    def fake_run(
        command: list[str],
        *args,
        **kwargs,
    ) -> subprocess.CompletedProcess[str]:
        if command[0] == "yt-dlp":
            output_mp3.write_text("audio", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        write_fake_ffmpeg_output(command, "audio with date tag")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(downloads_service_module.subprocess, "run", fake_run)

    _, success = downloader._download_video(
        watch_url,
        index=1,
        total=1,
        use_archive=False,
    )

    assert success is True
    assert urls_file.read_text(encoding="utf-8") == ""
    assert not archive_file.exists()


def test_single_queue_url_skips_too_new_youtube_video_without_bypass(
    tmp_path,
    monkeypatch,
) -> None:
    """Immediate unchecked YouTube runs should leave too-new videos queued."""
    video_url = "https://www.youtube.com/watch?v=abc123"
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(f"{video_url}\n", encoding="utf-8")
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    bypass_file = tmp_path / "bypass_age_check_urls.txt"

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
        min_channel_video_age_hours=24,
        bypass_age_check_file=bypass_file,
    )

    monkeypatch.setattr(
        downloads_service_module,
        "get_video_metadata",
        lambda *args, **kwargs: ("2000000000", "20330518"),
    )
    monkeypatch.setattr(
        downloads_service_module,
        "is_old_enough",
        lambda *args, **kwargs: False,
    )

    def fail_if_download_is_attempted(*args, **kwargs) -> None:
        raise AssertionError("too-new YouTube videos should not call yt-dlp")

    monkeypatch.setattr(downloader, "_download_video", fail_if_download_is_attempted)

    successful, failed = downloader.download_single_queue_url(video_url)

    assert (successful, failed) == (0, 0)
    assert urls_file.read_text(encoding="utf-8") == f"{video_url}\n"


def test_single_queue_url_downloads_old_enough_youtube_video_without_bypass(
    tmp_path,
    monkeypatch,
) -> None:
    """Immediate unchecked YouTube runs should download videos that pass the age gate."""
    video_url = "https://www.youtube.com/watch?v=abc123"
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(f"{video_url}\n", encoding="utf-8")
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
        min_channel_video_age_hours=24,
        bypass_age_check_file=tmp_path / "bypass_age_check_urls.txt",
    )

    monkeypatch.setattr(
        downloads_service_module,
        "get_video_metadata",
        lambda *args, **kwargs: ("1000000000", "20010909"),
    )
    monkeypatch.setattr(
        downloads_service_module,
        "is_old_enough",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        downloader,
        "_download_video",
        lambda *args, **kwargs: (video_url, True),
    )

    successful, failed = downloader.download_single_queue_url(video_url)

    assert (successful, failed) == (1, 0)


def test_single_queue_url_bypass_downloads_too_new_youtube_video(
    tmp_path,
    monkeypatch,
) -> None:
    """A bypass-marked immediate YouTube run should skip only the age check."""
    video_url = "https://www.youtube.com/watch?v=abc123"
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(f"{video_url}\n", encoding="utf-8")
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    bypass_file = tmp_path / "bypass_age_check_urls.txt"
    bypass_file.write_text(f"{video_url}\n", encoding="utf-8")

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
        min_channel_video_age_hours=24,
        bypass_age_check_file=bypass_file,
    )

    def fail_if_metadata_is_loaded(*args, **kwargs) -> None:
        raise AssertionError("bypass-marked videos should not read age metadata")

    monkeypatch.setattr(
        downloads_service_module,
        "get_video_metadata",
        fail_if_metadata_is_loaded,
    )
    monkeypatch.setattr(
        downloader,
        "_download_video",
        lambda *args, **kwargs: (video_url, True),
    )

    successful, failed = downloader.download_single_queue_url(video_url)

    assert (successful, failed) == (1, 0)


def test_download_full_playlist_now_downloads_every_expanded_video(
    tmp_path,
    monkeypatch,
) -> None:
    """Immediate playlist runs should download every expanded entry with archive use."""
    playlist_url = "https://www.youtube.com/playlist?list=playlist-name1"
    playlist_video_urls = [
        "https://www.youtube.com/watch?v=playlist001",
        "https://www.youtube.com/watch?v=playlist002",
    ]
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(f"{playlist_url}\n", encoding="utf-8")
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    archive_file = tmp_path / "downloaded_urls.txt"

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=archive_file,
    )

    def fake_expand(
        url: str,
        *args,
        **kwargs,
    ) -> list[str]:
        assert kwargs.get("full_playlist") is True
        if url == playlist_url:
            return playlist_video_urls
        raise AssertionError(f"unexpected expandable URL: {url}")

    downloaded_urls: list[str] = []

    def fake_run(
        command: list[str],
        *args,
        **kwargs,
    ) -> subprocess.CompletedProcess[str]:
        if command[0] == "yt-dlp":
            output_template = Path(command[command.index("--output") + 1])
            output_template.parent.mkdir(parents=True, exist_ok=True)
            output_mp3 = (
                output_template.parent / f"creator - {len(downloaded_urls) + 1}.mp3"
            )
            output_mp3.write_text("audio", encoding="utf-8")
            downloaded_urls.append(command[-1])
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        write_fake_ffmpeg_output(command, "audio with date tag")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(
        downloads_service_module, "expand_channel_or_playlist", fake_expand
    )
    monkeypatch.setattr(downloads_service_module.subprocess, "run", fake_run)

    successful, failed = downloader.download_full_playlist_now(playlist_url)

    assert (successful, failed) == (2, 0)
    assert downloaded_urls == playlist_video_urls
    assert archive_file.read_text(encoding="utf-8").splitlines() == playlist_video_urls


def test_download_all_routes_mp3s_to_source_folders_without_moving_queue(
    tmp_path,
    monkeypatch,
) -> None:
    """Downloads should be grouped by source while the queue file stays in place."""
    channel_url = "https://www.youtube.com/@channel-one/videos"
    playlist_url = "https://www.youtube.com/playlist?list=playlist-name1"
    single_url = "https://videos.example.com/watch/episode-1"
    channel_video_url = "https://www.youtube.com/watch?v=channel001"
    playlist_video_url = "https://www.youtube.com/watch?v=playlist001"
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(
        f"{channel_url}\n{playlist_url}\n{single_url}\n",
        encoding="utf-8",
    )
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=tmp_path / "downloaded_urls.txt",
    )

    def fake_expand(
        url: str,
        *args,
        **kwargs,
    ) -> list[str]:
        if url == channel_url:
            return [channel_video_url]
        if url == playlist_url:
            return [playlist_video_url]
        raise AssertionError(f"unexpected expandable URL: {url}")

    expected_parents = [
        downloads_dir / "channel-one",
        downloads_dir / "playlist-name1",
        downloads_dir / "singles",
    ]
    actual_parents: list[Path] = []

    def fake_run(
        command: list[str],
        *args,
        **kwargs,
    ) -> subprocess.CompletedProcess[str]:
        if command[0] == "yt-dlp":
            output_template = Path(command[command.index("--output") + 1])
            actual_parents.append(output_template.parent)
            output_template.parent.mkdir(parents=True, exist_ok=True)
            output_mp3 = output_template.parent / f"creator - {len(actual_parents)}.mp3"
            output_mp3.write_text("audio", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        write_fake_ffmpeg_output(command, "audio with date tag")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(
        downloads_service_module, "expand_channel_or_playlist", fake_expand
    )
    monkeypatch.setattr(downloads_service_module.subprocess, "run", fake_run)

    successful, failed = downloader.download_all()

    assert (successful, failed) == (3, 0)
    assert actual_parents == expected_parents
    assert urls_file.exists()
    assert f"{channel_url}\n{playlist_url}\n" == urls_file.read_text(encoding="utf-8")


def test_delete_expired_channel_audio_removes_archive_url_and_preserves_other_sources(
    tmp_path,
    monkeypatch,
) -> None:
    """Retention should apply only to channel files and remove their archive URL."""
    channel_url = "https://www.youtube.com/@channel-one"
    playlist_url = "https://www.youtube.com/playlist?list=playlist-name1"
    channel_video_url = "https://www.youtube.com/watch?v=channel001"
    playlist_video_url = "https://www.youtube.com/watch?v=playlist001"
    single_video_url = "https://videos.example.com/watch/episode-1"
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(f"{channel_url}\n{playlist_url}\n", encoding="utf-8")
    downloads_dir = tmp_path / "downloads"
    old_file = downloads_dir / "channel-one" / "old.mp3"
    playlist_file = downloads_dir / "playlist-name1" / "old-playlist.mp3"
    single_file = downloads_dir / "singles" / "old-single.mp3"
    missing_url_file = downloads_dir / "channel-one" / "missing-url.mp3"
    for audio_file in [old_file, playlist_file, single_file, missing_url_file]:
        audio_file.parent.mkdir(parents=True, exist_ok=True)
        audio_file.write_text("audio", encoding="utf-8")

    current_time = datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc)
    old_download_time = current_time - timedelta(days=91)
    archive_file = tmp_path / "downloaded_urls.txt"
    archive_file.write_text(
        f"{channel_video_url}\n{playlist_video_url}\n",
        encoding="utf-8",
    )

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=archive_file,
        retention_days=90,
    )

    def fake_read_download_date(audio_file: Path) -> str | None:
        if audio_file in {old_file, playlist_file, single_file, missing_url_file}:
            return old_download_time.isoformat()
        return None

    def fake_read_source_url(audio_file: Path) -> str | None:
        if audio_file == old_file:
            return channel_video_url
        if audio_file == playlist_file:
            return playlist_video_url
        if audio_file == single_file:
            return single_video_url
        return None

    monkeypatch.setattr(
        downloader,
        "_read_audio_download_date_metadata",
        fake_read_download_date,
    )
    monkeypatch.setattr(
        downloader,
        "_read_audio_source_url_metadata",
        fake_read_source_url,
    )

    channel_dirs = downloader._retention_channel_output_dirs(
        [channel_url, playlist_url]
    )
    deleted_files = downloader._delete_expired_audio_files(
        current_time=current_time,
        retention_dirs=channel_dirs,
    )

    assert deleted_files == [old_file]
    assert not old_file.exists()
    assert playlist_file.exists()
    assert single_file.exists()
    assert missing_url_file.exists()
    assert archive_file.read_text(encoding="utf-8") == f"{playlist_video_url}\n"


def test_download_all_retries_channel_item_after_retention_removes_archive_entry(
    tmp_path,
    monkeypatch,
) -> None:
    """A scheduled run should delete expired channel audio before archive checks."""
    channel_url = "https://www.youtube.com/@channel-one"
    channel_video_url = "https://www.youtube.com/watch?v=channel001"
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(f"{channel_url}\n", encoding="utf-8")

    downloads_dir = tmp_path / "downloads"
    expired_audio_file = downloads_dir / "channel-one" / "old.mp3"
    expired_audio_file.parent.mkdir(parents=True, exist_ok=True)
    expired_audio_file.write_text("audio", encoding="utf-8")

    archive_file = tmp_path / "downloaded_urls.txt"
    archive_file.write_text(f"{channel_video_url}\n", encoding="utf-8")

    downloader = PodcastDownloader(
        urls_file=urls_file,
        downloads_dir=downloads_dir,
        log_file=tmp_path / "download.log",
        downloaded_urls_file=archive_file,
        retention_days=30,
        delay_seconds=0,
    )

    expired_download_time = datetime(2000, 1, 1, 12, 0, tzinfo=timezone.utc)
    attempted_urls: list[str] = []

    def fake_expand(
        url: str,
        *_args: object,
        **_kwargs: object,
    ) -> list[str]:
        assert url == channel_url
        return [channel_video_url]

    def fake_download_video_unlocked(
        video_url: str,
        _index: int,
        _total: int,
        _final_output_dir: Path,
        _work_dir: Path,
    ) -> tuple[str, bool]:
        attempted_urls.append(video_url)
        return video_url, True

    monkeypatch.setattr(
        downloads_service_module,
        "expand_channel_or_playlist",
        fake_expand,
    )
    monkeypatch.setattr(
        downloader,
        "_read_audio_download_date_metadata",
        lambda _audio_file: expired_download_time.isoformat(),
    )
    monkeypatch.setattr(
        downloader,
        "_read_audio_source_url_metadata",
        lambda _audio_file: channel_video_url,
    )
    monkeypatch.setattr(
        downloader,
        "_download_video_unlocked",
        fake_download_video_unlocked,
    )

    successful, failed = downloader.download_all()

    assert (successful, failed) == (1, 0)
    assert attempted_urls == [channel_video_url]
    assert not expired_audio_file.exists()
    assert archive_file.read_text(encoding="utf-8") == f"{channel_video_url}\n"
