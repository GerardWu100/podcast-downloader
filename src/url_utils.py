"""Validate, normalize, and expand media URLs used by the downloader."""

from __future__ import annotations

from contextlib import contextmanager
import logging
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator
from urllib.parse import parse_qs, urlparse, urlunparse

from .state.archive_store import ArchiveStore, LockedDownloadedUrlArchive
from .state.bypass_store import BypassStore
from .state.queue_store import QueueStore


YTDLP_MISSING_VALUE_PLACEHOLDERS = {"", "NA", "N/A", "None", "none", "null"}
YOUTUBE_CHANNEL_CONTENT_TABS = {"streams", "videos"}
YOUTUBE_CHANNEL_ID_PATTERN = re.compile(r"^UC[\w-]{20,}$")
YTDLP_METADATA_TIMEOUT_SECONDS = 30
FULL_PLAYLIST_EXPANSION_TIMEOUT_SECONDS = 300


def _normalized_hostname(url: str) -> str:
    """Return the lower-case hostname with any port removed."""
    try:
        parsed = urlparse(url)
    except Exception:
        return ""

    return (parsed.hostname or "").lower()


def is_youtube_url(url: str) -> bool:
    """Return ``True`` when the URL points at a supported YouTube host."""
    hostname = _normalized_hostname(url)
    return hostname in {
        "www.youtube.com",
        "youtube.com",
        "m.youtube.com",
        "youtu.be",
    }


def is_supported_media_url(url: str) -> bool:
    """Return ``True`` for web URLs that ``yt-dlp`` can attempt to download.

    The downloader still treats YouTube specially for channel/playlist
    expansion, URL normalization, age checks, and SponsorBlock. Non-YouTube
    URLs are accepted only as direct media URLs and are passed to ``yt-dlp``
    with ``--no-playlist`` during the download step.
    """
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return False

    if parsed.scheme not in {"http", "https"}:
        return False

    return bool(parsed.netloc)


def normalize_youtube_url(url: str) -> str:
    """Normalize a YouTube video URL to the canonical watch format.

    YouTube exposes completed livestreams through ``/live/VIDEO_ID`` as well as
    the normal ``/watch?v=VIDEO_ID`` route. Both routes refer to the same media
    item, so they must share one queue identity. Leaves channel/playlist URLs
    as-is.
    """
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()

    if hostname == "youtu.be":
        video_id = parsed.path.lstrip("/")
        return f"https://www.youtube.com/watch?v={video_id}" if video_id else url

    if hostname in {
        "www.youtube.com",
        "youtube.com",
        "m.youtube.com",
    }:
        if parsed.path == "/watch":
            query = parse_qs(parsed.query)
            video_id = query.get("v", [""])[0]
            return f"https://www.youtube.com/watch?v={video_id}" if video_id else url
        if parsed.path.startswith("/live/"):
            path_parts = [part for part in parsed.path.split("/") if part]
            video_id = path_parts[1] if len(path_parts) > 1 else ""
            return f"https://www.youtube.com/watch?v={video_id}" if video_id else url

    return url


def is_youtube_playlist(url: str) -> bool:
    """Return ``True`` for dedicated YouTube playlist URLs."""
    if not is_youtube_url(url):
        return False

    return "/playlist?" in url.rstrip("/")


def is_channel_or_playlist(url: str) -> bool:
    """Return ``True`` for YouTube channel, user, handle, or playlist URLs."""
    if not is_youtube_url(url):
        return False

    url_clean = url.rstrip("/")
    return any(
        x in url_clean for x in ["/@", "/c/", "/channel/", "/user/", "/playlist?"]
    )


