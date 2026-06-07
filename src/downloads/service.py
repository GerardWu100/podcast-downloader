"""Download orchestration for media URLs, archive updates, and activity logs."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from ..activity_log import activity_log_file_for, write_activity_event
from ..config import DEFAULT_CHANNEL_VIDEO_COUNT
from ..url_utils import (
    expand_channel_or_playlist,
    get_video_metadata,
    get_youtube_channel_display_name,
    get_youtube_channel_folder_name,
    get_youtube_playlist_folder_name,
    is_channel_or_playlist,
    is_old_enough,
    is_youtube_short_url,
    is_youtube_url,
    load_bypass_age_urls,
    load_downloaded_url_archive,
    locked_downloaded_url_archive,
    looks_like_youtube_channel_id,
    normalize_youtube_url,
    read_urls_file,
    remove_from_bypass_age_file,
    remove_from_downloaded_url_archive,
    remove_video_url_from_file,
)
from .audio_metadata import AudioMetadataWriter
from .ytdlp_client import AudioSnapshot

FALLBACK_SINGLE_DOWNLOAD_FOLDER = "singles"
YTDLP_OUTPUT_FILENAME_TEMPLATE = "%(channel,uploader)s - %(title)s.%(ext)s"
INTERMEDIATE_ROOT_TEMP_SUFFIXES = (
    ".part",
    ".ytdl",
    ".frag",
    ".temp",
    ".download",
    ".tmp",
)
INVALID_FOLDER_CHARACTER_PATTERN = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


@dataclass(frozen=True)
class DownloadTarget:
    """Concrete video URL plus the output folder policy for that attempt.

    Attributes
    ----------
    video_url:
        Direct media URL passed to ``yt-dlp``.
    output_dir:
        Folder where the finished MP3 should be published.
    use_archive:
        Whether ``downloaded_urls.txt`` should be checked and updated. This is
        true for videos expanded from channels and playlists, and false for
        direct one-off video URLs.
    """

    video_url: str
    output_dir: Path
    use_archive: bool


class PodcastDownloadService:
    """Run one batch of downloads and keep queue/archive files in sync."""

    def __init__(
        self,
        urls_file: Path,
        downloads_dir: Path,
        intermediate_dir: Path | None = None,
        channel_count: int = DEFAULT_CHANNEL_VIDEO_COUNT,
        log_file: Path | None = None,
        downloaded_urls_file: Path | None = None,
        min_channel_video_age_hours: int = 24,
        delay_seconds: float = 2.0,
        retention_days: int = 30,
        cookies_file: Path | None = None,
        always_use_cookies: bool = False,
        bypass_age_check_file: Path | None = None,
    ) -> None:
        """Create a downloader service for one queue/archive location.

        Parameters
        ----------
        urls_file:
            Queue file containing direct media URLs and monitored YouTube
            channel/playlist URLs.
        downloads_dir:
            Folder where finished MP3 files are published for playback libraries.
        intermediate_dir:
            Scratch folder where ``yt-dlp`` and the metadata pass write files
            before they are moved into ``downloads_dir``. Defaults to
            ``downloads_dir`` when omitted so tests and one-off callers keep
            working without an extra path.
        channel_count:
            Number of old-enough non-Shorts videos to pull from each channel.
        log_file:
            Detailed runtime log. ``activity.log`` is derived from this path.
        downloaded_urls_file:
            Archive for expanded channel/playlist video URLs that succeeded.
        min_channel_video_age_hours:
            Minimum age gate for YouTube videos when metadata is known.
        delay_seconds:
            Sleep between queued downloads to avoid hammering the remote site.
        retention_days:
            Number of days to keep MP3 files, measured from the embedded
            download-date metadata written after a successful download.
        cookies_file:
            Optional cookies file passed to ``yt-dlp``.
        always_use_cookies:
            When true, pass ``cookies_file`` on the first YouTube ``yt-dlp`` call.
            When false, try without cookies first and retry once with the file.
        bypass_age_check_file:
            One-shot file of direct YouTube videos allowed to skip the age gate.
        """
        self.urls_file = urls_file
        self.downloads_dir = downloads_dir
        self.intermediate_dir = intermediate_dir or downloads_dir
        self.channel_count = channel_count
        self.log_file = log_file or (urls_file.parent / "download.log")
        self.activity_log_file = activity_log_file_for(self.log_file)
        self.downloaded_urls_file = downloaded_urls_file or (
            urls_file.parent / "downloaded_urls.txt"
        )
        self.min_channel_video_age_hours = max(0, min_channel_video_age_hours)
        self.delay_seconds = max(0.0, delay_seconds)
        self.retention_days = max(1, retention_days)
        self.cookies_file = cookies_file
        self.always_use_cookies = always_use_cookies
        self.bypass_age_check_file = bypass_age_check_file or (
            urls_file.parent / "bypass_age_check_urls.txt"
        )
        self.audio_metadata_writer = AudioMetadataWriter(
            run_command=lambda command, **kwargs: subprocess.run(command, **kwargs),
        )

        self._setup_logging()
        self._downloaded_urls = self._load_downloaded_urls()

        if self.cookies_file:
            cookie_mode = "always" if self.always_use_cookies else "fallback"
            self.logger.info(
                "Using cookies file (%s mode): %s",
                cookie_mode,
                self.cookies_file,
            )

    def _snapshot_downloaded_audio(self) -> AudioSnapshot:
        """Capture MP3 state in the work directory so changes can be detected."""
        snapshot: dict[Path, tuple[int, int]] = {}
        for mp3_path in self.intermediate_dir.rglob("*.mp3"):
            if not mp3_path.is_file():
                continue

            file_stat = mp3_path.stat()
            snapshot[mp3_path] = (file_stat.st_mtime_ns, file_stat.st_size)

        return AudioSnapshot(files=snapshot)

    def _sanitize_download_folder_name(self, raw_name: str) -> str:
        """Return a filesystem-safe folder name derived from a source URL."""
        decoded_name = unquote(raw_name).strip()
        if decoded_name.startswith("@"):
            decoded_name = decoded_name[1:]

        without_handle_prefix = decoded_name
        collapsed_whitespace = re.sub(r"\s+", "-", without_handle_prefix)
        safe_name = INVALID_FOLDER_CHARACTER_PATTERN.sub("-", collapsed_whitespace)
        safe_name = safe_name.strip(" .-_")
        return safe_name or FALLBACK_SINGLE_DOWNLOAD_FOLDER

    def _source_folder_name(self, source_url: str) -> str:
        """Derive the direct child folder name used for one queue source."""
        if not is_channel_or_playlist(source_url):
            return FALLBACK_SINGLE_DOWNLOAD_FOLDER

        parsed = urlparse(source_url)
        query_values = parse_qs(parsed.query)
        playlist_id = query_values.get("list", [""])[0]
        if playlist_id:
            playlist_name = get_youtube_playlist_folder_name(
                source_url,
                self.logger,
                self.cookies_file,
                self.always_use_cookies,
            )
            if playlist_name:
                return self._sanitize_download_folder_name(playlist_name)
            return self._sanitize_download_folder_name(playlist_id)

        path_parts = [part for part in parsed.path.split("/") if part]
        if path_parts and path_parts[0].startswith("@"):
            folder_name = self._sanitize_download_folder_name(path_parts[0])
        elif len(path_parts) >= 2 and path_parts[0] in {"c", "channel", "user"}:
            folder_name = self._sanitize_download_folder_name(path_parts[1])
        elif path_parts:
            folder_name = self._sanitize_download_folder_name(path_parts[-1])
        else:
            hostname = parsed.hostname or "source"
            folder_name = self._sanitize_download_folder_name(hostname)

        if looks_like_youtube_channel_id(folder_name):
            resolved_name = get_youtube_channel_folder_name(
                source_url,
                self.logger,
                self.cookies_file,
                self.always_use_cookies,
            )
            if resolved_name:
                folder_name = self._sanitize_download_folder_name(resolved_name)

        return folder_name

    def _download_output_dir_for_source(self, source_url: str) -> Path:
        """Return the direct child folder for finished MP3s from one queue source."""
        folder_name = self._source_folder_name(source_url)
        return self.downloads_dir / folder_name

    def _intermediate_output_dir_for_source(self, source_url: str) -> Path:
        """Return the scratch folder where one queue source is downloaded first."""
        folder_name = self._source_folder_name(source_url)
        return self.intermediate_dir / folder_name

    def _uses_separate_intermediate_dir(self) -> bool:
        """Return whether finished MP3s are published into a different tree."""
        return self.intermediate_dir.resolve() != self.downloads_dir.resolve()

    def _publish_audio_files_to_output_dir(
        self,
        intermediate_audio_files: list[Path],
        final_output_dir: Path,
    ) -> list[Path]:
        """Move stamped MP3 files from the work tree into the library tree."""
        if not intermediate_audio_files:
            return []

        final_output_dir.mkdir(parents=True, exist_ok=True)
        if not self._uses_separate_intermediate_dir():
            return intermediate_audio_files

        published_files: list[Path] = []
        for intermediate_file in intermediate_audio_files:
            destination_file = final_output_dir / intermediate_file.name
            shutil.move(str(intermediate_file), str(destination_file))
            published_files.append(destination_file)

        return published_files

    def _delete_intermediate_file(self, file_path: Path) -> None:
        """Delete one scratch file and log a warning when removal fails."""
        try:
            file_path.unlink()
        except OSError as exc:
            self.logger.warning(
                "Could not delete intermediate artifact %s: %s",
                file_path,
                exc,
            )

    def _delete_non_mp3_files_in_tree(self, work_dir: Path) -> None:
        """Remove every non-MP3 file under one work folder."""
        if not work_dir.exists():
            return

        for candidate_file in work_dir.rglob("*"):
            if not candidate_file.is_file():
                continue
            if candidate_file.suffix.lower() == ".mp3":
                continue
            self._delete_intermediate_file(candidate_file)

    def _delete_work_dir_files_except(
        self,
        work_dir: Path,
        preserved_paths: set[Path],
    ) -> None:
        """Remove scratch files from one work folder while keeping selected paths."""
        if not work_dir.exists():
            return

        for candidate_path in sorted(work_dir.rglob("*"), reverse=True):
            if candidate_path.is_file():
                if candidate_path.resolve() in preserved_paths:
                    continue
                self._delete_intermediate_file(candidate_path)
                continue

            if candidate_path.is_dir() and candidate_path != work_dir:
                try:
                    candidate_path.rmdir()
                except OSError:
                    continue

    def _cleanup_intermediate_work_dir(
        self,
        work_dir: Path,
        *,
        preserve_mp3_files: list[Path] | None = None,
    ) -> None:
        """Remove scratch files from one work folder after an attempt finishes.

        When ``preserve_mp3_files`` is set, keep those MP3 paths for a later
        metadata retry and delete every other file in the work folder. When it
        is omitted and ``intermediate_dir`` is separate from ``downloads_dir``,
        delete the entire work folder. In the legacy single-tree layout, delete
        only non-MP3 artifacts so finished MP3 files remain in place.
        """
        if not work_dir.exists():
            return

        if preserve_mp3_files is not None:
            preserved_paths = {
                mp3_path.resolve()
                for mp3_path in preserve_mp3_files
                if mp3_path.exists()
            }
            self._delete_work_dir_files_except(work_dir, preserved_paths)
            return

        if not self._uses_separate_intermediate_dir():
            self._delete_non_mp3_files_in_tree(work_dir)
            return

        try:
            shutil.rmtree(work_dir)
        except OSError as exc:
            self.logger.warning(
                "Could not delete intermediate work directory %s: %s",
                work_dir,
                exc,
            )

    def _cleanup_intermediate_root_temp_files(self) -> None:
        """Remove stale ``yt-dlp`` temp files left at the intermediate root."""
        if not self._uses_separate_intermediate_dir():
            return
        if not self.intermediate_dir.is_dir():
            return

        for candidate_file in self.intermediate_dir.iterdir():
            if not candidate_file.is_file():
                continue
            if candidate_file.suffix.lower() not in INTERMEDIATE_ROOT_TEMP_SUFFIXES:
                continue
            self._delete_intermediate_file(candidate_file)

    def _finalize_intermediate_cleanup(
        self,
        work_dir: Path,
        *,
        preserve_mp3_files: list[Path] | None = None,
    ) -> None:
        """Run work-folder and root temp cleanup after one download attempt."""
        self._cleanup_intermediate_work_dir(
            work_dir,
            preserve_mp3_files=preserve_mp3_files,
        )
        self._cleanup_intermediate_root_temp_files()

    def _is_youtube_channel_source(self, source_url: str) -> bool:
        """Return whether a queue source is a YouTube channel, not a playlist."""
        if not is_youtube_url(source_url):
            return False

        parsed = urlparse(source_url)
        query_values = parse_qs(parsed.query)
        if query_values.get("list", [""])[0]:
            return False

        path_parts = [part for part in parsed.path.split("/") if part]
        if not path_parts:
            return False

        first_part = path_parts[0]
        return first_part.startswith("@") or first_part in {"c", "channel", "user"}

    def _retention_channel_output_dirs(self, urls: list[str]) -> set[Path]:
        """Return output folders eligible for retention cleanup."""
        retention_dirs: set[Path] = set()
        for url in urls:
            if self._is_youtube_channel_source(url):
                retention_dirs.add(self._download_output_dir_for_source(url))

        return retention_dirs

    def _detect_changed_audio_files(
        self,
        before_snapshot: AudioSnapshot,
        after_snapshot: AudioSnapshot,
    ) -> list[Path]:
        """Return MP3 files created or changed during one command."""
        changed_files: list[Path] = []
        for file_path, updated_state in after_snapshot.files.items():
            previous_state = before_snapshot.files.get(file_path)
            if previous_state is None or updated_state != previous_state:
                changed_files.append(file_path)

        return sorted(changed_files)

    def _format_download_date_metadata(self, download_timestamp: float) -> str:
        """Format a POSIX timestamp as a local timezone-aware ISO string."""
        local_download_time = datetime.fromtimestamp(download_timestamp).astimezone()
        return local_download_time.isoformat()

    def _write_audio_download_date_metadata(
        self,
        audio_file: Path,
        download_date_metadata: str,
        source_url_metadata: str,
        channel_display_name: str | None = None,
    ) -> None:
        """Write local download-date and source URL metadata into one MP3 file."""
        self.audio_metadata_writer.write_download_metadata(
            audio_file,
            download_date_metadata,
            source_url_metadata,
            channel_display_name=channel_display_name,
        )

    def _stamp_audio_files_with_download_time(
        self,
        audio_files: list[Path],
        source_url_metadata: str,
    ) -> None:
        """Stamp changed MP3 files with local completion time and source URL."""
        download_timestamp = time.time()
        download_date_metadata = self._format_download_date_metadata(download_timestamp)
        channel_display_name = None
        if is_youtube_url(source_url_metadata):
            channel_display_name = get_youtube_channel_display_name(
                source_url_metadata,
                self.logger,
                self.cookies_file,
                self.always_use_cookies,
            )
        for audio_file in audio_files:
            self._write_audio_download_date_metadata(
                audio_file,
                download_date_metadata,
                source_url_metadata,
                channel_display_name=channel_display_name,
            )

    def _setup_logging(self) -> None:
        """Send logs to both the detailed file log and the terminal."""
        file_formatter = logging.Formatter(
            "[%(asctime)s] %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(self.log_file, encoding="utf-8")
        file_handler.setFormatter(file_formatter)
        file_handler.setLevel(logging.DEBUG)

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        self.logger = logging.getLogger("PodcastDownloader")
        self.logger.setLevel(logging.DEBUG)

        for handler in list(self.logger.handlers):
            self.logger.removeHandler(handler)
            handler.close()

        self.logger.propagate = False
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

    def _load_downloaded_urls(self) -> set[str]:
        """Load the archive of expanded URLs that already succeeded."""
        return load_downloaded_url_archive(self.downloaded_urls_file, self.logger)

    @property
    def downloaded_urls(self) -> set[str]:
        """Return the latest archived expanded URLs from disk.

        The archive is shared across downloader processes and service objects,
        so this property refreshes from disk on access instead of trusting only
        constructor-time state.
        """
        self._downloaded_urls = self._load_downloaded_urls()
        return set(self._downloaded_urls)

    @downloaded_urls.setter
    def downloaded_urls(self, urls: set[str]) -> None:
        """Replace the in-memory archive cache used by compatibility callers."""
        self._downloaded_urls = set(urls)

    def _record_activity(self, message: str) -> None:
        """Append one concise browser-facing activity event."""
        try:
            write_activity_event(self.activity_log_file, message)
        except OSError as exc:
            self.logger.warning("Could not write activity log: %s", exc)

    def _read_audio_download_date_metadata(self, audio_file: Path) -> str | None:
        """Read the embedded MP3 date metadata written at download completion."""
        return self._read_audio_metadata_tag(audio_file, "date")

    def _read_audio_source_url_metadata(self, audio_file: Path) -> str | None:
        """Read the embedded source URL stored in the MP3 comment metadata."""
        return self._read_audio_metadata_tag(audio_file, "comment")

    def _read_audio_metadata_tag(self, audio_file: Path, tag_name: str) -> str | None:
        """Read one embedded MP3 format tag using ``ffprobe``."""
        command = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            f"format_tags={tag_name}",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_file),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except Exception as exc:
            self.logger.warning(
                "Could not read MP3 %s metadata for %s: %s",
                tag_name,
                audio_file,
                exc,
            )
            return None

        if result.returncode != 0:
            error_text = result.stderr.strip()
            if error_text:
                self.logger.warning(
                    "Could not read MP3 %s metadata for %s: %s",
                    tag_name,
                    audio_file,
                    error_text,
                )
            return None

        metadata_value = result.stdout.strip()
        return metadata_value or None

    def _parse_download_date_metadata(self, metadata_value: str) -> datetime | None:
        """Parse an embedded MP3 date tag into a comparable datetime."""
        normalized_value = metadata_value.strip()
        if not normalized_value:
            return None

        try:
            parsed_datetime = datetime.fromisoformat(normalized_value)
        except ValueError:
            return None

        if parsed_datetime.tzinfo is None:
            return parsed_datetime.astimezone()

        return parsed_datetime

    def _delete_expired_audio_files(
        self,
        current_time: datetime | None = None,
        retention_dirs: set[Path] | None = None,
    ) -> list[Path]:
        """Delete channel MP3 files older than the configured retention window.

        The age is measured from the embedded audio ``date`` metadata that this
        downloader writes after completion. Only MP3 files inside active
        YouTube channel output folders are eligible. Files with missing date or
        source URL metadata are left in place so cleanup can also remove the
        matching entry from ``downloaded_urls.txt``.
        """
        reference_time = current_time or datetime.now().astimezone()
        normalized_retention_dirs = {path.resolve() for path in retention_dirs or set()}
        if not normalized_retention_dirs:
            return []

        deleted_files: list[Path] = []

        for audio_file in sorted(self.downloads_dir.rglob("*.mp3")):
            audio_parent = audio_file.parent.resolve()
            if audio_parent not in normalized_retention_dirs:
                continue

            metadata_value = self._read_audio_download_date_metadata(audio_file)
            if metadata_value is None:
                self.logger.info(
                    "Skipping retention cleanup for %s because download date metadata is missing",
                    audio_file,
                )
                continue

            download_datetime = self._parse_download_date_metadata(metadata_value)
            if download_datetime is None:
                self.logger.info(
                    "Skipping retention cleanup for %s because download date metadata is invalid: %s",
                    audio_file,
                    metadata_value,
                )
                continue

            comparable_reference_time = reference_time
            if download_datetime.tzinfo is not None and reference_time.tzinfo is None:
                comparable_reference_time = reference_time.astimezone()
            elif download_datetime.tzinfo is None and reference_time.tzinfo is not None:
                download_datetime = download_datetime.astimezone()

            expiration_cutoff = comparable_reference_time - timedelta(
                days=self.retention_days
            )
            if download_datetime >= expiration_cutoff:
                continue

            source_url = self._read_audio_source_url_metadata(audio_file)
            if source_url is None:
                self.logger.info(
                    "Skipping retention cleanup for %s because source URL metadata is missing",
                    audio_file,
                )
                continue

            try:
                audio_file.unlink()
            except OSError as exc:
                self.logger.warning(
                    "Could not delete expired MP3 %s: %s",
                    audio_file,
                    exc,
                )
                continue

            deleted_files.append(audio_file)
            archive_removed = remove_from_downloaded_url_archive(
                self.downloaded_urls_file,
                source_url,
                self.logger,
            )
            if archive_removed:
                self._downloaded_urls.discard(normalize_youtube_url(source_url))
            self.logger.info("Deleted expired MP3: %s", audio_file)
            self._record_activity(f"Deleted expired MP3: {audio_file.name}")

        return deleted_files

    def _run_retention_cleanup(self, retention_dirs: set[Path]) -> None:
        """Run best-effort retention cleanup after a download cycle."""
        try:
            deleted_files = self._delete_expired_audio_files(
                retention_dirs=retention_dirs,
            )
        except Exception as exc:
            self.logger.warning("Retention cleanup failed: %s", exc)
            return

        if deleted_files:
            self._record_activity(
                f"Retention cleanup deleted {len(deleted_files)} MP3(s)"
            )

    def _check_ytdlp(self) -> bool:
        """Return whether the ``yt-dlp`` command is available."""
        try:
            result = subprocess.run(
                ["yt-dlp", "--version"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                self.logger.info("yt-dlp version: %s", result.stdout.strip())
                return True
            return False
        except FileNotFoundError:
            return False

    def _work_dir_for_final_output_dir(self, final_output_dir: Path) -> Path:
        """Map a library folder to the matching scratch folder."""
        if not self._uses_separate_intermediate_dir():
            return final_output_dir

        try:
            relative_path = final_output_dir.relative_to(self.downloads_dir)
        except ValueError:
            return self.intermediate_dir / final_output_dir.name

        return self.intermediate_dir / relative_path

    def _run_ytdlp(
        self,
        url: str,
        cookies_file: Path | None,
        work_dir: Path | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], list[Path]]:
        """Run ``yt-dlp`` for one URL and return changed MP3 files in the work tree."""
        before_snapshot = self._snapshot_downloaded_audio()
        target_work_dir = work_dir or (
            self.intermediate_dir / FALLBACK_SINGLE_DOWNLOAD_FOLDER
        )
        target_work_dir.mkdir(parents=True, exist_ok=True)
        command = [
            "yt-dlp",
            "--paths",
            f"temp:{target_work_dir}",
            "--extract-audio",
            "--audio-format",
            "mp3",
            "--audio-quality",
            "0",
            "--no-mtime",
            "--embed-thumbnail",
            "--add-metadata",
            "--output",
            str(target_work_dir / YTDLP_OUTPUT_FILENAME_TEMPLATE),
        ]

        if is_youtube_url(url):
            command.extend(["--sponsorblock-remove", "sponsor,selfpromo"])
        else:
            command.append("--no-playlist")

        if cookies_file:
            command.extend(["--cookies", str(cookies_file)])

        command.extend(["--", url])

        # A successful return code is not enough, so snapshot MP3 state before
        # and after the subprocess and return only the files that changed.
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        after_snapshot = self._snapshot_downloaded_audio()
        changed_audio_files = self._detect_changed_audio_files(
            before_snapshot,
            after_snapshot,
        )
        return result, changed_audio_files

    def _should_retry_youtube_download_with_cookies(
        self,
        video_url: str,
        result: subprocess.CompletedProcess[str],
        changed_audio_files: list[Path],
        recoverable_audio_files: list[Path],
    ) -> bool:
        """Return whether a failed plain YouTube attempt should try cookies.

        ``yt-dlp`` cookies are sensitive browser credentials. When
        ``always_use_cookies`` is enabled, the first attempt already spent them.
        Otherwise a retry is useful only when the URL is YouTube, a cookie file
        is configured, and the first attempt either returned a non-zero exit code
        or produced no changed/recoverable MP3 file.
        """
        if self.always_use_cookies:
            return False
        if not is_youtube_url(video_url):
            return False
        if self.cookies_file is None:
            return False
        if result.returncode != 0:
            return True
        if changed_audio_files:
            return False
        return not recoverable_audio_files

    def _find_recoverable_existing_audio(
        self,
        before_snapshot: AudioSnapshot,
        after_snapshot: AudioSnapshot,
    ) -> list[Path]:
        """Find an existing MP3 that can be stamped after a zero-delta success.

        If a prior run created the MP3 but failed while stamping metadata,
        ``yt-dlp`` can later report success without changing the file. With no
        reliable filename in stdout across all extractors, the conservative
        recovery case is exactly one MP3 in the output directory.
        """
        if before_snapshot.files != after_snapshot.files:
            return []

        existing_audio_files = sorted(after_snapshot.files)
        if len(existing_audio_files) != 1:
            return []

        return existing_audio_files

    def _download_video(
        self,
        video_url: str,
        index: int,
        total: int,
        use_archive: bool,
        final_output_dir: Path | None = None,
    ) -> tuple[str, bool]:
        """Download one concrete media URL and update queue/archive state."""
        normalized_url = normalize_youtube_url(video_url)
        target_final_output_dir = final_output_dir or (
            self.downloads_dir / FALLBACK_SINGLE_DOWNLOAD_FOLDER
        )
        target_work_dir = self._work_dir_for_final_output_dir(target_final_output_dir)
        # Refresh archive state because another process may have updated the file.
        self._downloaded_urls = self._load_downloaded_urls()

        if use_archive:
            with locked_downloaded_url_archive(self.downloaded_urls_file) as archive:
                if archive.contains(normalized_url):
                    self._downloaded_urls.add(normalized_url)
                    self.logger.info("Already downloaded: %s", normalized_url)
                    return normalized_url, True

                result_url, success = self._download_video_unlocked(
                    normalized_url,
                    index,
                    total,
                    target_final_output_dir,
                    target_work_dir,
                )
                if success:
                    archive.append_success(normalized_url)
                    self._downloaded_urls.add(normalized_url)
                return result_url, success

        return self._download_video_unlocked(
            normalized_url,
            index,
            total,
            target_final_output_dir,
            target_work_dir,
        )

    def _download_video_unlocked(
        self,
        video_url: str,
        index: int,
        total: int,
        final_output_dir: Path,
        work_dir: Path,
    ) -> tuple[str, bool]:
        """Run the actual subprocess work once archive policy is settled."""
        self.logger.info("[%s/%s] Downloading: %s", index, total, video_url)

        if is_youtube_short_url(video_url):
            self.logger.info("Skipping YouTube Short: %s", video_url)
            remove_video_url_from_file(self.urls_file, video_url, self.logger)
            remove_from_bypass_age_file(
                self.bypass_age_check_file,
                video_url,
                self.logger,
            )
            self._record_activity(f"Skipped Short: {video_url}")
            return video_url, True

        before_snapshot = self._snapshot_downloaded_audio()
        first_attempt_cookies = None
        if (
            is_youtube_url(video_url)
            and self.cookies_file is not None
            and self.always_use_cookies
        ):
            first_attempt_cookies = self.cookies_file

        try:
            result, changed_audio_files = self._run_ytdlp(
                video_url,
                first_attempt_cookies,
                work_dir,
            )
            after_snapshot = self._snapshot_downloaded_audio()

            recoverable_audio_files = []
            if result.returncode == 0 and not changed_audio_files:
                recoverable_audio_files = self._find_recoverable_existing_audio(
                    before_snapshot,
                    after_snapshot,
                )

            if self._should_retry_youtube_download_with_cookies(
                video_url,
                result,
                changed_audio_files,
                recoverable_audio_files,
            ):
                self.logger.info(
                    "Plain YouTube download failed; retrying with cookies file: %s",
                    self.cookies_file,
                )
                before_snapshot = self._snapshot_downloaded_audio()
                result, changed_audio_files = self._run_ytdlp(
                    video_url,
                    self.cookies_file,
                    work_dir,
                )
                after_snapshot = self._snapshot_downloaded_audio()
        except subprocess.TimeoutExpired:
            self.logger.error("Timeout downloading: %s", video_url)
            self._record_activity(f"Failed: {video_url}")
            self._finalize_intermediate_cleanup(work_dir)
            return video_url, False
        except Exception as exc:
            self.logger.error("Error downloading %s: %s", video_url, exc)
            self._record_activity(f"Failed: {video_url}")
            self._finalize_intermediate_cleanup(work_dir)
            return video_url, False

        if result.returncode != 0:
            error_text = result.stderr.strip() or result.stdout.strip()
            self.logger.error("Failed: %s", video_url)
            if error_text:
                self.logger.error("yt-dlp error: %s", error_text)
            self._record_activity(f"Failed: {video_url}")
            self._finalize_intermediate_cleanup(work_dir)
            return video_url, False

        audio_files_to_stamp = changed_audio_files
        if not audio_files_to_stamp:
            audio_files_to_stamp = self._find_recoverable_existing_audio(
                before_snapshot,
                after_snapshot,
            )

        if not audio_files_to_stamp:
            self.logger.error("No MP3 file changed for successful run: %s", video_url)
            self._record_activity(f"Failed: {video_url}")
            self._finalize_intermediate_cleanup(work_dir)
            return video_url, False

        try:
            self._stamp_audio_files_with_download_time(
                audio_files_to_stamp,
                video_url,
            )
        except Exception as exc:
            self.logger.error("Metadata stamping failed for %s: %s", video_url, exc)
            self._record_activity(f"Failed: {video_url}")
            self._finalize_intermediate_cleanup(
                work_dir,
                preserve_mp3_files=audio_files_to_stamp,
            )
            return video_url, False

        try:
            published_audio_files = self._publish_audio_files_to_output_dir(
                audio_files_to_stamp,
                final_output_dir,
            )
        except Exception as exc:
            self.logger.error("Could not publish MP3 for %s: %s", video_url, exc)
            self._record_activity(f"Failed: {video_url}")
            self._finalize_intermediate_cleanup(work_dir)
            return video_url, False

        self._finalize_intermediate_cleanup(work_dir)

        remove_video_url_from_file(self.urls_file, video_url, self.logger)
        remove_from_bypass_age_file(
            self.bypass_age_check_file,
            video_url,
            self.logger,
        )

        downloaded_name = published_audio_files[-1].name
        self.logger.info("Downloaded: %s", downloaded_name)
        self._record_activity(f"Downloaded: {downloaded_name}")
        return video_url, True

    def _youtube_video_is_too_new(
        self,
        url: str,
        bypass_urls: set[str],
    ) -> bool:
        """Return whether a direct YouTube URL should wait for age gating."""
        normalized_url = normalize_youtube_url(url)
        if normalized_url in bypass_urls:
            return False

        metadata = get_video_metadata(
            url,
            self.logger,
            self.cookies_file,
            self.always_use_cookies,
        )
        if metadata is None:
            self.logger.info("Allowed video with unknown age: %s", url)
            return False

        timestamp_raw, upload_date = metadata
        age_check = is_old_enough(
            timestamp_raw,
            upload_date,
            self.min_channel_video_age_hours,
        )
        # Unknown or satisfied age checks proceed; only a known "too new" result waits.
        if age_check is None:
            self.logger.info("Allowed video with unknown age: %s", url)
            return False
        if age_check:
            return False

        self.logger.info(
            "Skipping too-new YouTube video until it is at least %s hours old: %s",
            self.min_channel_video_age_hours,
            url,
        )
        self._record_activity(f"Waiting for age gate: {url}")
        return True

    def _expand_queue_url(self, url: str) -> list[DownloadTarget]:
        """Expand one queue entry into concrete download targets."""
        output_dir = self._download_output_dir_for_source(url)
        if is_channel_or_playlist(url):
            video_urls = expand_channel_or_playlist(
                url,
                self.channel_count,
                self.min_channel_video_age_hours,
                self.logger,
                self.cookies_file,
                self.always_use_cookies,
            )
            return [
                DownloadTarget(
                    video_url=video_url, output_dir=output_dir, use_archive=True
                )
                for video_url in video_urls
            ]

        return [
            DownloadTarget(
                video_url=normalize_youtube_url(url),
                output_dir=output_dir,
                use_archive=False,
            )
        ]

    def download_all(self) -> tuple[int, int]:
        """Process every valid queue entry once.

        Returns
        -------
        tuple[int, int]
            ``(successful, failed)`` counts for concrete videos attempted or
            skipped as completed.
        """
        urls = read_urls_file(self.urls_file, self.logger)
        if not urls:
            self.logger.info("No URLs to process.")
            return 0, 0

        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        self.intermediate_dir.mkdir(parents=True, exist_ok=True)
        bypass_urls = load_bypass_age_urls(self.bypass_age_check_file, self.logger)
        retention_dirs = self._retention_channel_output_dirs(urls)
        download_targets: list[DownloadTarget] = []

        for url in urls:
            expanded_targets = self._expand_queue_url(url)
            for target in expanded_targets:
                if (
                    not target.use_archive
                    and is_youtube_url(target.video_url)
                    and self._youtube_video_is_too_new(target.video_url, bypass_urls)
                ):
                    continue
                download_targets.append(target)

        total = len(download_targets)
        successful = 0
        failed = 0

        for index, target in enumerate(download_targets, 1):
            _, success = self._download_video(
                target.video_url,
                index,
                total,
                target.use_archive,
                target.output_dir,
            )
            if success:
                successful += 1
            else:
                failed += 1

            if index < total and self.delay_seconds > 0:
                time.sleep(self.delay_seconds)

        self._record_activity(f"Run finished: {successful} successful, {failed} failed")
        self._run_retention_cleanup(retention_dirs)
        return successful, failed

    def download_single_queue_url(self, url: str) -> tuple[int, int]:
        """Process exactly one queued direct media URL.

        Returns
        -------
        tuple[int, int]
            ``(successful, failed)`` counts matching ``download_all()``.
        """
        normalized_url = normalize_youtube_url(url.strip())
        if is_channel_or_playlist(normalized_url):
            self.logger.info(
                "Single-URL immediate downloads require a video URL: %s",
                normalized_url,
            )
            return 0, 0

        bypass_urls = load_bypass_age_urls(self.bypass_age_check_file, self.logger)
        if is_youtube_url(normalized_url) and self._youtube_video_is_too_new(
            normalized_url, bypass_urls
        ):
            return 0, 0

        current_queue_urls = read_urls_file(self.urls_file, self.logger)
        retention_dirs = self._retention_channel_output_dirs(current_queue_urls)
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        self.intermediate_dir.mkdir(parents=True, exist_ok=True)
        output_dir = self._download_output_dir_for_source(normalized_url)
        _, success = self._download_video(
            normalized_url,
            index=1,
            total=1,
            use_archive=False,
            final_output_dir=output_dir,
        )
        self._run_retention_cleanup(retention_dirs)
        return (1, 0) if success else (0, 1)

    def show_stats(self, successful: int, failed: int) -> None:
        """Log a short run summary."""
        self.logger.info("")
        self.logger.info("=" * 40)
        self.logger.info("Download Summary")
        self.logger.info("=" * 40)
        self.logger.info("Successful: %s", successful)
        self.logger.info("Failed: %s", failed)
        self.logger.info("Downloads saved to: %s", self.downloads_dir)
