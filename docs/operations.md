---
title: Operations
sidebar_position: 5
---

# Running the downloader

## Local development

Install the dependencies:

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

Set the web UI login by copying `.env.example` to `.env` and changing both values:

```bash
cp .env.example .env
# edit .env: set UI_USERNAME and UI_PASSWORD
```

At startup the app reads `.env`, hashes `UI_PASSWORD` with PBKDF2, checks that the hash matches the password, and writes only the hash to `.ui_credentials.json`. There is no manual hashing step. To change the password, edit `.env` and restart; the app creates and checks the new hash automatically.

For Docker deployments, create that `.env` file in the repo before you copy the project to the server or run `docker compose up -d`. The image build carries it into `/app/.env`, and the first container start seeds the mounted `/data/.env` from it automatically. After that, `/data/.env` on the host (`$HOME/.containers/podcast-downloader/.env`) is the file to edit.

Compose expects the shared proxy network named `single`. Create it once when it
does not exist:

```bash
docker network inspect single >/dev/null 2>&1 || docker network create single
```

## Docker behavior

When the container starts, it:

1. Copies the repo `config.ini` into the mounted data directory if that file is missing.
2. Copies an image-bundled `.env` (or `.env.example` when the repo has no `.env`) into the mounted data directory when no mounted `.env` exists yet, and sets its permissions to owner-only.
3. Uses an existing `/data/cookies.txt` when present, fixes its permissions to owner-only, and only seeds it from image-bundled repo-root `cookies.txt` when the mounted data directory has no cookie file.
4. Creates missing runtime files such as `urls.txt`, `downloaded_urls.txt`, `download.log`, and `.login_state.json`.
5. Performs a best-effort `yt-dlp` update when `YT_DLP_AUTO_UPDATE=true`.

`start.py` then hashes and checks the `.env` password before the web server starts. If `.env` still contains the example password `changeme`, startup logs a warning.

## YouTube cookies

If YouTube blocks a normal request, provide a Netscape-format cookie file named `cookies.txt`. With Docker Compose, the file is `$HOME/.containers/podcast-downloader/cookies.txt` on the host and `/data/cookies.txt` in the container.

The mounted cookie file is the one the app uses. Rebuilds and restarts do not replace it; the entrypoint only applies `chmod 600`. If `/data/cookies.txt` is missing, the entrypoint copies `/app/cookies.txt` when that file exists.

You can update cookies from the web UI instead of copying a file over SSH. The upload form requires a normal signed-in session, checks the Netscape header, converts line endings to LF, and writes the file with permission mode `600`.

You can also set `cookies_file` in `config.ini` to another mounted path.

`always_use_cookies` defaults to `true`, so YouTube `yt-dlp` calls use `--cookies <file>` first and retry once without cookies if needed. Set it to `false` to try without cookies first. Keep the file private because it contains browser sign-in data.

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

Completed MP3 files get an embedded MP3 `date` tag set to the Toronto/Eastern download completion time. Audiobookshelf maps that embedded audio date into the visible podcast episode date. The same metadata pass writes the source URL into the embedded MP3 `comment` tag. YouTube source URLs are stored in canonical watch form, including live URLs, while non-YouTube source URLs are stored as provided. The metadata rewrite uses a non-`.mp3` temporary file and copies the rewritten bytes into the original MP3 path without replacing its inode, so Audiobookshelf should not index a temporary or replacement duplicate during a scan. The downloader also keeps `--no-mtime` in the `yt-dlp` command because preventing source timestamp preservation is harmless and useful, but it does not do a separate filesystem timestamp restamp for Audiobookshelf.

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

On scheduled full-queue runs, the downloader scans MP3 files recursively under the configured download directory before it checks archive-backed channel candidates. Only files in current YouTube channel output folders are eligible for retention cleanup. Playlist and single-video files are never deleted by this cleanup rule.

Cleanup reads the embedded MP3 `date` tag and deletes eligible channel files older than `retention_days`. The checked-in default is 30 days. Cleanup does not use YouTube release dates. It also does not use filesystem modification time as the deletion clock. If an MP3 has missing or unreadable date metadata, or does not have a source URL in the comment tag, the file is logged and left alone. When a channel MP3 is deleted, its source video URL is removed from `downloaded_urls.txt`.

## Operational files

| File | Purpose |
|---|---|
| `urls.txt` | Pending queue of user-supplied URLs |
| `downloaded_urls.txt` | Archive of expanded channel and playlist items |
| `download.log` | Main runtime log; rotates at 5 MB keeping `download.log.1` through `download.log.3` |
| `activity.log` | Concise browser activity feed, created on first activity event |
| `.login_state.json` | Failed-login counters and temporary bans |
| `.env` | Operator-set UI account name and plain password |
| `.ui_credentials.json` | UI account name and PBKDF2 password hash generated from `.env` |

## Manual smoke check

There is one manual check that uses the live network:

```bash
uv run --with "yt-dlp[default]" python scripts/sponsorblock_smoke_check.py
```

It is intentionally kept out of the normal pytest suite because it depends on the live YouTube and SponsorBlock ecosystem.
