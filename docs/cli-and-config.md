---
title: CLI and Config
sidebar_position: 3
---

# Command line and configuration

## Common commands

Run one pass through the queue:

```bash
uv run python main.py
```

Add URLs to the queue without downloading them:

```bash
uv run python main.py --add-url "https://www.youtube.com/watch?v=..."
uv run python main.py --add-url "https://www.youtube.com/@channel"
uv run python main.py --add-url "https://www.youtube.com/@channel/videos"
uv run python main.py --add-url "https://www.youtube.com/@channel/streams"
uv run python main.py --add-url "https://videos.example.com/watch/episode-1"
uv run python main.py --add-url "https://www.youtube.com/watch?v=..." --skip-age-check
```

For YouTube channels, `/videos` selects normal uploads and `/streams` selects livestreams. A bare channel URL uses `/videos`.

Read URLs from standard input and append them to the queue:

```bash
uv run python main.py --add-url-stdin < new_urls.txt
```

Use `--skip-age-check` with either add command when a direct YouTube video should bypass the waiting period on its next run. Other sites do not use this waiting period.

The web UI offers the same option. For a direct URL, it starts `python -m src.cli --download-single-url "<url>"` from the project root and handles only that URL. The checkbox also records a one-use exception for a new YouTube video.

For a playlist, the checkbox starts `python -m src.cli --download-full-playlist "<url>"`. This downloads every playlist entry immediately; scheduled runs consider only the newest `channel_count` entries.

Override the queue file, output folder, or number of recent channel/playlist entries:

```bash
uv run python main.py -f custom_urls.txt -o ./custom_downloads -n 3
```

`-n` must be at least `1`. `--download-single-url` accepts only individual URLs. `--download-full-playlist` requires a dedicated YouTube playlist URL. An add command exits with an error if it adds no new valid URL.

## `config.ini`

The checked-in file is in the project root and contains one `[podcast]` section.

| Key | Meaning | Current checked-in default |
|---|---|---|
| `urls_file` | Queue file path | `urls.txt` |
| `output_dir` | Finished MP3 library directory | `downloads` |
| `intermediate_dir` | Temporary work directory. Completed work folders are removed when this differs from `output_dir` | `download_work` |
| `channel_count` | Number of recent channel or playlist entries to consider; at least `1` | `2` |
| `min_channel_video_age_hours` | Minimum age before a YouTube video is eligible when its age is known; at least `0` | `24` |
| `delay_seconds` | Pause between downloads; at least `0` | `60` |
| `retention_days` | Number of days to keep YouTube channel MP3 files, measured from embedded download-date metadata; at least `1` | `30` |
| `download_timeout_seconds` | Limit for one `yt-dlp` attempt, including download, MP3 conversion, SponsorBlock, and thumbnail embedding; at least `60` | `3600` |
| `log_file` | Full runtime log. The browser-facing `activity.log` is written beside it. Logs rotate at 5 MB, keeping three older copies | `download.log` |
| `downloaded_urls_file` | History of successfully expanded URLs; also prevents duplicate downloads | `downloaded_urls.txt` |
| `bypass_age_check_file` | One-use exceptions to the YouTube waiting period | `bypass_age_check_urls.txt` |
| `cookies_file` | Optional Netscape cookie-jar path. The web UI can create a configured file that is missing | unset |
| `always_use_cookies` | If true, try cookies first and retry without them; if false, reverse the order | `true` |
| `youtube_player_client` | YouTube player API used by `yt-dlp`; blank lets `yt-dlp` choose | `web_embedded` |
| `ytdlp_verbose` | Run every `yt-dlp` attempt with `-v`; retry attempts are verbose either way | `false` |
| `trust_x_forwarded_for` | Whether the UI trusts client IP headers from your reverse proxy | `true` |

## Environment variables

