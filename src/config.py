"""Load runtime paths and settings from ``config.ini`` and environment variables."""

from __future__ import annotations

import configparser
import math
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CHANNEL_VIDEO_COUNT = 2
DEFAULT_MIN_CHANNEL_VIDEO_AGE_HOURS = 24
DEFAULT_DELAY_SECONDS = 2.0
DEFAULT_RETENTION_DAYS = 30
# Time limit for one yt-dlp attempt, including download, conversion, SponsorBlock,
# and thumbnail work. Long episodes on a slow connection need a generous limit.
DEFAULT_DOWNLOAD_TIMEOUT_SECONDS = 3600
# A limit below one minute is unlikely to finish a real download.
MINIMUM_DOWNLOAD_TIMEOUT_SECONDS = 60
# Which YouTube player API yt-dlp asks for stream URLs. Most clients now hand
# back URLs that need a "GVS PO Token" (a proof-of-origin token issued by
# YouTube's own web player); fetching those URLs without one returns
# HTTP 403 Forbidden. `web_embedded` still serves usable URLs without a token.
# An empty value lets yt-dlp pick, which is what fails today.
DEFAULT_YOUTUBE_PLAYER_CLIENT = "web_embedded"
# Run every yt-dlp attempt with `-v`. Off by default because retry attempts
# are already verbose, so a download that actually breaks logs its full
# extractor trail without this. Turn it on to inspect a run that succeeds
# but produces the wrong result.
DEFAULT_YTDLP_VERBOSE = False


class ConfigError(ValueError):
    """Raised when ``config.ini`` contains an invalid runtime setting."""


@dataclass(frozen=True)
class PodcastConfig:
    """Concrete paths and settings after config.ini and env overrides are applied."""

    urls_file: Path
    output_dir: Path
    intermediate_dir: Path
    channel_count: int
    log_file: Path
    downloaded_urls_file: Path
    min_channel_video_age_hours: int
    delay_seconds: float
    retention_days: int
    download_timeout_seconds: int
    trust_x_forwarded_for: bool
    cookies_file: Path | None
    always_use_cookies: bool
    bypass_age_check_file: Path
    youtube_player_client: str = DEFAULT_YOUTUBE_PLAYER_CLIENT
    ytdlp_verbose: bool = DEFAULT_YTDLP_VERBOSE


def _require_non_blank(raw_value: str, key: str) -> str:
    """Return a stripped config value or raise when it is blank."""
    stripped_value = raw_value.strip()
    if not stripped_value:
        raise ConfigError(f"{key} must not be blank")
    return stripped_value


def _resolve_path(value: str, project_root: Path) -> Path:
    """Resolve a configured path relative to the project root when needed."""
    path = Path(value).expanduser()
    if not path.is_absolute():
        return project_root / path
    return path


def _get_int(
    section: configparser.SectionProxy | dict[str, str], key: str, default: int
) -> int:
    """Parse an integer config value and raise on bad input."""
    raw_value = section.get(key, str(default))
    try:
        value = int(raw_value)
    except ValueError:
        raise ConfigError(f"{key} must be an integer") from None

    return value


def _require_minimum_int(value: int, key: str, minimum: int) -> int:
    """Validate that an integer setting is not below its accepted minimum."""
    if value < minimum:
        raise ConfigError(f"{key} must be at least {minimum}")
    return value


def _get_float(
    section: configparser.SectionProxy | dict[str, str],
    key: str,
    default: float,
) -> float:
    """Parse a float config value and raise on bad input."""
    raw_value = section.get(key, str(default))
    try:
        value = float(raw_value)
    except ValueError:
        raise ConfigError(f"{key} must be a number") from None

    return value


def _require_minimum_float(value: float, key: str, minimum: float) -> float:
    """Validate that a floating-point setting is not below its accepted minimum."""
    if not math.isfinite(value):
        raise ConfigError(f"{key} must be a finite number")
    if value < minimum:
        minimum_text = str(int(minimum)) if minimum.is_integer() else str(minimum)
        raise ConfigError(f"{key} must be at least {minimum_text}")
    return value


def _get_bool(
    parser: configparser.ConfigParser,
    section_name: str,
    key: str,
    default: bool,
) -> bool:
    """Parse a boolean config value and fall back to the default on bad input.

    Takes the full parser (unlike _get_int/_get_float) because configparser's
    getboolean() handles 'yes/no/on/off/true/false' and requires the parser object.
    """
    try:
        return parser.getboolean(section_name, key, fallback=default)
    except ValueError:
        return default


def _get_path(
    section: configparser.SectionProxy | dict[str, str],
    key: str,
    default: str,
    project_root: Path,
) -> Path:
    """Resolve a required path setting after rejecting blank configured values."""
    raw_value = section.get(key, default)
    value = _require_non_blank(raw_value, key)
    return _resolve_path(value, project_root)


