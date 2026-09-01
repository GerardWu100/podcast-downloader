---
title: CLI and Config
sidebar_position: 3
---

# Command line and configuration

## Common commands

Run one queue pass:

```bash
uv run python main.py
```

Add URLs without downloading them:

```bash
uv run python main.py --add-url "https://www.youtube.com/watch?v=..."
uv run python main.py --add-url "https://www.youtube.com/@channel"
uv run python main.py --add-url "https://www.youtube.com/@channel/videos"
uv run python main.py --add-url "https://www.youtube.com/@channel/streams"
uv run python main.py --add-url "https://videos.example.com/watch/episode-1"
uv run python main.py --add-url "https://www.youtube.com/watch?v=..." --skip-age-check
```

For YouTube channels, `/videos` selects normal uploads and `/streams` selects
livestreams. A bare channel URL uses `/videos`.

Read URLs from standard input and append them to the queue:

```bash
uv run python main.py --add-url-stdin < new_urls.txt
```

Use `--skip-age-check` with either add command to bypass the waiting period for
a direct YouTube video on its next run. Other sites do not use this wait.

The web UI offers the same option. For a direct URL, it starts
`python -m src.cli --download-single-url "<url>"` and handles only that URL.
The checkbox also records a one-use exception for a new YouTube video.

For a playlist, it starts
`python -m src.cli --download-full-playlist "<url>"`. This downloads every
playlist entry immediately; scheduled runs consider only the newest
`channel_count` entries.

Override the queue file, output folder, or number of recent channel/playlist
entries:

```bash
uv run python main.py -f custom_urls.txt -o ./custom_downloads -n 3
```

`-n` must be at least `1`. `--download-single-url` accepts only individual
URLs. `--download-full-playlist` requires a dedicated YouTube playlist URL.
An add command exits with an error if it adds no new valid URL.

## `config.ini`

The checked-in file is in the project root and contains one `[podcast]`
section.

| Key | Purpose | Default |
|---|---|---|
| `urls_file` | Queue file | `urls.txt` |
| `output_dir` | Finished MP3 library | `downloads` |
| `intermediate_dir` | Temporary work directory | `download_work` |
| `channel_count` | Recent channel or playlist entries to check; at least `1` | `2` |
| `min_channel_video_age_hours` | Minimum YouTube video age when known; at least `0` | `24` |
| `delay_seconds` | Pause between downloads; at least `0` | `60` |
| `retention_days` | Days to keep YouTube channel MP3s; at least `1` | `30` |
| `download_timeout_seconds` | Time limit for one attempt; at least `60` | `3600` |
| `scheduled_run_hour` | Local hour an automatic run starts, `0` to `23` | `6` |
| `scheduled_run_interval_days` | Calendar days between automatic runs; at least `1` | `2` |
| `log_file` | Detailed log; rotates at 5 MB and keeps three older copies | `download.log` |
| `downloaded_urls_file` | Successfully expanded URLs; also prevents duplicates | `downloaded_urls.txt` |
| `bypass_age_check_file` | One-use YouTube waiting-period exceptions | `bypass_age_check_urls.txt` |
| `cookies_file` | Optional Netscape cookie-jar path | unset |
| `always_use_cookies` | Try cookies first when `true`, last when `false` | `true` |
| `youtube_player_client` | YouTube player API passed to `yt-dlp`; blank lets it choose | `web_embedded` |
| `ytdlp_verbose` | Add `-v` to every `yt-dlp` attempt | `false` |
| `trust_x_forwarded_for` | Trust client-IP headers from your reverse proxy | `true` |

## Environment variables

| Variable | Purpose |
|---|---|
| `PODCAST_DATA_DIR` | Move `config.ini`, queue files, `.env`, credentials, and login state |
| `PODCAST_DOWNLOAD_DIR` | Override the finished MP3 directory |
| `PODCAST_INTERMEDIATE_DIR` | Override the scratch directory; Compose maps `$HOME/downloads/temporary` to `/temporary` |
| `YT_DLP_AUTO_UPDATE` | Enable or disable Docker-time `yt-dlp` upgrades |
| `TZ` | Clock the schedule and the logs use; Compose sets `America/Toronto` |
| `HOST_UID` | Host user for mounted Docker files; default `1000` |
| `HOST_GID` | Host group for mounted Docker files; default `1000` |