def is_youtube_short_url(url: str) -> bool:
    """Return ``True`` for YouTube Shorts URLs."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    return is_youtube_url(url) and "/shorts/" in parsed.path


def looks_like_youtube_channel_id(name: str) -> bool:
    """Return whether a string looks like an opaque YouTube channel ID."""
    return bool(YOUTUBE_CHANNEL_ID_PATTERN.match(name.strip()))


def _youtube_cookies_for_first_attempt(
    url: str,
    cookies_file: Path | None,
    always_use_cookies: bool,
) -> Path | None:
    """Return the cookie file to pass on the first ``yt-dlp`` attempt for one URL.

    Cookies are YouTube-only. When ``always_use_cookies`` is false, the first
    attempt runs without cookies so browser credentials are spent only on retry.
    """
    if cookies_file is None:
        return None
    if not is_youtube_url(url):
        return None
    if always_use_cookies:
        return cookies_file
    return None


def _youtube_cookies_for_retry_attempt(
    url: str,
    cookies_file: Path | None,
    always_use_cookies: bool,
    first_attempt_cookies: Path | None,
) -> Path | None:
    """Return cookies for the alternate retry after a failed first YouTube attempt.

    When ``always_use_cookies`` is true, the first attempt used cookies and the
    retry runs plain. When false, the first attempt was plain and the retry uses
    the configured cookie file.
    """
    if cookies_file is None:
        return None
    if not is_youtube_url(url):
        return None
    if always_use_cookies:
        return None
    if first_attempt_cookies is None:
        return cookies_file
    return None


def _should_retry_youtube_with_alternate_cookies(
    url: str,
    cookies_file: Path | None,
    always_use_cookies: bool,
    *,
    first_attempt_cookies: Path | None,
    succeeded: bool,
) -> bool:
    """Return whether a failed YouTube attempt should try the alternate cookie mode."""
    if succeeded:
        return False
    if not is_youtube_url(url):
        return False
    if cookies_file is None:
        return False
    if always_use_cookies:
        return first_attempt_cookies is not None
    return first_attempt_cookies is None


def _fetch_ytdlp_print_line(
    url: str,
    print_template: str,
    logger: logging.Logger,
    cookies_file: Path | None = None,
    always_use_cookies: bool = False,
) -> str | None:
    """Return the first ``yt-dlp --print`` line for one URL without downloading."""

    def run_once(cookies_for_attempt: Path | None) -> str | None:
        command = [
            "yt-dlp",
            "--flat-playlist",
            "--playlist-end",
            "1",
            "--print",
            print_template,
            "--sleep-requests",
            "0.5",
        ]
        if cookies_for_attempt:
            command.extend(["--cookies", str(cookies_for_attempt)])
        command.extend(["--", url])

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=YTDLP_METADATA_TIMEOUT_SECONDS,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().splitlines()[0]

            logger.warning(
                "yt-dlp metadata print failed for %s: %s",
                url,
                result.stderr.strip(),
            )
            return None
        except subprocess.TimeoutExpired:
            logger.warning("yt-dlp metadata print timed out for %s", url)
            return None
        except Exception as exc:
            logger.warning("yt-dlp metadata print error for %s: %s", url, exc)
            return None

    first_attempt_cookies = _youtube_cookies_for_first_attempt(
        url,
        cookies_file,
        always_use_cookies,
    )
    metadata_line = run_once(first_attempt_cookies)
    if metadata_line is not None:
        return metadata_line

    if _should_retry_youtube_with_alternate_cookies(
        url,
        cookies_file,
        always_use_cookies,
        first_attempt_cookies=first_attempt_cookies,
        succeeded=False,
    ):
        retry_cookies = _youtube_cookies_for_retry_attempt(
            url,
            cookies_file,
            always_use_cookies,
            first_attempt_cookies,
        )
        if always_use_cookies:
            logger.info(
                "Cookie YouTube metadata request failed; retrying without cookies",
            )
        else:
            logger.info(
                "Plain YouTube metadata request failed; retrying with cookies file: %s",
                cookies_file,
            )
        return run_once(retry_cookies)

    return None


def get_youtube_channel_display_name(
    url: str,
    logger: logging.Logger,
    cookies_file: Path | None = None,
    always_use_cookies: bool = False,
) -> str | None:
    """Return a human-readable YouTube channel name for one video or channel URL."""
    metadata_line = _fetch_ytdlp_print_line(
        url,
        "%(channel)s\t%(uploader)s",
        logger,
        cookies_file,
        always_use_cookies,
    )
    if metadata_line is None:
        return None

    parts = metadata_line.split("\t")
    channel_name = parts[0] if parts else ""
    uploader_name = parts[1] if len(parts) > 1 else ""

    if _metadata_value_is_present(channel_name) and not looks_like_youtube_channel_id(
        channel_name,
    ):
        return channel_name.strip()
    if _metadata_value_is_present(uploader_name) and not looks_like_youtube_channel_id(
        uploader_name,
    ):
        return uploader_name.strip()
    return None


def get_youtube_channel_folder_name(
    url: str,
    logger: logging.Logger,
    cookies_file: Path | None = None,
    always_use_cookies: bool = False,
) -> str | None:
    """Return a stable channel folder name, preferring ``@`` handles when present."""
    metadata_line = _fetch_ytdlp_print_line(
        url,
        "%(channel)s\t%(uploader_id)s",
        logger,
        cookies_file,
        always_use_cookies,
    )
    if metadata_line is None:
        return None

    parts = metadata_line.split("\t")
    channel_name = parts[0] if parts else ""
    uploader_id = parts[1] if len(parts) > 1 else ""

    if _metadata_value_is_present(uploader_id) and uploader_id.startswith("@"):
        handle_name = uploader_id[1:].strip()
        if handle_name and not looks_like_youtube_channel_id(handle_name):
            return handle_name
    if _metadata_value_is_present(channel_name) and not looks_like_youtube_channel_id(
        channel_name,
    ):
        return channel_name.strip()
    return None


def get_youtube_playlist_folder_name(
    url: str,
    logger: logging.Logger,
    cookies_file: Path | None = None,
    always_use_cookies: bool = False,
) -> str | None:
    """Return a readable YouTube playlist title for folder naming.

    The value comes from ``yt-dlp`` playlist metadata instead of the ``list=``
    identifier, which is usually an opaque ``PL...`` string. ``None`` means the
    caller should keep its existing URL-derived fallback.
    """
    metadata_line = _fetch_ytdlp_print_line(
        url,
        "%(playlist_title)s",
        logger,
        cookies_file,
        always_use_cookies,
    )
    if metadata_line is None:
        return None

    if not _metadata_value_is_present(metadata_line):
        return None

    playlist_title = metadata_line.strip()
    return playlist_title or None


def _metadata_value_is_present(raw_value: str) -> bool:
    """Return whether a ``yt-dlp`` metadata field contains usable data.

    ``yt-dlp`` uses ``NA`` as its default placeholder when a template field is
    unavailable. Treat those placeholders as missing so callers can fall back to
    another field, such as ``upload_date`` when ``timestamp`` is unavailable.
    """
    normalized_value = raw_value.strip()
    return normalized_value not in YTDLP_MISSING_VALUE_PLACEHOLDERS


def create_sample_urls_file(urls_file: Path, logger: logging.Logger) -> None:
    """Create a starter queue file when ``urls.txt`` is missing."""
    QueueStore(urls_file, logger).create_sample_file()


@contextmanager
def locked_downloaded_url_archive(
    archive_file: Path,
) -> Iterator[LockedDownloadedUrlArchive]:
    """Hold the downloaded URL archive lock for a full check-download-write pass."""
    store = ArchiveStore(archive_file, logging.getLogger("url_utils.archive"))
    with store.locked_transaction() as archive:
        yield archive


def read_urls_file(urls_file: Path, logger: logging.Logger) -> list[str]:
    """Read monitored URLs from disk and ignore comments and blank lines."""
    return QueueStore(urls_file, logger).read_urls()


def load_queue_urls(urls_file: Path, logger: logging.Logger) -> list[str]:
    """Return normalized queue entries from ``urls.txt`` under a shared lock."""
    return QueueStore(urls_file, logger).load_normalized_urls()


def remove_video_url_from_file(
    urls_file: Path,
    video_url: str,
    logger: logging.Logger,
) -> None:
    """Remove one video URL from ``urls.txt`` and leave channels alone."""
    QueueStore(urls_file, logger).remove_video_url(video_url)


def remove_url_from_queue(urls_file: Path, url: str, logger: logging.Logger) -> bool:
    """Remove one normalized URL from ``urls.txt`` under an exclusive lock."""
    return QueueStore(urls_file, logger).remove_url(url)


def load_downloaded_url_archive(
    archive_file: Path,
    logger: logging.Logger,
) -> set[str]:
    """Read normalized archive URLs while holding a shared lock."""
    return ArchiveStore(archive_file, logger).load()


def append_to_downloaded_url_archive(
    archive_file: Path,
    url: str,
    logger: logging.Logger,
) -> bool:
    """Append one normalized URL to the archive under an exclusive lock."""
    return ArchiveStore(archive_file, logger).append(url)


def remove_from_downloaded_url_archive(
    archive_file: Path,
    url: str,
    logger: logging.Logger,
) -> bool:
    """Remove one normalized URL from the archive under an exclusive lock."""
    return ArchiveStore(archive_file, logger).remove(url)


def is_old_enough(
    timestamp_raw: str,
    upload_date: str,
    min_channel_video_age_hours: int,
) -> bool | None:
    """Check whether a video meets the minimum age requirement.

    Returns:
        True if old enough, False if too new, None if age is unknown.
    """
    if min_channel_video_age_hours <= 0:
        return True

    if _metadata_value_is_present(timestamp_raw):
        try:
            timestamp = int(timestamp_raw)
            age_seconds = datetime.now(timezone.utc).timestamp() - timestamp
            return age_seconds >= min_channel_video_age_hours * 3600
        except ValueError:
            pass

    if _metadata_value_is_present(upload_date):
        try:
            upload_day = datetime.strptime(upload_date, "%Y%m%d").date()
            next_day_start = datetime.combine(
                upload_day + timedelta(days=1),
                datetime.min.time(),
                tzinfo=timezone.utc,
            )
            allowed_at = next_day_start + timedelta(
                hours=min_channel_video_age_hours,
            )
            return datetime.now(timezone.utc) >= allowed_at
        except ValueError:
            return None

    return None


def _is_channel_url(url_clean: str) -> bool:
    """Return whether a cleaned YouTube URL points at a channel-like source."""
    return any(marker in url_clean for marker in ["/@", "/c/", "/channel/", "/user/"])


def _channel_identity_part_count(path_parts: list[str]) -> int:
    """Return how many path parts identify a YouTube channel itself.

    YouTube supports several channel URL shapes. Handles use one path part, such
    as ``/@PBDPodcast``. Legacy routes use a route marker plus a name or ID,
    such as ``/c/name``, ``/channel/UC...``, or ``/user/name``. Parts after that
    identity select a channel tab, for example ``videos`` or ``streams``.
    """
    if not path_parts:
        return 0

    first_part = path_parts[0]
    if first_part.startswith("@"):
        return 1

    if first_part in {"c", "channel", "user"} and len(path_parts) >= 2:
        return 2

    return 0


def _channel_tab_expansion_url(url_clean: str) -> str:
    """Return the exact YouTube channel tab URL that should be expanded.

    A bare channel URL can include mixed tab content depending on the extractor
    and YouTube's current page layout. The downloader's safer default is the
    normal uploads tab. An explicit ``streams`` URL is preserved so the queue can
    monitor completed and current livestream entries separately from uploads.
    Unknown channel subpaths are treated like bare channels and redirected to
    ``videos`` because this downloader only supports the videos and streams
    source modes.
    """
    if not is_youtube_url(url_clean):
        return url_clean

    parsed = urlparse(url_clean)
    path_parts = [part for part in parsed.path.split("/") if part]
    identity_part_count = _channel_identity_part_count(path_parts)
    if identity_part_count == 0:
        return url_clean

    channel_identity_parts = path_parts[:identity_part_count]
    tab_part = ""
    if len(path_parts) > identity_part_count:
        tab_part = path_parts[identity_part_count].lower()

    selected_tab = tab_part if tab_part in YOUTUBE_CHANNEL_CONTENT_TABS else "videos"
    normalized_path = "/" + "/".join([*channel_identity_parts, selected_tab])
    normalized_parts = parsed._replace(path=normalized_path, query="", fragment="")
    return urlunparse(normalized_parts)


def _build_expansion_command(
    url_clean: str,
    channel_count: int,
    cookies_file: Path | None,
    *,
    full_playlist: bool = False,
) -> list[str]:
    """Build the ``yt-dlp`` metadata command for a channel or playlist.

    Channels fetch extra entries because Shorts and fresh uploads can be
    filtered out before the service reaches the requested ``channel_count``.
    Playlists use the configured count directly because playlist order is the
    intended source order. When ``full_playlist`` is ``True`` for a playlist
    source, the command omits ``--playlist-end`` so every entry is listed.
    """
    is_channel = _is_channel_url(url_clean)
    expansion_url = _channel_tab_expansion_url(url_clean) if is_channel else url_clean
    fetch_count = channel_count * 6 if is_channel else channel_count
    command = [
        "yt-dlp",
        "--flat-playlist",
        "--extractor-args",
        "youtubetab:approximate_date",
        "--sleep-requests",
        "0.5",
        "--print",
        "%(url)s\t%(timestamp)s\t%(upload_date)s",
    ]

    if cookies_file:
        command.extend(["--cookies", str(cookies_file)])

    if not (full_playlist and not is_channel):
        command.extend(["--playlist-end", str(fetch_count)])

    command.extend(["--", expansion_url])
    return command


def _split_expanded_entry(entry: str) -> tuple[str, str, str]:
    """Split one tab-delimited ``yt-dlp`` metadata line into useful fields."""
    parts = entry.split("\t")
    video_url = parts[0]
    timestamp_raw = parts[1] if len(parts) > 1 else ""
    upload_date = parts[2] if len(parts) > 2 else ""
    return video_url, timestamp_raw, upload_date


def _filter_channel_entries(
    entries: list[str],
    channel_count: int,
    min_channel_video_age_hours: int,
    logger: logging.Logger,
) -> list[str]:
    """Keep the first old-enough non-Shorts channel videos from ``yt-dlp``.

    Unknown ages are allowed because ``yt-dlp`` metadata can be incomplete. A
    known too-new upload is skipped so SponsorBlock has time to collect
    matching segments before the downloader processes it.
    """
    video_urls: list[str] = []
    shorts_count = 0
    too_new_count = 0
    unknown_age_count = 0

    for entry in entries:
        video_url, timestamp_raw, upload_date = _split_expanded_entry(entry)

        if is_youtube_short_url(video_url):
            shorts_count += 1
            continue

        age_check = is_old_enough(
            timestamp_raw,
            upload_date,
            min_channel_video_age_hours,
        )
        if age_check is None:
            unknown_age_count += 1
        elif not age_check:
            too_new_count += 1
            continue

        video_urls.append(video_url)
        if len(video_urls) >= channel_count:
            break

    if shorts_count > 0:
        logger.info("Filtered out %s shorts", shorts_count)
    if too_new_count > 0:
        logger.info(
            "Filtered out %s videos newer than %s hours",
            too_new_count,
            min_channel_video_age_hours,
        )
    if unknown_age_count > 0:
        logger.info("Allowed %s videos with unknown age", unknown_age_count)

    logger.info(
        "Found %s videos (excluding shorts and too-new videos)",
        len(video_urls),
    )
    return video_urls


def _expand_channel_or_playlist_once(
    url_clean: str,
    channel_count: int,
    min_channel_video_age_hours: int,
    logger: logging.Logger,
    cookies_for_attempt: Path | None,
    *,
    full_playlist: bool = False,
) -> list[str] | None:
    """Run one channel/playlist expansion attempt and return video URLs on success."""
    command = _build_expansion_command(
        url_clean,
        channel_count,
        cookies_for_attempt,
        full_playlist=full_playlist,
    )
    expansion_timeout_seconds = (
        FULL_PLAYLIST_EXPANSION_TIMEOUT_SECONDS
        if full_playlist and not _is_channel_url(url_clean)
        else YTDLP_METADATA_TIMEOUT_SECONDS
    )
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=expansion_timeout_seconds,
        check=False,
    )

    if result.returncode != 0:
        logger.error(f"Failed to expand URL: {result.stderr}")
        return None

    all_entries = [line.strip() for line in result.stdout.split("\n") if line.strip()]
    logger.info("Fetched %s entries from channel/playlist", len(all_entries))

    if _is_channel_url(url_clean):
        return _filter_channel_entries(
            all_entries,
            channel_count,
            min_channel_video_age_hours,
            logger,
        )

    # Playlists preserve the flat playlist order and skip only metadata columns
    # that were printed to support channel age filtering. Slice defensively in
    # case an extractor ignores ``--playlist-end``.
    playlist_entries = all_entries if full_playlist else all_entries[:channel_count]
    video_urls = [_split_expanded_entry(entry)[0] for entry in playlist_entries]
    logger.info("Found %s videos", len(video_urls))
    return video_urls


def expand_channel_or_playlist(
    url: str,
    channel_count: int,
    min_channel_video_age_hours: int,
    logger: logging.Logger,
    cookies_file: Path | None = None,
    always_use_cookies: bool = False,
    *,
    full_playlist: bool = False,
) -> list[str]:
    """Expand a channel or playlist into individual video URLs."""
    url_clean = url.rstrip("/")
    logger.info(f"Expanding: {url_clean}")

    try:
        first_attempt_cookies = _youtube_cookies_for_first_attempt(
            url_clean,
            cookies_file,
            always_use_cookies,
        )
        video_urls = _expand_channel_or_playlist_once(
            url_clean,
            channel_count,
            min_channel_video_age_hours,
            logger,
            first_attempt_cookies,
            full_playlist=full_playlist,
        )
        if video_urls is not None:
            return video_urls

        if _should_retry_youtube_with_alternate_cookies(
            url_clean,
            cookies_file,
            always_use_cookies,
            first_attempt_cookies=first_attempt_cookies,
            succeeded=False,
        ):
            retry_cookies = _youtube_cookies_for_retry_attempt(
                url_clean,
                cookies_file,
                always_use_cookies,
                first_attempt_cookies,
            )
            if always_use_cookies:
                logger.info(
                    "Cookie YouTube expansion failed; retrying without cookies",
                )
            else:
                logger.info(
                    "Plain YouTube expansion failed; retrying with cookies file: %s",
                    cookies_file,
                )
            retry_video_urls = _expand_channel_or_playlist_once(
                url_clean,
                channel_count,
                min_channel_video_age_hours,
                logger,
                retry_cookies,
                full_playlist=full_playlist,
            )
            if retry_video_urls is not None:
                return retry_video_urls

        return []

    except subprocess.TimeoutExpired:
        logger.error(f"Timeout expanding URL: {url}")
        return []
    except Exception as exc:
        logger.error(f"Error expanding URL: {exc}")
        return []


def _get_video_metadata_once(
    url: str,
    logger: logging.Logger,
    cookies_for_attempt: Path | None,
) -> tuple[str, str] | None:
    """Run one metadata fetch attempt for a single video URL."""
    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--print",
        "%(timestamp)s\t%(upload_date)s",
        "--sleep-requests",
        "0.5",
    ]
    if cookies_for_attempt:
        cmd.extend(["--cookies", str(cookies_for_attempt)])
    cmd.extend(["--", url])

    result = subprocess.run(
        cmd,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=YTDLP_METADATA_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        first_line = result.stdout.strip().splitlines()[0]
        parts = first_line.split("\t")
        return (parts[0] if parts else "", parts[1] if len(parts) > 1 else "")

    logger.warning("get_video_metadata failed for %s: %s", url, result.stderr)
    return None


def get_video_metadata(
    url: str,
    logger: logging.Logger,
    cookies_file: Path | None = None,
    always_use_cookies: bool = False,
) -> tuple[str, str] | None:
    """Fetch ``(timestamp_raw, upload_date)`` for one video via ``yt-dlp``.

    Uses --flat-playlist to avoid a full download; same approach as expand_channel_or_playlist.
    Returns None if the call fails or times out, so callers can treat unknown age as "allow".
    """
    try:
        first_attempt_cookies = _youtube_cookies_for_first_attempt(
            url,
            cookies_file,
            always_use_cookies,
        )
        metadata = _get_video_metadata_once(url, logger, first_attempt_cookies)
        if metadata is not None:
            return metadata

        if _should_retry_youtube_with_alternate_cookies(
            url,
            cookies_file,
            always_use_cookies,
            first_attempt_cookies=first_attempt_cookies,
            succeeded=False,
        ):
            retry_cookies = _youtube_cookies_for_retry_attempt(
                url,
                cookies_file,
                always_use_cookies,
                first_attempt_cookies,
            )
            if always_use_cookies:
                logger.info(
                    "Cookie YouTube metadata request failed; retrying without cookies",
                )
            else:
                logger.info(
                    "Plain YouTube metadata request failed; retrying with cookies file: %s",
                    cookies_file,
                )
            return _get_video_metadata_once(url, logger, retry_cookies)

        return None
    except subprocess.TimeoutExpired:
        logger.warning("get_video_metadata timed out for %s", url)
        return None
    except Exception as exc:
        logger.warning("get_video_metadata error for %s: %s", url, exc)
        return None


def load_bypass_age_urls(bypass_file: Path, logger: logging.Logger) -> set[str]:
    """Return the URLs that should skip the age check on the next run."""
    return BypassStore(bypass_file, logger).load()


def add_to_bypass_age_file(bypass_file: Path, url: str, logger: logging.Logger) -> None:
    """Append a normalized URL to the bypass-age file if it is not there already."""
    BypassStore(bypass_file, logger).add(url)


def remove_from_bypass_age_file(
    bypass_file: Path, url: str, logger: logging.Logger
) -> None:
    """Remove one normalized URL from the bypass-age file."""
    BypassStore(bypass_file, logger).remove(url)


def append_urls(urls_file: Path, urls: list[str]) -> int:
    """Append normalized URLs to ``urls.txt`` while skipping duplicates.

    Returns the number of URLs added.
    """
    return QueueStore(urls_file, logging.getLogger("url_utils.queue")).append_urls(urls)