def load_config(config_path: Path, project_root: Path) -> PodcastConfig:
    """Load ``config.ini`` and apply environment overrides and defaults."""
    parser = configparser.ConfigParser()
    parser.read(config_path)
    section = parser["podcast"] if "podcast" in parser else {}

    urls_file = _get_path(section, "urls_file", "urls.txt", project_root)
    # Docker can put downloads on a separate mount, so let the environment win.
    if "PODCAST_DOWNLOAD_DIR" in os.environ:
        env_download_dir = os.environ.get("PODCAST_DOWNLOAD_DIR", "")
        output_dir = _resolve_path(
            _require_non_blank(env_download_dir, "PODCAST_DOWNLOAD_DIR"),
            project_root,
        )
    else:
        output_dir = _get_path(section, "output_dir", "downloads", project_root)

    if "PODCAST_INTERMEDIATE_DIR" in os.environ:
        env_intermediate_dir = os.environ.get("PODCAST_INTERMEDIATE_DIR", "")
        intermediate_dir = _resolve_path(
            _require_non_blank(env_intermediate_dir, "PODCAST_INTERMEDIATE_DIR"),
            project_root,
        )
    else:
        intermediate_dir = _get_path(
            section,
            "intermediate_dir",
            "download_work",
            project_root,
        )

    channel_count = _require_minimum_int(
        _get_int(section, "channel_count", DEFAULT_CHANNEL_VIDEO_COUNT),
        "channel_count",
        1,
    )

    log_file = _get_path(section, "log_file", "download.log", project_root)
    downloaded_urls_file = _get_path(
        section,
        "downloaded_urls_file",
        "downloaded_urls.txt",
        project_root,
    )

    min_channel_video_age_hours = _require_minimum_int(
        _get_int(
            section,
            "min_channel_video_age_hours",
            DEFAULT_MIN_CHANNEL_VIDEO_AGE_HOURS,
        ),
        "min_channel_video_age_hours",
        0,
    )

    delay_seconds = _require_minimum_float(
        _get_float(section, "delay_seconds", DEFAULT_DELAY_SECONDS),
        "delay_seconds",
        0.0,
    )
    retention_days = _require_minimum_int(
        _get_int(section, "retention_days", DEFAULT_RETENTION_DAYS),
        "retention_days",
        1,
    )
    download_timeout_seconds = _require_minimum_int(
        _get_int(
            section,
            "download_timeout_seconds",
            DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
        ),
        "download_timeout_seconds",
        MINIMUM_DOWNLOAD_TIMEOUT_SECONDS,
    )
    trust_x_forwarded_for = _get_bool(
        parser,
        "podcast",
        "trust_x_forwarded_for",
        False,
    )

    # Cookies are optional. ``always_use_cookies`` chooses which mode comes
    # first; the other mode is tried once if the first attempt fails.
    cookies_file: Path | None = None
    if "cookies_file" in section:
        explicit_cookies = _require_non_blank(
            section.get("cookies_file", ""), "cookies_file"
        )
        candidate = _resolve_path(explicit_cookies, project_root)
        # Preserve an explicit path even before the file exists. The web UI can
        # then create that exact file, and later downloader processes use it.
        cookies_file = candidate
    else:
        auto_candidate = project_root / "cookies.txt"
        if auto_candidate.is_file():
            cookies_file = auto_candidate

    always_use_cookies = _get_bool(
        parser,
        "podcast",
        "always_use_cookies",
        True,
    )

    bypass_age_check_file = _get_path(
        section,
        "bypass_age_check_file",
        "bypass_age_check_urls.txt",
        project_root,
    )

    youtube_player_client = section.get(
        "youtube_player_client",
        DEFAULT_YOUTUBE_PLAYER_CLIENT,
    ).strip()

    ytdlp_verbose = _get_bool(
        parser,
        "podcast",
        "ytdlp_verbose",
        DEFAULT_YTDLP_VERBOSE,
    )

    return PodcastConfig(
        urls_file=urls_file,
        output_dir=output_dir,
        intermediate_dir=intermediate_dir,
        channel_count=channel_count,
        log_file=log_file,
        downloaded_urls_file=downloaded_urls_file,
        min_channel_video_age_hours=min_channel_video_age_hours,
        delay_seconds=delay_seconds,
        retention_days=retention_days,
        download_timeout_seconds=download_timeout_seconds,
        trust_x_forwarded_for=trust_x_forwarded_for,
        cookies_file=cookies_file,
        always_use_cookies=always_use_cookies,
        bypass_age_check_file=bypass_age_check_file,
        youtube_player_client=youtube_player_client,
        ytdlp_verbose=ytdlp_verbose,
    )