| Variable | Purpose |
|---|---|
| `PODCAST_DATA_DIR` | Alternate directory for `config.ini`, queue files, `.env`, credentials, and login state |
| `PODCAST_DOWNLOAD_DIR` | Finished MP3 library directory, mainly useful for separating Docker volumes |
| `PODCAST_INTERMEDIATE_DIR` | Scratch download directory; Compose maps `$HOME/downloads/temporary` to `/temporary` |
| `DOWNLOAD_INTERVAL_HOURS` | Scheduler interval in Docker mode |
| `YT_DLP_AUTO_UPDATE` | Enables or disables Docker-time `yt-dlp` upgrades; only `yt-dlp` is updated |
| `HOST_UID` | Numeric host user that owns mounted Docker files; defaults to `1000` |
| `HOST_GID` | Numeric host group that owns mounted Docker files; defaults to `1000` |

`yt-dlp` is not listed in `uv.lock`. After `uv sync`, install the current release and its default YouTube challenge-solving dependencies:

```bash
uv pip install "yt-dlp[default]"
```

Docker does this during the image build and at container startup. The image includes Deno for YouTube JavaScript challenges.

## YouTube player client

YouTube provides stream URLs through several player APIs. `yt-dlp` calls these APIs “player clients”. Most now return URLs that require a **GVS PO Token**, a proof-of-origin token generated by YouTube’s web player. Without one, the download can fail partway through with:

```text
ERROR: unable to download video data: HTTP Error 403: Forbidden
```

Metadata may still load successfully, so the error often appears only when audio starts transferring.

`youtube_player_client` selects the client used by `yt-dlp`. The default, `web_embedded`, currently provides usable URLs without a token. Leaving the setting blank lets `yt-dlp` choose, which currently triggers the 403 error.

If YouTube closes this route, the durable fix is a PO token provider plugin. See the [yt-dlp PO Token guide](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide).

## Failure logging

Each download failure is recorded in two places.

`download.log` contains the exact `yt-dlp` command and the complete stdout and stderr from every attempt. This includes both attempts of a cookie retry, which may fail for different reasons.

`activity.log`, shown in the web UI, contains one line with the cause:

```text
[2026-08-18 21:14] Failed: https://www.youtube.com/watch?v=... - ERROR: [youtube] Video unavailable
```

The cause is the last `ERROR:` line from the failed attempt, collapsed to one line and capped at 160 characters. Timeouts, metadata failures, and publishing failures name themselves instead.

Retry attempts always run with `-v`, leaving the full extractor trail, including the player client and whether a PO token provider was available. A run that succeeds on its first attempt adds no verbose retry output. A double failure with the verbose retry adds roughly 7 KB to the log.

`ytdlp_verbose = true` adds `-v` to first attempts too. It is off by default because retries already provide verbose output for real failures. Turn it on when a run reports success but produces the wrong result. `-v` prints the cookie file path, never cookie values.

## Cookie support

When `cookies_file` is unset, the app looks for `cookies.txt` in the active data directory.

`always_use_cookies` controls the order of attempts when a cookie file exists:

- `true` (default): use cookies first for YouTube downloads, channel/playlist expansion, and metadata lookups; retry once without them if the attempt fails or produces no usable result.
- `false`: try without cookies first; retry once with cookies if needed.

The file must use the Netscape/Mozilla text format expected by `yt-dlp`:

- The first line must be `# HTTP Cookie File` or `# Netscape HTTP Cookie File`.
- Use LF (`\n`) line endings on Linux and macOS, or CRLF (`\r\n`) on Windows. Convert them when moving the file between operating systems.
- `HTTP Error 400: Bad Request` from `--cookies` often means the line endings are wrong.

With Docker Compose, the host file is `$HOME/.containers/podcast-downloader/cookies.txt`; inside the container it is `/data/cookies.txt`. A project-root `cookies.txt` is copied into the image and seeds `/data/cookies.txt` only when the mounted data directory has no cookie file. The authenticated web UI can overwrite the configured path, validate the Netscape header, convert line endings to LF, and set permission mode `600`.

## Validation behavior

- Invalid integer and float values fail immediately with a `ConfigError` naming the bad key.
- Out-of-range values fail too: `channel_count < 1`, `min_channel_video_age_hours < 0`, `delay_seconds < 0`, `retention_days < 1`, and `download_timeout_seconds < 60`.
- A blank configured path fails immediately instead of resolving to the data directory.
- Invalid `DOWNLOAD_INTERVAL_HOURS` values do not fall back; Docker startup fails fast.
- If `urls.txt` is missing, the project creates a starter file with comments and example URLs.
