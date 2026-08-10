---
title: CLI and Config
sidebar_position: 3
---

# Command line and configuration

## Common commands

Run the downloader:

```bash
uv run python main.py
```

Add one or more URLs without starting a download:

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

Use `--skip-age-check` with `--add-url` or `--add-url-stdin` when a direct YouTube video should skip the configured waiting period on its next run. Other sites do not use SponsorBlock, so they do not use this waiting period.

The Docker web UI offers the same option. When you add a direct URL, the scheduler runs `python -m src.cli --download-single-url "<url>"` from the project root, so it processes only that URL. Checking the box also records a one-use exception so a new YouTube video can skip the waiting period once.

For a playlist URL, checking the box queues `python -m src.cli --download-full-playlist "<url>"`. That command downloads every playlist entry immediately instead of waiting for the scheduled run, which checks only `channel_count` recent entries.

Override the queue file, output folder, or channel depth:

```bash
uv run python main.py -f custom_urls.txt -o ./custom_downloads -n 3
```

## `config.ini`

The checked-in configuration file is at the project root and has one `[podcast]` section.

| Key | Meaning | Current checked-in default |
|---|---|---|
| `urls_file` | Queue file path | `urls.txt` |
| `output_dir` | Finished MP3 library directory | `downloads` |
| `intermediate_dir` | Temporary directory used before completed files are published; finished work folders are removed when it differs from `output_dir` | `download_work` |
| `channel_count` | How many recent channel or playlist entries to consider; must be at least `1` | `2` |
| `min_channel_video_age_hours` | Minimum age before a YouTube direct video or channel upload is eligible when age is known; must be at least `0` | `24` |
| `delay_seconds` | Sleep between downloads; must be at least `0` | `60` |
| `retention_days` | How many days to keep YouTube channel MP3 files, measured from embedded download-date metadata; must be at least `1` | `30` |
| `download_timeout_seconds` | Time limit for one `yt-dlp` attempt, covering the media download plus the MP3 conversion, SponsorBlock pass, and thumbnail embed; must be at least `60` | `3600` |
| `log_file` | Full runtime log path; browser-facing `activity.log` is written beside it. Rotates at 5 MB keeping three older copies | `download.log` |
| `downloaded_urls_file` | History of expanded URLs that finished successfully; also prevents duplicate downloads | `downloaded_urls.txt` |
| `bypass_age_check_file` | File containing one-use exceptions to the YouTube waiting period | `bypass_age_check_urls.txt` |
| `cookies_file` | Optional Netscape cookie jar path | unset |
| `always_use_cookies` | When true, try cookies first and retry without them once; when false, try without cookies first and retry with them once | `true` |
| `trust_x_forwarded_for` | Whether the UI trusts client IP headers from your reverse proxy | `true` |

## Environment variables

| Variable | Purpose |
|---|---|
| `PODCAST_DATA_DIR` | Alternate directory for `config.ini`, queue files, `.env`, credentials, and login state |
| `PODCAST_DOWNLOAD_DIR` | Finished MP3 library directory, mainly for Docker volume separation |
| `PODCAST_INTERMEDIATE_DIR` | Scratch download directory; Compose maps `$HOME/downloads/temporary` to `/temporary` |
| `DOWNLOAD_INTERVAL_HOURS` | Scheduler interval in Docker mode |
| `YT_DLP_AUTO_UPDATE` | Enables or disables Docker-time `yt-dlp` upgrades; only the `yt-dlp` package is targeted |

`yt-dlp` is not listed in `uv.lock`. After `uv sync`, install the current release and its default YouTube challenge-solving dependencies with `uv pip install "yt-dlp[default]"`. Docker does this during the image build and at container startup. The image includes Deno for YouTube JavaScript challenges.

## Cookie support

If `cookies_file` is not configured, the app looks for `cookies.txt` in the active data directory.

`always_use_cookies` controls the YouTube cookie strategy when a cookie file is present:

- `true` (default): pass cookies on the first YouTube `yt-dlp` call for downloads, channel/playlist expansion, and metadata lookups; if that attempt fails or produces no usable result, retry once without cookies.
- `false`: try without cookies first; if the plain attempt fails or produces no usable result, retry once with the cookie file.

The cookie file must use the Netscape/Mozilla text format expected by `yt-dlp`:

- The first line must be either `# HTTP Cookie File` or `# Netscape HTTP Cookie File`.
- Use the newline style that matches your OS: LF (`\n`) on Linux and macOS, CRLF (`\r\n`) on Windows. Convert line endings if you copied the file from another machine.
- `HTTP Error 400: Bad Request` when using `--cookies` is a common sign of invalid newline format.

In Docker Compose, the runtime cookie file is `$HOME/.containers/podcast-downloader/cookies.txt` on the host and `/data/cookies.txt` inside the container. A project-root `cookies.txt` is copied into the Docker image and only seeds `/data/cookies.txt` when the mounted data directory does not already have a cookie file. The authenticated web UI can overwrite the configured cookie path, validate the Netscape header, normalize line endings to LF, and set permission mode `600`.

## Validation behavior

- Invalid integer and float values in `config.ini` fail immediately with a `ConfigError` that names the bad key.
- Out-of-range numeric values fail too: `channel_count < 1`, `min_channel_video_age_hours < 0`, `delay_seconds < 0`, `retention_days < 1`, and `download_timeout_seconds < 60`.
- Blank configured paths fail immediately instead of resolving to the data directory.
- Invalid `DOWNLOAD_INTERVAL_HOURS` values do not fall back. Docker startup fails fast instead.
- If `urls.txt` is missing, the project creates a starter file with comments and example URLs.
