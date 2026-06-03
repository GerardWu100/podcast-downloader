---
title: CLI and Config
sidebar_position: 3
---

# CLI and Config

## Common commands

Run the downloader:

```bash
uv run python main.py
```

Append one or more URLs without starting a download:

```bash
uv run python main.py --add-url "https://www.youtube.com/watch?v=..."
uv run python main.py --add-url "https://www.youtube.com/@channel"
uv run python main.py --add-url "https://www.youtube.com/@channel/videos"
uv run python main.py --add-url "https://www.youtube.com/@channel/streams"
uv run python main.py --add-url "https://videos.example.com/watch/episode-1"
uv run python main.py --add-url "https://www.youtube.com/watch?v=..." --skip-age-check
```

For YouTube channels, `/videos` means normal uploads and `/streams` means livestream entries. Bare channel URLs default to `/videos`.

Append URLs from standard input:

```bash
uv run python main.py --add-url-stdin < new_urls.txt
```

Use `--skip-age-check` with `--add-url` or `--add-url-stdin` when you want a direct YouTube video URL to bypass the configured minimum-age gate on the next downloader run. Non-YouTube direct URLs do not use SponsorBlock, so they do not need the age gate.

The Docker web UI uses the same bypass idea, but every direct video URL uses the single-item immediate path. When you add a direct URL, the scheduler runs `python -m src.cli --download-single-url "<url>"` from the project root so only that new video is considered immediately. Checking the box adds the URL to the bypass file first, which lets a direct YouTube video skip the configured minimum-age gate for that one attempt.

Override the queue file, output folder, or channel depth:

```bash
uv run python main.py -f custom_urls.txt -o ./custom_downloads -n 3
```

## `config.ini`

The checked-in configuration file lives at the project root and uses a single `[podcast]` section.

| Key | Meaning | Current checked-in default |
|---|---|---|
| `urls_file` | Queue file path | `urls.txt` |
| `output_dir` | Finished MP3 library directory | `downloads` |
| `intermediate_dir` | Scratch directory for `yt-dlp` and metadata passes; completed work folders are removed after successful publish when this is separate from `output_dir` | `download_work` |
| `channel_count` | How many recent channel or playlist entries to consider; must be at least `1` | `2` |
| `min_channel_video_age_hours` | Minimum age before a YouTube direct video or channel upload is eligible when age is known; must be at least `0` | `24` |
| `delay_seconds` | Sleep between downloads; must be at least `0` | `60` |
| `retention_days` | How many days to keep YouTube channel MP3 files, measured from embedded download-date metadata; must be at least `1` | `30` |
| `log_file` | Full runtime log path; browser-facing `activity.log` is written beside it | `download.log` |
| `downloaded_urls_file` | Archive path for expanded URLs, also used for duplicate detection | `downloaded_urls.txt` |
| `bypass_age_check_file` | File that records one-shot direct-video age-gate bypasses | `bypass_age_check_urls.txt` |
| `cookies_file` | Optional Netscape cookie jar path | unset |
| `trust_x_forwarded_for` | Whether the UI trusts reverse-proxy IP headers | `true` |

## Environment variables

| Variable | Purpose |
|---|---|
| `PODCAST_DATA_DIR` | Alternate directory for `config.ini`, queue files, password file, and login state |
| `PODCAST_DOWNLOAD_DIR` | Finished MP3 library directory, mainly for Docker volume separation |
| `PODCAST_INTERMEDIATE_DIR` | Scratch download directory; Compose maps `$HOME/downloads/temporary` to `/temporary` |
| `DOWNLOAD_INTERVAL_HOURS` | Scheduler interval in Docker mode |
| `YT_DLP_AUTO_UPDATE` | Enables or disables Docker-time `yt-dlp` upgrades; only the `yt-dlp` package is targeted |

## Cookie support

If `cookies_file` is not configured, the loader checks for `cookies.txt` in the active data directory. Direct YouTube downloads still try without cookies first. If that plain attempt fails or produces no usable MP3, the downloader retries once with the cookie file.

The cookie file must use the Netscape/Mozilla text format expected by `yt-dlp`. In Docker, put `cookies.txt` in the mounted `PODCAST_DATA_DIR` directory, or set `cookies_file` in the mounted `config.ini` to another mounted path.

## Validation behavior

- Invalid integer and float values in `config.ini` now fail fast with a `ConfigError` that names the bad key.
- Out-of-range numeric values fail too: `channel_count < 1`, `min_channel_video_age_hours < 0`, `delay_seconds < 0`, and `retention_days < 1`.
- Blank configured paths fail fast instead of resolving to the data directory.
- Invalid `DOWNLOAD_INTERVAL_HOURS` values do not fall back. Docker startup fails fast instead.
- Missing `urls.txt` causes the project to create a sample queue file with comments and example URLs.
