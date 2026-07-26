"""Command-line interface for queueing URLs and running downloads."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .config import ConfigError, DEFAULT_CHANNEL_VIDEO_COUNT, load_config
from .downloads.service import PodcastDownloadService
from .media.urls import is_supported_media_url
from .media.youtube import (
    is_channel_or_playlist,
    is_youtube_url,
    normalize_youtube_url,
)
from .state.bypass_store import BypassStore
from .state.queue_store import QueueStore

_logger = logging.getLogger("cli")


class Colors:
    """ANSI color codes used by command-line status output."""

    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    BLUE = "\033[0;34m"
    NC = "\033[0m"


def append_urls(urls_file: Path, urls: list[str]) -> int:
    """Append validated URLs through the queue store."""
    return QueueStore(urls_file, _logger).append_urls(urls)


def add_to_bypass_age_file(
    bypass_file: Path,
    url: str,
    logger: logging.Logger,
) -> None:
    """Record one normalized URL in the one-shot bypass store."""
    BypassStore(bypass_file, logger).add(url)


def _mark_youtube_bypass_urls(
    urls: list[str],
    bypass_age_check_file: Path,
) -> None:
    """Record one-shot age-gate bypasses for direct YouTube video URLs.

    Channels, playlists, and non-YouTube URLs are ignored because the bypass
    file only affects direct YouTube videos on the next downloader run.
    """
    for raw_url in urls:
        if not is_supported_media_url(raw_url):
            continue
        if is_channel_or_playlist(raw_url):
            continue
        if not is_youtube_url(raw_url):
            continue
        add_to_bypass_age_file(
            bypass_age_check_file,
            normalize_youtube_url(raw_url),
            _logger,
        )


def build_parser(
    default_urls_file: Path,
    default_output_dir: Path,
    default_channel_count: int,
) -> argparse.ArgumentParser:
    """Build the parser used for queue updates and batch downloads."""
    parser = argparse.ArgumentParser(
        description="Podcast downloader with YouTube SponsorBlock cleanup",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          # Use default urls.txt
  %(prog)s -f my_urls.txt          # Use custom URLs file
  %(prog)s -o ~/Music/podcasts      # Custom output directory
  %(prog)s -n 10                   # Download 10 latest videos from channels
        """,
    )

    parser.add_argument(
        "-f",
        "--file",
        type=Path,
        default=default_urls_file,
        help="URLs file (default: urls.txt)",
    )

    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=default_output_dir,
        help="Output directory (default: downloads)",
    )

    parser.add_argument(
        "-n",
        "--number",
        type=int,
        default=default_channel_count,
        help=(
            f"Number of latest videos from channels (default: {DEFAULT_CHANNEL_VIDEO_COUNT})"
        ),
    )

    parser.add_argument(
        "--add-url",
        action="append",
        default=[],
        help=(
            "Append a URL to the urls file and exit. Can be provided multiple times."
        ),
    )

    parser.add_argument(
        "--add-url-stdin",
        action="store_true",
        help="Read URLs from stdin (one per line), append to urls file, and exit.",
    )

    parser.add_argument(
        "--skip-age-check",
        action="store_true",
        help=(
            "When used with --add-url or --add-url-stdin, mark direct YouTube "
            "video URLs for an age-gate bypass on the next download run."
        ),
    )

    parser.add_argument(
        "--download-single-url",
        default="",
        help=(
            "Consider exactly one direct media URL from the queue. YouTube URLs "
            "still honor the configured age gate unless that URL is marked for bypass."
        ),
    )

    parser.add_argument(
        "--download-full-playlist",
        default="",
        help=(
            "Expand and download every video in one YouTube playlist URL "
            "immediately instead of using the configured channel_count cap."
        ),
    )

    return parser


def main() -> int:
    """Load config, then either add URLs or run one download pass."""
    project_root = Path(__file__).resolve().parents[1]
    # Docker mounts state in /data; local runs fall back to the project root.
    data_dir = Path(os.environ.get("PODCAST_DATA_DIR", str(project_root)))
    try:
        config = load_config(data_dir / "config.ini", data_dir)
    except ConfigError as exc:
        print(f"{Colors.RED}Error: {exc}{Colors.NC}")
        return 1

    parser = build_parser(
        default_urls_file=config.urls_file,
        default_output_dir=config.output_dir,
        default_channel_count=config.channel_count,
    )
    args = parser.parse_args()

    urls_to_add = list(args.add_url)
    if args.add_url_stdin:
        stdin_urls = [line.strip() for line in sys.stdin if line.strip()]
        urls_to_add.extend(stdin_urls)

    if urls_to_add:
        added = append_urls(args.file, urls_to_add)
        if args.skip_age_check:
            _mark_youtube_bypass_urls(urls_to_add, config.bypass_age_check_file)
        print(f"Added {added} URL(s) to {args.file}")
        return 0

    single_url = args.download_single_url.strip()
    full_playlist_url = args.download_full_playlist.strip()
    if single_url and full_playlist_url:
        print(
            f"{Colors.RED}Error: use only one of --download-single-url or "
            f"--download-full-playlist{Colors.NC}"
        )
        return 1

    if single_url and not is_supported_media_url(single_url):
        print(
            f"{Colors.RED}Error: --download-single-url must be a web media URL{Colors.NC}"
        )
        return 1

    if full_playlist_url and not is_supported_media_url(full_playlist_url):
        print(
            f"{Colors.RED}Error: --download-full-playlist must be a web media URL{Colors.NC}"
        )
        return 1

    # yt-dlp needs the work and library folders to exist before it starts writing files.
    args.output.mkdir(parents=True, exist_ok=True)
    config.intermediate_dir.mkdir(parents=True, exist_ok=True)

    downloader = PodcastDownloadService(
        urls_file=args.file,
        downloads_dir=args.output,
        intermediate_dir=config.intermediate_dir,
        channel_count=args.number,
        log_file=config.log_file,
        downloaded_urls_file=config.downloaded_urls_file,
        min_channel_video_age_hours=config.min_channel_video_age_hours,
        delay_seconds=config.delay_seconds,
        retention_days=config.retention_days,
        cookies_file=config.cookies_file,
        always_use_cookies=config.always_use_cookies,
        bypass_age_check_file=config.bypass_age_check_file,
    )

    if not downloader._check_ytdlp():
        print(f"{Colors.RED}Error: yt-dlp not found{Colors.NC}")
        print("Please install: uv add yt-dlp")
        return 1

    print()
    print(f"{Colors.BLUE}🎵 Podcast Downloader 🎵{Colors.NC}")
    print(f"{Colors.BLUE}={'=' * 35}{Colors.NC}")
    print()

    if single_url:
        successful, failed = downloader.download_single_queue_url(single_url)
    elif full_playlist_url:
        successful, failed = downloader.download_full_playlist_now(full_playlist_url)
    else:
        successful, failed = downloader.download_all()

    downloader.show_stats(successful, failed)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