The `/api` routes need no setting of their own. They accept the same
`UI_USERNAME` and `UI_PASSWORD` accounts as the web page. `yt-dlp` is not in
`uv.lock`; install its current nightly release, the default YouTube
dependencies, and `curl-cffi` with:

```bash
uv pip install --prerelease allow "yt-dlp[default,curl-cffi]"
```

Docker installs it during image build and container startup. The image includes
Deno for YouTube JavaScript challenges. Nightly is intentional because media
site fixes often arrive there first.

## Rumble requests

Rumble can reject a normal command-line client with
`HTTP Error 403: Forbidden`. For exact `rumble.com` URLs, the downloader
passes `--impersonate chrome`. The `curl-cffi` package makes the request
look like it came from Chrome.

This setting is limited to Rumble. Other non-YouTube sites keep the ordinary
`--no-playlist` command.

## YouTube player client

YouTube exposes streams through several player APIs, called “player clients”
by `yt-dlp`. Most now return URLs that require a GVS PO Token, a
proof-of-origin token created by YouTube's web player. Without one, metadata
may load while audio fails with:

```text
ERROR: unable to download video data: HTTP Error 403: Forbidden
```

`youtube_player_client` selects the client. The default
`web_embedded` currently provides usable URLs without a token. Leaving the
setting blank lets `yt-dlp` choose, which currently triggers the 403 error.

If this route closes, the durable fix is a PO Token provider plugin. See the
[yt-dlp PO Token guide](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide).

## Failure logs

Each failure is recorded in two places:

- `download.log` contains the exact command and complete standard output and
  error from every attempt, including cookie retries.
- `activity.log`, shown in the web UI, contains one short line with the cause.

The cause is the final `ERROR:` line from the failed attempt, reduced to one
line and capped at 160 characters. Timeouts, metadata failures, and publishing
failures identify themselves.

Retries always use `-v`, so they record the extractor, player client, and
available PO Token provider. A first-attempt success adds no retry output. Set
`ytdlp_verbose = true` when a successful run produces the wrong result. Verbose
output can show the cookie-file path, but never its values.

## Cookies

When `cookies_file` is unset, the app looks for `cookies.txt` in the active
data directory.

`always_use_cookies` controls the order when a cookie file exists:

- `true` (default): use cookies first for YouTube downloads, expansion, and
  metadata; retry once without them if needed.
- `false`: try without cookies first; retry once with cookies if needed.

The file must use Netscape/Mozilla format. Its first line must be
`# HTTP Cookie File` or `# Netscape HTTP Cookie File`. Use LF line endings
on Linux and macOS, or CRLF on Windows. `HTTP Error 400: Bad Request` from
`--cookies` often means the line endings are wrong.

With Docker Compose, the host file is
`$HOME/.containers/podcast-downloader/cookies.txt`; inside the container it is
`/data/cookies.txt`. A project-root `cookies.txt` seeds that file only when
the mounted data directory has no cookie file. The signed-in web UI can
overwrite the configured path, validate the header, convert line endings to LF,
and set permission mode `600`.

## Validation

- Invalid integer and float values fail immediately with a `ConfigError` naming the key.
- Out-of-range values fail: `channel_count < 1`, `min_channel_video_age_hours < 0`, `delay_seconds < 0`, `retention_days < 1`, and `download_timeout_seconds < 60`.
- A blank configured path fails instead of silently using the data directory.
- An out-of-range `scheduled_run_hour` or `scheduled_run_interval_days` stops
  startup rather than falling back to a guess.
- If `urls.txt` is missing, the project creates a starter file with comments and example URLs.
