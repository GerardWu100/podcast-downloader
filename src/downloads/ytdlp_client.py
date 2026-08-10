"""Run ``yt-dlp`` audio downloads behind one explicit client boundary."""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..config import DEFAULT_DOWNLOAD_TIMEOUT_SECONDS
from ..media.youtube import is_youtube_url

SPONSORBLOCK_CATEGORIES = "sponsor,selfpromo"
YTDLP_OUTPUT_FILENAME_TEMPLATE = "%(channel,uploader)s - %(title)s [%(id)s].%(ext)s"

RunCommand = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class AudioSnapshot:
    """MP3 file state captured around one download attempt.

    Attributes
    ----------
    files:
        Mapping from MP3 path to ``(mtime_ns, size_bytes)``. ``mtime_ns`` is
        the filesystem modification time in nanoseconds.
    """

    files: dict[Path, tuple[int, int]]


@dataclass(frozen=True)
class YtDlpResult:
    """Observable result of a complete audio-download request.

    Attributes
    ----------
    returncode:
        Exit status from the final ``yt-dlp`` attempt.
    stdout:
        Standard output from the final attempt.
    stderr:
        Standard error from the final attempt.
    changed_audio_files:
        MP3 files created or changed across all attempts.
    before_snapshot:
        MP3 state before the first attempt.
    after_snapshot:
        MP3 state after the final attempt.
    attempts:
        Number of subprocess attempts, either one or two.
    """

    returncode: int
    stdout: str
    stderr: str
    changed_audio_files: list[Path]
    before_snapshot: AudioSnapshot
    after_snapshot: AudioSnapshot
    attempts: int


