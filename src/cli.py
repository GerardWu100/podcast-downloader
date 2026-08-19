"""Add media URLs to the queue and run downloads from the command line."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .config import DEFAULT_CHANNEL_VIDEO_COUNT, ConfigError, load_config
from .downloads.service import PodcastDownloadService
from .media.urls import is_supported_media_url
from .media.youtube import (
    is_channel_or_playlist,
    is_youtube_playlist,
    is_youtube_url,
    normalize_youtube_url,
)
from .notifications.apprise_client import AppriseNotifier
from .state.bypass_store import BypassStore
from .state.notification_store import (
    NotificationStore,
    notification_settings_file_for,
)
from .state.queue_store import QueueStore

_logger = logging.getLogger("cli")


class Colors:
    """ANSI color codes used by command-line status output."""

    RED = "\033[0;31m"
    BLUE = "\033[0;34m"
    NC = "\033[0m"


def _positive_int(raw_value: str) -> int:
    """Parse a command-line integer that must be at least one."""
    value = int(raw_value)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def _mark_youtube_bypass_urls(
    urls: list[str],
    bypass_age_check_file: Path,
) -> None:
    """Record one-use exceptions to the waiting period for YouTube videos.

    Channels, playlists, and non-YouTube URLs are ignored because the bypass
    file only affects direct YouTube videos on the next downloader run.

    Parameters
    ----------
    urls:
        Candidate queue URLs supplied through command-line arguments or stdin.
    bypass_age_check_file:
        One-shot bypass file updated for eligible direct YouTube videos.
    """
    bypass_store = BypassStore(bypass_age_check_file, _logger)

    # Only direct YouTube videos use this one-use waiting-period exception.
    for raw_url in urls:
        if not is_supported_media_url(raw_url):
            continue
        if is_channel_or_playlist(raw_url):
            continue
        if not is_youtube_url(raw_url):
            continue
        bypass_store.add(normalize_youtube_url(raw_url))


def build_parser(
    default_urls_file: Path,
    default_output_dir: Path,
    default_channel_count: int,
) -> argparse.ArgumentParser:
    """Build the command-line parser for queue edits and downloads."""
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
        type=_positive_int,
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
    """Run one queue-update or download command from command-line arguments.

    Returns
    -------
    int
        Process exit status: zero after a successful command, otherwise one.
    """
    project_root = Path(__file__).resolve().parents[1]
    # Docker stores state in /data; local runs use the project root.
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
        added = QueueStore(args.file, _logger).append_urls(urls_to_add)
        if added == 0:
            print(f"{Colors.RED}Error: no valid new URLs were added{Colors.NC}")
            return 1
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

    if single_url and is_channel_or_playlist(single_url):
        print(
            f"{Colors.RED}Error: --download-single-url requires one direct media URL{Colors.NC}"
        )
        return 1

    if full_playlist_url and not is_supported_media_url(full_playlist_url):
        print(
            f"{Colors.RED}Error: --download-full-playlist must be a web media URL{Colors.NC}"
        )
        return 1

    if full_playlist_url and not is_youtube_playlist(full_playlist_url):
        print(
            f"{Colors.RED}Error: --download-full-playlist requires a YouTube playlist URL{Colors.NC}"
        )
        return 1

    # Create both folders before yt-dlp starts writing files.
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
        download_timeout_seconds=config.download_timeout_seconds,
        youtube_player_client=config.youtube_player_client,
        ytdlp_verbose=config.ytdlp_verbose,
        notifier=AppriseNotifier(
            NotificationStore(notification_settings_file_for(data_dir)).load(),
            logging.getLogger("notifications"),
        ),
    )

    if not downloader._check_ytdlp():
        print(f"{Colors.RED}Error: yt-dlp not found{Colors.NC}")
        print('Install it with: uv pip install "yt-dlp[default]"')
        return 1

    print()
    print(f"{Colors.BLUE}Podcast Downloader{Colors.NC}")
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
