"""Load runtime paths and settings from ``config.toml`` and environment variables.

``config.toml`` holds flat top-level keys, one per setting, such as
``retention_days = 30`` or ``urls_file = "urls.txt"``. Each value must have the
type its setting needs: a whole number, a number, ``true``/``false``, or quoted
text. A wrong type or an unknown key stops startup with an error that names it,
so a typo can never fall back to a default without anyone noticing.
"""

from __future__ import annotations

import math
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CHANNEL_VIDEO_COUNT = 2
DEFAULT_MIN_CHANNEL_VIDEO_AGE_HOURS = 24
DEFAULT_DELAY_SECONDS = 2.0
DEFAULT_RETENTION_DAYS = 30
MINIMUM_RETENTION_DAYS = 1
# Ceiling for the settings page only; ten years is "keep everything".
MAXIMUM_RETENTION_DAYS = 3650
RETENTION_DAYS_KEY = "retention_days"
CONFIG_FILENAME = "config.toml"
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
# Wall-clock schedule for automatic runs: 06:00 local time, every second
# calendar day. `src/schedule.py` turns these two numbers into run instants.
# How many days before the YouTube sign-in cookies expire to start warning
# after a run. Zero turns the warning off; an expired file is always reported.
DEFAULT_COOKIE_EXPIRY_WARNING_DAYS = 14
DEFAULT_SCHEDULED_RUN_HOUR = 6
# Failed attempts after which a video is dropped: a direct URL leaves the
# queue, and a channel or playlist video is no longer tried. Failures that
# point at a YouTube block or a network problem do not count.
DEFAULT_MAX_DOWNLOAD_ATTEMPTS = 2
DEFAULT_SCHEDULED_RUN_INTERVAL_DAYS = 2
FIRST_HOUR_OF_DAY = 0
LAST_HOUR_OF_DAY = 23


class ConfigError(ValueError):
    """Raised when ``config.toml`` contains an invalid runtime setting."""


@dataclass(frozen=True)
class PodcastConfig:
    """Concrete paths and settings after config.toml and env overrides are applied."""

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
    scheduled_run_hour: int = DEFAULT_SCHEDULED_RUN_HOUR
    scheduled_run_interval_days: int = DEFAULT_SCHEDULED_RUN_INTERVAL_DAYS
    cookie_expiry_warning_days: int = DEFAULT_COOKIE_EXPIRY_WARNING_DAYS
    max_download_attempts: int = DEFAULT_MAX_DOWNLOAD_ATTEMPTS


# Every key config.toml may contain. Anything else is a typo, and a typo that
# was silently ignored would leave the default in force without a word.
KNOWN_SETTINGS = frozenset(
    {
        "urls_file",
        "output_dir",
        "intermediate_dir",
        "channel_count",
        "min_channel_video_age_hours",
        "delay_seconds",
        "retention_days",
        "download_timeout_seconds",
        "max_download_attempts",
        "scheduled_run_hour",
        "scheduled_run_interval_days",
        "cookie_expiry_warning_days",
        "log_file",
        "downloaded_urls_file",
        "bypass_age_check_file",
        "cookies_file",
        "youtube_player_client",
        "ytdlp_verbose",
        "always_use_cookies",
        "trust_x_forwarded_for",
    }
)

# config.toml as parsed: setting name -> value of its TOML type.
Settings = dict[str, object]


def read_settings(config_path: Path) -> Settings:
    """Parse ``config.toml`` and reject keys that no setting uses.

    Parameters
    ----------
    config_path:
        Path to ``config.toml``. A missing file gives an empty mapping, so
        every setting takes its default.

    Returns
    -------
    Settings
        Top-level keys mapped to their parsed values.

    Raises
    ------
    ConfigError
        When the file is not valid TOML or holds an unknown key.
    """
    if not config_path.exists():
        return {}
    try:
        with config_path.open("rb") as config_file:
            settings = tomllib.load(config_file)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{config_path.name} could not be parsed: {exc}") from exc

    unknown_keys = sorted(set(settings) - KNOWN_SETTINGS)
    if unknown_keys:
        raise ConfigError(
            f"{config_path.name} has unknown setting(s): {', '.join(unknown_keys)}"
        )
    return settings


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


def _get_int(settings: Settings, key: str, default: int) -> int:
    """Return a whole-number setting, or raise when it has another type."""
    value = settings.get(key, default)
    # bool is a subclass of int in Python, but `true` is not a count.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{key} must be a whole number, such as {default}")
    return value


def _get_float(settings: Settings, key: str, default: float) -> float:
    """Return a numeric setting; whole numbers are accepted too."""
    value = settings.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{key} must be a number, such as {default}")
    return float(value)


