---
title: Operations
sidebar_position: 5
---

# Operations

## Local development

Install dependencies:

```bash
uv sync --dev
```

Run the test suite:

```bash
uv run python -m pytest -q
```

Run the API locally:

```bash
uv run uvicorn src.api:app --host 127.0.0.1 --port 8000
```

Generate a `.ui_password` hash manually:

```bash
uv run python -c 'from src.passwords import hash_password; import getpass; print(hash_password(getpass.getpass("Password: ")))' > .ui_password
```

This prompts for the real password in the terminal and writes only the PBKDF2 hash into `.ui_password`.

For Docker deployments, create that `.ui_password` file in the repo before you copy the project to the server or run `docker compose up -d`. The image build carries it into `/app/.ui_password`, and the first container start seeds the mounted `/data/.ui_password` from it automatically.

## Docker behavior

The container bootstrap path does the following:

1. Copies the repo `config.ini` into the mounted data directory if that file is missing.
2. Copies an image-bundled `.ui_password` into the mounted data directory when that file exists in the repo at build time and no mounted password file exists yet.
3. Uses an existing `/data/cookies.txt` when present, fixes its permissions to owner-only, and only seeds it from image-bundled repo-root `cookies.txt` when the mounted data directory has no cookie file.
4. Creates missing runtime files such as `urls.txt`, `downloaded_urls.txt`, `download.log`, `.login_state.json`, and `.ui_password`.
5. Stores a PBKDF2 hash for the default password `.ui_password` if no password file exists.
6. Rewrites legacy `CHANGE_ME` files and other plain-text password files into hashes in place.
7. Performs a best-effort `yt-dlp` update when `YT_DLP_AUTO_UPDATE=true`.

If you already have a plain-text password in `.ui_password`, the Docker entrypoint will rewrite it as a hash automatically on the next container start.

## YouTube cookies

For YouTube requests that are blocked after normal unauthenticated access, provide a Netscape-format cookie file named `cookies.txt`. In Docker Compose, the runtime file is `$HOME/.containers/podcast-downloader/cookies.txt` on the host and `/data/cookies.txt` inside the container.

The mounted data cookie is the source of truth. The entrypoint does not replace it on rebuilds or restarts; it only runs `chmod 600` on the existing file. If `/data/cookies.txt` is missing, the entrypoint seeds it from image-bundled `/app/cookies.txt` when that file exists.

You can update cookies without SSH file copying by signing in to the web UI and using the YouTube cookies upload form. The upload endpoint requires the normal UI session and CSRF token, overwrites the configured cookie path, validates the Netscape header, normalizes line endings to LF, and writes permission mode `600`.

You can also set `cookies_file` in `config.ini` to another mounted path.

`always_use_cookies` defaults to `true`, so YouTube `yt-dlp` calls pass `--cookies <file>` on the first attempt and retry once without cookies when that attempt fails or produces no usable result. Set it to `false` to invert the order: plain first, cookies on retry. Keep the cookie file private because it contains browser authentication state.

### Cookie file format

`yt-dlp` expects a Mozilla/Netscape cookie jar, not JSON or browser SQLite exports pasted in directly.

| Requirement | Detail |
|---|---|
| Header line | First line must be `# Netscape HTTP Cookie File` for browser uploads; `yt-dlp` also accepts `# HTTP Cookie File` on manually managed files |
| Line endings | LF (`\n`) on Linux/macOS; CRLF (`\r\n`) on Windows |
| Bad-newline symptom | `HTTP Error 400: Bad Request` when running `yt-dlp --cookies cookies.txt ...` |

On Linux, convert a Windows-exported file manually with:

```bash
sed -i 's/\r$//' cookies.txt
```

The web UI upload does this line-ending conversion automatically.

## Scheduler behavior