class YtDlpClient:
    """Construct and execute ``yt-dlp`` audio-download commands.

    Parameters
    ----------
    cookies_file:
        Optional Netscape-format cookie file used only for YouTube.
    always_use_cookies:
        When ``True``, try YouTube with cookies and retry without them. When
        ``False``, try without cookies and retry with them.
    logger:
        Destination for retry messages.
    run_command:
        Subprocess-compatible callable; tests may inject a deterministic fake.
    download_timeout_seconds:
        Wall-clock limit for one ``yt-dlp`` attempt.
    """

    def __init__(
        self,
        *,
        cookies_file: Path | None,
        always_use_cookies: bool,
        logger: logging.Logger,
        run_command: RunCommand = subprocess.run,
        download_timeout_seconds: int = DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
    ) -> None:
        self.cookies_file = cookies_file
        self.always_use_cookies = always_use_cookies
        self.logger = logger
        self.run_command = run_command
        self.download_timeout_seconds = download_timeout_seconds

    def snapshot_audio(self, work_dir: Path) -> AudioSnapshot:
        """Capture recursive MP3 modification time and size state."""
        captured_files: dict[Path, tuple[int, int]] = {}

        # Recursive snapshots include extractor-created subfolders while
        # remaining scoped to this source's isolated working directory.
        for audio_file in work_dir.rglob("*.mp3"):
            if not audio_file.is_file():
                continue
            file_stat = audio_file.stat()
            captured_files[audio_file] = (
                file_stat.st_mtime_ns,
                file_stat.st_size,
            )
        return AudioSnapshot(files=captured_files)

    @staticmethod
    def changed_audio_files(
        before_snapshot: AudioSnapshot,
        after_snapshot: AudioSnapshot,
    ) -> list[Path]:
        """Return MP3 paths created or changed between two snapshots."""
        return sorted(
            audio_file
            for audio_file, after_state in after_snapshot.files.items()
            if before_snapshot.files.get(audio_file) != after_state
        )

    def build_download_command(
        self,
        url: str,
        work_dir: Path,
        cookies_file: Path | None,
    ) -> list[str]:
        """Build one audio-download command with a safe URL separator."""
        command = [
            "yt-dlp",
            "--paths",
            f"temp:{work_dir}",
            "--extract-audio",
            "--audio-format",
            "mp3",
            "--audio-quality",
            "0",
            "--no-mtime",
            "--embed-thumbnail",
            "--add-metadata",
            "--output",
            str(work_dir / YTDLP_OUTPUT_FILENAME_TEMPLATE),
        ]
        if is_youtube_url(url):
            command.extend(["--sponsorblock-remove", SPONSORBLOCK_CATEGORIES])
        else:
            command.append("--no-playlist")
        if cookies_file is not None:
            command.extend(["--cookies", str(cookies_file)])

        # ``--`` prevents a user-controlled URL beginning with a dash from
        # being interpreted as another command-line option.
        command.extend(["--", url])
        return command

    def _run_attempt(
        self,
        url: str,
        work_dir: Path,
        cookies_file: Path | None,
    ) -> subprocess.CompletedProcess[str]:
        """Run one bounded ``yt-dlp`` subprocess attempt."""
        command = self.build_download_command(url, work_dir, cookies_file)
        return self.run_command(
            command,
            capture_output=True,
            text=True,
            timeout=self.download_timeout_seconds,
            check=False,
        )

    def _first_attempt_cookies(self, url: str) -> Path | None:
        """Choose cookies for the first attempt according to configured policy."""
        if not is_youtube_url(url) or self.cookies_file is None:
            return None
        return self.cookies_file if self.always_use_cookies else None

    def _retry_cookies(
        self,
        url: str,
        first_attempt_cookies: Path | None,
    ) -> tuple[bool, Path | None]:
        """Return whether to retry and which alternate cookie mode to use.

        Parameters
        ----------
        url:
            Media URL from the failed first attempt.
        first_attempt_cookies:
            Cookie file used by the first attempt, or ``None`` for a plain
            request.

        Returns
        -------
        tuple[bool, Path | None]
            ``(should_retry, cookies_file)``. A true decision with ``None``
            means retry without cookies.
        """
        if not is_youtube_url(url) or self.cookies_file is None:
            return False, None

        # YouTube gets one retry with the opposite cookie policy.
        if self.always_use_cookies and first_attempt_cookies is not None:
            return True, None
        if not self.always_use_cookies and first_attempt_cookies is None:
            return True, self.cookies_file
        return False, None

    def download(self, url: str, work_dir: Path) -> YtDlpResult:
        """Run an audio download, including one alternate-cookie retry.

        A zero exit status without a changed MP3 is treated as a failed
        attempt for retry purposes. The service may still recover one existing
        MP3 after this client returns when a prior metadata pass failed.

        Parameters
        ----------
        url:
            Direct media URL passed to ``yt-dlp``.
        work_dir:
            Source-scoped scratch folder for downloads and snapshots.

        Returns
        -------
        YtDlpResult
            Final process output and MP3 state across one or two attempts.
        """
        work_dir.mkdir(parents=True, exist_ok=True)
        before_snapshot = self.snapshot_audio(work_dir)
        first_attempt_cookies = self._first_attempt_cookies(url)
        process = self._run_attempt(url, work_dir, first_attempt_cookies)
        after_snapshot = self.snapshot_audio(work_dir)
        changed_files = self.changed_audio_files(before_snapshot, after_snapshot)
        attempts = 1

        first_attempt_failed = process.returncode != 0 or not changed_files
        should_retry, retry_cookies = self._retry_cookies(
            url,
            first_attempt_cookies,
        )
        if first_attempt_failed and should_retry:
            if first_attempt_cookies is not None:
                self.logger.info(
                    "Cookie YouTube download failed; retrying without cookies"
                )
            else:
                self.logger.info(
                    "Plain YouTube download failed; retrying with cookies file: %s",
                    self.cookies_file,
                )
            process = self._run_attempt(url, work_dir, retry_cookies)
            after_snapshot = self.snapshot_audio(work_dir)
            changed_files = self.changed_audio_files(
                before_snapshot,
                after_snapshot,
            )
            attempts = 2

        return YtDlpResult(
            returncode=process.returncode,
            stdout=process.stdout or "",
            stderr=process.stderr or "",
            changed_audio_files=changed_files,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            attempts=attempts,
        )