def _get_bool(settings: Settings, key: str, default: bool) -> bool:
    """Return a ``true``/``false`` setting, or raise when it has another type."""
    value = settings.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{key} must be true or false, without quotes")
    return value


def _get_text(settings: Settings, key: str, default: str) -> str:
    """Return a quoted-text setting, stripped of surrounding spaces."""
    value = settings.get(key, default)
    if not isinstance(value, str):
        raise ConfigError(f'{key} must be quoted text, such as "{default}"')
    return value.strip()


def _require_minimum_int(value: int, key: str, minimum: int) -> int:
    """Validate that an integer setting is not below its accepted minimum."""
    if value < minimum:
        raise ConfigError(f"{key} must be at least {minimum}")
    return value


def _require_int_in_range(value: int, key: str, minimum: int, maximum: int) -> int:
    """Validate that an integer setting sits inside its accepted range."""
    if not minimum <= value <= maximum:
        raise ConfigError(f"{key} must be between {minimum} and {maximum}")
    return value


def _require_minimum_float(value: float, key: str, minimum: float) -> float:
    """Validate that a floating-point setting is not below its accepted minimum."""
    if not math.isfinite(value):
        raise ConfigError(f"{key} must be a finite number")
    if value < minimum:
        minimum_text = str(int(minimum)) if minimum.is_integer() else str(minimum)
        raise ConfigError(f"{key} must be at least {minimum_text}")
    return value


def _get_path(settings: Settings, key: str, default: str, project_root: Path) -> Path:
    """Resolve a required path setting after rejecting blank configured values."""
    value = _require_non_blank(_get_text(settings, key, default), key)
    return _resolve_path(value, project_root)


def _env_or_setting_path(
    env_name: str, settings: Settings, key: str, default: str, project_root: Path
) -> Path:
    """Return a directory from the environment if set, else from config.toml.

    Docker can put downloads and scratch files on separate mounts, so the
    environment wins over the file.
    """
    if env_name in os.environ:
        return _resolve_path(
            _require_non_blank(os.environ.get(env_name, ""), env_name), project_root
        )
    return _get_path(settings, key, default, project_root)


def load_config(config_path: Path, project_root: Path) -> PodcastConfig:
    """Load ``config.toml`` and apply environment overrides and defaults.

    Parameters
    ----------
    config_path:
        Path to ``config.toml``; a missing file means every default.
    project_root:
        Directory that relative paths in the file are resolved against.

    Returns
    -------
    PodcastConfig
        Validated settings with every path made absolute.

    Raises
    ------
    ConfigError
        On invalid TOML, an unknown key, a value of the wrong type, or a value
        outside its range. The message names the setting.
    """
    settings = read_settings(config_path)

    # Cookies are optional. An explicit cookies_file is kept even before the
    # file exists, so the web UI can create that exact file and later runs use
    # it; without the key, a cookies.txt beside the data is picked up if present.
    cookies_file: Path | None = None
    if "cookies_file" in settings:
        cookies_file = _get_path(settings, "cookies_file", "cookies.txt", project_root)
    elif (project_root / "cookies.txt").is_file():
        cookies_file = project_root / "cookies.txt"

    return PodcastConfig(
        urls_file=_get_path(settings, "urls_file", "urls.txt", project_root),
        output_dir=_env_or_setting_path(
            "PODCAST_DOWNLOAD_DIR", settings, "output_dir", "downloads", project_root
        ),
        intermediate_dir=_env_or_setting_path(
            "PODCAST_INTERMEDIATE_DIR",
            settings,
            "intermediate_dir",
            "download_work",
            project_root,
        ),
        channel_count=_require_minimum_int(
            _get_int(settings, "channel_count", DEFAULT_CHANNEL_VIDEO_COUNT),
            "channel_count",
            1,
        ),
        log_file=_get_path(settings, "log_file", "download.log", project_root),
        downloaded_urls_file=_get_path(
            settings, "downloaded_urls_file", "downloaded_urls.txt", project_root
        ),
        min_channel_video_age_hours=_require_minimum_int(
            _get_int(
                settings,
                "min_channel_video_age_hours",
                DEFAULT_MIN_CHANNEL_VIDEO_AGE_HOURS,
            ),
            "min_channel_video_age_hours",
            0,
        ),
        delay_seconds=_require_minimum_float(
            _get_float(settings, "delay_seconds", DEFAULT_DELAY_SECONDS),
            "delay_seconds",
            0.0,
        ),
        retention_days=_require_minimum_int(
            _get_int(settings, RETENTION_DAYS_KEY, DEFAULT_RETENTION_DAYS),
            RETENTION_DAYS_KEY,
            MINIMUM_RETENTION_DAYS,
        ),
        download_timeout_seconds=_require_minimum_int(
            _get_int(
                settings, "download_timeout_seconds", DEFAULT_DOWNLOAD_TIMEOUT_SECONDS
            ),
            "download_timeout_seconds",
            MINIMUM_DOWNLOAD_TIMEOUT_SECONDS,
        ),
        trust_x_forwarded_for=_get_bool(settings, "trust_x_forwarded_for", False),
        cookies_file=cookies_file,
        always_use_cookies=_get_bool(settings, "always_use_cookies", True),
        bypass_age_check_file=_get_path(
            settings, "bypass_age_check_file", "bypass_age_check_urls.txt", project_root
        ),
        youtube_player_client=_get_text(
            settings, "youtube_player_client", DEFAULT_YOUTUBE_PLAYER_CLIENT
        ),
        ytdlp_verbose=_get_bool(settings, "ytdlp_verbose", DEFAULT_YTDLP_VERBOSE),
        # The schedule is a wall-clock rule, not a countdown: an hour of the
        # day and how many calendar days apart the run days are.
        scheduled_run_hour=_require_int_in_range(
            _get_int(settings, "scheduled_run_hour", DEFAULT_SCHEDULED_RUN_HOUR),
            "scheduled_run_hour",
            FIRST_HOUR_OF_DAY,
            LAST_HOUR_OF_DAY,
        ),
        scheduled_run_interval_days=_require_minimum_int(
            _get_int(
                settings,
                "scheduled_run_interval_days",
                DEFAULT_SCHEDULED_RUN_INTERVAL_DAYS,
            ),
            "scheduled_run_interval_days",
            1,
        ),
        cookie_expiry_warning_days=_require_minimum_int(
            _get_int(
                settings,
                "cookie_expiry_warning_days",
                DEFAULT_COOKIE_EXPIRY_WARNING_DAYS,
            ),
            "cookie_expiry_warning_days",
            0,
        ),
        max_download_attempts=_require_minimum_int(
            _get_int(settings, "max_download_attempts", DEFAULT_MAX_DOWNLOAD_ATTEMPTS),
            "max_download_attempts",
            1,
        ),
    )