- Scheduled runs happen every `DOWNLOAD_INTERVAL_HOURS`.
- Scheduler subprocesses run `python -m src.cli` with the project root as their current working directory, so Docker runtime behavior does not depend on where the scheduler thread was started.
- `yt-dlp` is not pinned in `uv.lock`. The Docker image installs the latest PyPI release with `yt-dlp[default]` during `docker build` and upgrades the same dependency group again on each container start when `YT_DLP_AUTO_UPDATE=true`. The default dependency group includes the YouTube EJS challenge-solver package. Local development should run `uv pip install "yt-dlp[default]"` after `uv sync`.
- The Docker image includes Deno so current `yt-dlp` YouTube extraction has a supported JavaScript runtime on `PATH`.
- The scheduled path upgrades only the `yt-dlp[default]` dependency group, not the rest of the Python environment.
- After a scheduled `yt-dlp` update, the downloader waits 5 minutes before starting the run unless a UI-triggered download arrives during that delay.
- If the package update fails, the scheduler logs the warning, reports the current `yt-dlp` version, and skips the post-update wait.
- A direct video URL added through the web UI triggers an immediate single-URL run for only that submitted URL.
- Direct non-YouTube URLs are always attempted in that immediate single-URL run because they do not use the YouTube age gate.
- Direct YouTube URLs are attempted immediately only when they pass the configured minimum-age gate, unless the `Download now` checkbox is checked.
- Checked playlist URLs trigger an immediate full-playlist run that downloads every entry instead of the configured `channel_count` cap.
- Channel and playlist additions stay queued for the normal scheduled full-queue run. Each run expands only the latest configured `channel_count` entries from each monitored playlist or channel source.
- Single-URL immediate runs do not inspect the rest of `urls.txt`, so they do not expand older channel or playlist entries.
- After an immediate run, the scheduler waits a full interval again before the next scheduled run.

## Downloaded file dates

Completed MP3 files get an embedded MP3 `date` tag set to the local download completion time. Audiobookshelf maps that embedded audio date into the visible podcast episode date. The same metadata pass writes the source URL into the embedded MP3 `comment` tag. YouTube source URLs are stored in canonical watch form, including live URLs, while non-YouTube source URLs are stored as provided. The metadata rewrite uses a non-`.mp3` temporary file and copies the rewritten bytes into the original MP3 path without replacing its inode, so Audiobookshelf should not index a temporary or replacement duplicate during a scan. The downloader also keeps `--no-mtime` in the `yt-dlp` command because preventing source timestamp preservation is harmless and useful, but it does not do a separate filesystem timestamp restamp for Audiobookshelf.

## Download folder layout

Only MP3 files are grouped under the configured download directory. The queue file `urls.txt` remains in the data directory and is not moved or copied into `downloads/`.

```text
downloads/
├── channel-one/
├── channel-two/
├── playlist-name1/
└── singles/
```

Channel folder names come from the source URL after filesystem-safe cleanup. Playlist folder names prefer the playlist title reported by `yt-dlp`; when that lookup fails, the folder falls back to the `list=` identifier. Direct individual videos from YouTube or any other supported site go into `singles/`.

## Retention cleanup

After each download cycle, the downloader scans MP3 files recursively under the configured download directory, but only files in current YouTube channel output folders are eligible for retention cleanup. Playlist and single-video files are never deleted by this cleanup rule.

Cleanup reads the embedded MP3 `date` tag and deletes eligible channel files older than `retention_days`. The checked-in default is 30 days. Cleanup does not use YouTube release dates. It also does not use filesystem modification time as the deletion clock. If an MP3 has missing or unreadable date metadata, or does not have a source URL in the comment tag, the file is logged and left alone. When a channel MP3 is deleted, its source video URL is removed from `downloaded_urls.txt`.

## Operational files

| File | Purpose |
|---|---|
| `urls.txt` | Pending queue of user-supplied URLs |
| `downloaded_urls.txt` | Archive of expanded channel and playlist items |
| `download.log` | Main runtime log |
| `activity.log` | Concise browser activity feed, created on first activity event |
| `.login_state.json` | Failed-login counters and temporary bans |
| `.ui_password` | Stored PBKDF2 hash for the shared UI password |

## Manual smoke check

There is one manual live-network script:

```bash
uv run python test_sponsorblock.py
```

It is intentionally kept out of the normal pytest suite because it depends on the live YouTube and SponsorBlock ecosystem.