def read_retention_days(config_path: Path) -> int:
    """Return ``retention_days`` as it is in ``config.toml`` right now.

    The web server loads its configuration once at startup, but each download
    run reads ``config.toml`` again, so the settings page reads the file instead
    of the startup copy to show what the next run will use.

    Parameters
    ----------
    config_path:
        Path to ``config.toml``.

    Returns
    -------
    int
        The configured number of days, or :data:`DEFAULT_RETENTION_DAYS` when
        the file or the key is missing.

    Raises
    ------
    ConfigError
        When the file cannot be parsed or the value is not a valid count.
    """
    return _require_minimum_int(
        _get_int(read_settings(config_path), RETENTION_DAYS_KEY, DEFAULT_RETENTION_DAYS),
        RETENTION_DAYS_KEY,
        MINIMUM_RETENTION_DAYS,
    )


def write_retention_days(config_path: Path, days: int) -> None:
    """Set ``retention_days`` in ``config.toml``, keeping every other line.

    The file is the operator's, full of explanatory comments, and Python's
    ``tomllib`` can read TOML but not write it, so the one line is edited as
    text. The next download run picks the value up; no restart is needed.

    Parameters
    ----------
    config_path:
        Path to ``config.toml``. Created if absent.
    days:
        Days to keep channel episodes, from :data:`MINIMUM_RETENTION_DAYS` to
        :data:`MAXIMUM_RETENTION_DAYS`.

    Raises
    ------
    ConfigError
        When ``days`` is outside that range.
    """
    _require_int_in_range(
        days, RETENTION_DAYS_KEY, MINIMUM_RETENTION_DAYS, MAXIMUM_RETENTION_DAYS
    )
    text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    setting_line = f"{RETENTION_DAYS_KEY} = {days}"

    # Before: "retention_days = 30" on its own line.
    # After:  the same line with the new number. Comments that mention the key
    # start with "#" and are not matched. A file without the key gets it as the
    # first line, where a top-level TOML key is always valid.
    key_line = re.compile(rf"^[ \t]*{RETENTION_DAYS_KEY}[ \t]*=.*$", re.MULTILINE)
    if key_line.search(text):
        text = key_line.sub(setting_line, text, count=1)
    else:
        text = f"{setting_line}\n{text}"

    # Replace in one rename, so a run starting at this moment reads either the
    # old file or the new one, never half of each.
    temporary_file = config_path.with_name(f".{config_path.name}.tmp")
    temporary_file.write_text(text, encoding="utf-8")
    temporary_file.replace(config_path)
