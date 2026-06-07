# Root Guide

## What Lives Where

This repository is a small web-video-to-audio pipeline with two entry surfaces:

1. A CLI batch downloader for pulling audio from URLs, channels, and playlists.
2. A FastAPI web UI for appending new URLs into the queue file, showing the current monitored entries from `urls.txt`, and removing URLs from that list.

The root folder exists to hold the project-level entrypoints, runtime configuration, state files, and operational artifacts. The actual application logic lives in [`src/`](/Users/gwh/projects/one-time-projects/podcast-downloader/src), while [`tests/`](/Users/gwh/projects/one-time-projects/podcast-downloader/tests) holds automated regressions.

The main navigation rule is simple:

- URL parsing and expansion logic lives in [`src/url_utils.py`](/Users/gwh/projects/one-time-projects/podcast-downloader/src/url_utils.py).
- File-backed queue, archive, bypass, and activity-log state lives in [`src/state/`](/Users/gwh/projects/one-time-projects/podcast-downloader/src/state).
- Batch execution and command-line behavior live in [`src/cli.py`](/Users/gwh/projects/one-time-projects/podcast-downloader/src/cli.py).
- Download orchestration now lives in [`src/downloads/`](/Users/gwh/projects/one-time-projects/podcast-downloader/src/downloads) with `src/downloader.py` kept as a compatibility adapter.
- UI authentication, monitored-URL rendering, queue removal, and HTML endpoints live in [`src/api.py`](/Users/gwh/projects/one-time-projects/podcast-downloader/src/api.py).
- Runtime defaults come from [`config.ini`](/Users/gwh/projects/one-time-projects/podcast-downloader/config.ini) and are parsed by [`src/config.py`](/Users/gwh/projects/one-time-projects/podcast-downloader/src/config.py).

## Root-Level Logic

The root does not contain business logic beyond entrypoints and operational scripts.

- [`main.py`](/Users/gwh/projects/one-time-projects/podcast-downloader/main.py) is the compatibility entrypoint. It delegates directly to `src.cli.main()`.
- [`config.ini`](/Users/gwh/projects/one-time-projects/podcast-downloader/config.ini) controls queue paths, output paths, channel polling depth, direct-video age gating, retention days, bypass-file paths, delay between downloads, and whether the UI should trust `X-Forwarded-For`.
- [`src/config.py`](/Users/gwh/projects/one-time-projects/podcast-downloader/src/config.py) loads that file and now raises `ConfigError` when numeric values cannot be parsed, are outside accepted ranges, or path settings are blank.
- [`start.py`](/Users/gwh/projects/one-time-projects/podcast-downloader/start.py) is the Docker-oriented process supervisor. It keeps the web UI in the main process, runs the download scheduler in a background thread, runs scheduled full-queue downloads and direct-video single-URL immediate downloads, and now fails fast during startup if `DOWNLOAD_INTERVAL_HOURS` is missing, malformed, or non-positive.
- [`docker-entrypoint.sh`](/Users/gwh/projects/one-time-projects/podcast-downloader/docker-entrypoint.sh) seeds the mounted data directory with a default `config.ini` and missing state files on first boot, copies an image-bundled `.ui_password` into the mounted data path when present, migrates `.ui_password` into a hashed format, then performs a best-effort `yt-dlp` update.
- [`Dockerfile`](/Users/gwh/projects/one-time-projects/podcast-downloader/Dockerfile) builds the runtime image with Python, `ffmpeg`, the locked project dependencies, and the Docker entrypoint.
- [`docker-compose.yml`](/Users/gwh/projects/one-time-projects/podcast-downloader/docker-compose.yml) defines the default container deployment with mounted data and downloads volumes plus the scheduled download interval.
- [`urls.txt`](/Users/gwh/projects/one-time-projects/podcast-downloader/urls.txt) is the input queue users edit manually or through the web UI. The UI now renders its current contents and can remove individual monitored URLs directly from the browser.
- `cookies.txt`, when present in the active data directory, is a private Netscape-format cookie file used only as a fallback retry for blocked direct YouTube downloads.
- [`downloaded_urls.txt`](/Users/gwh/projects/one-time-projects/podcast-downloader/downloaded_urls.txt) is the archive used to avoid re-downloading channel and playlist entries and to reject already-downloaded URLs in the web UI.
- [`download.log`](/Users/gwh/projects/one-time-projects/podcast-downloader/download.log) is the main diagnostic runtime log produced by the downloader.
- `activity.log` is the concise browser-facing activity feed written beside `download.log`.
- [`test_sponsorblock.py`](/Users/gwh/projects/one-time-projects/podcast-downloader/test_sponsorblock.py) is a manual smoke script for live SponsorBlock debugging. It is not part of the automated test suite.
- [`pyproject.toml`](/Users/gwh/projects/one-time-projects/podcast-downloader/pyproject.toml) and [`uv.lock`](/Users/gwh/projects/one-time-projects/podcast-downloader/uv.lock) define the managed Python environment.

## Design Notes

### Queue, archive, and downloaded file dates

The project keeps a user-facing queue file and a machine-facing archive file separate.

- `urls.txt` is the source of truth for what should be attempted next.
- `downloaded_urls.txt` exists only to deduplicate expanded channel and playlist entries over time.

This matters because direct single-video URLs are intentionally removed from `urls.txt` after success but are not added to the archive, while expanded YouTube channel and playlist items are archived to prevent future repeats.

YouTube livestream URLs such as `https://www.youtube.com/live/VIDEO_ID` are normalized to the same `https://www.youtube.com/watch?v=VIDEO_ID` identity used for ordinary videos. Completed livestreams can be submitted or rediscovered through either route, but queue cleanup and duplicate checks should treat them as one video.

YouTube channel tab URLs control channel expansion. `https://www.youtube.com/@PBDPodcast/videos` monitors ordinary uploads, `https://www.youtube.com/@PBDPodcast/streams` monitors livestream entries, and `https://www.youtube.com/@PBDPodcast/` defaults to the uploads tab.

The queue file is now protected by an interprocess file lock during reads and writes. That lock is owned by the state-store layer in `src/state/`. It prevents the Docker scheduler and the web UI from overwriting each other's changes when one side removes a finished URL while the other appends a new one.

The archive file now uses the same locking model because it is read by the web UI for duplicate detection while the downloader appends new completed URLs in the background. Expanded-item downloads hold that archive lock across duplicate detection, the download attempt, and the success append so two downloader processes cannot work on the same expanded URL at the same time. Failed downloads are not appended, so they remain retryable.

The project also keeps a separate bypass-age file for one-shot overrides. When a user adds a direct YouTube video URL with the UI checkbox or the CLI `--skip-age-check` flag, that normalized URL is written there so the next downloader run can bypass the configured YouTube minimum-age gate for that specific item. In Docker, every direct-video UI addition adds a scheduler payload for that normalized URL, so the immediate run considers only the newly submitted direct video instead of processing every queued item. The checkbox only controls the YouTube age gate.

Invalid numeric settings in `config.ini` now fail fast instead of silently falling back to defaults, so a bad deploy surfaces the broken key immediately. Range checks are enforced too: `channel_count` and `retention_days` must be at least `1`, while `min_channel_video_age_hours` and `delay_seconds` must be at least `0`. Blank path settings fail instead of resolving to the data directory by accident.

Completed MP3 files are stamped with the local download completion time after `yt-dlp` finishes. The downloader writes that value into the MP3 date metadata that Audiobookshelf maps into the visible podcast episode date. The same metadata pass writes the source URL into the MP3 comment tag. YouTube live, short, and watch links are normalized to the canonical watch URL before that tag is written, so completed livestreams do not get a separate metadata identity from the same video's watch URL. The metadata rewrite uses a temporary file without an `.mp3` extension, then copies the rewritten bytes into the existing MP3 path instead of replacing that path's inode, so Audiobookshelf should not index a temporary or replacement duplicate episode during the rewrite.

Downloaded MP3 files are grouped directly under the configured download directory by source. Channel URLs write to sanitized direct child folders, playlist URLs prefer readable `yt-dlp` playlist-title folders with the `list=` identifier as fallback, and direct individual videos from YouTube or other supported sites write to `singles/`. The root/data `urls.txt` file remains the queue file and is not moved or copied into the download directory.

After each download cycle, retention cleanup scans MP3 files recursively under the download directory, but only current YouTube channel folders are eligible. The cleanup clock is the embedded MP3 date metadata written at download completion. Playlist and single-video MP3 files are left alone. Channel files older than `retention_days` are deleted only when the source URL comment tag is also present, and the same concrete video URL is removed from `downloaded_urls.txt`.

If `yt-dlp` reports that an expanded item is already downloaded or if it completes without changing an MP3, the download service now checks the output folder for the expected file and stamps it if the file already exists. That makes partial success recoverable instead of forcing a future run to get stuck on a stale metadata state.

Configured YouTube cookies follow `always_use_cookies` in `config.ini`. When true (default), YouTube `yt-dlp` calls pass the configured Netscape-format cookie file on the first attempt and retry once without cookies on failure. When false, the order is inverted: plain first, cookies on retry. In Docker, the simplest path is putting `cookies.txt` in the mounted data directory. The file is ignored by git because it contains browser authentication state.

### Security posture of the web UI

The UI uses a deliberately simple login model:

- Password is read from `.ui_password`.
- Docker now stores a PBKDF2 hash in `.ui_password`, but if a repo-root `.ui_password` exists when the image is built it is copied into the mounted data directory on first boot before any default is generated.
- Failed attempts are rate-limited and persisted in `.login_state.json`.
- Sessions are persisted to `.ui_sessions.json` and restored after app restarts until they expire.
- Session cookies now carry an explicit max age.
- Session validity is not tied to the authenticating IP address; only login failure bans use client IP.
- Reopening `/` or `/login` with a valid remembered session now goes directly to `/ui` instead of showing the password form again.
- The code-level fallback is to ignore `X-Forwarded-For`, but the checked-in `config.ini` explicitly enables it for reverse-proxy deployments.
- Login HTML responses now send no-store and anti-framing headers, and anonymous login CSRF tokens expire instead of accumulating forever.
- Failed login attempts now return to the HTML login form with an inline error banner instead of a raw JSON body.
- The queue page now uses a nonce-based Content Security Policy so its activity viewer can run without allowing arbitrary inline JavaScript.

That distinction is important. Trusting forwarded headers on a directly exposed app lets clients spoof their source IP and bypass the ban logic.

### Docker bootstrap behavior

The container runtime now treats the mounted data directory as the durable source of truth, but it no longer assumes that directory is pre-populated.

- If `/data/config.ini` does not exist, the Docker entrypoint copies the repo's checked-in `config.ini` into place.
- If queue or state files are missing, the entrypoint creates them.
- If mounted `.ui_password` is missing but the image contains `/app/.ui_password`, the entrypoint copies that file into the mounted data directory first. If no password file exists anywhere, or if the mounted file is blank or still contains the legacy `CHANGE_ME` value, the entrypoint writes a PBKDF2 hash for the default password `.ui_password`. Existing plain-text passwords are also rewritten as hashes in place.
- `yt-dlp` auto-update is enabled by default through `YT_DLP_AUTO_UPDATE=true`, but update failures are logged and do not stop the container from starting.
- The scheduled 48-hour path upgrades only the `yt-dlp` package, then waits 5 minutes before starting downloads so the updated binary has settled. If a UI-triggered download arrives during that delay, the scheduler handles the UI trigger and skips that full scheduled queue pass.
- Direct-video UI submissions trigger an immediate single-URL run for the submitted video only. Channel and playlist submissions wait for the scheduled full-queue run.
- The scheduler interval comes from `DOWNLOAD_INTERVAL_HOURS`, and the Python startup path now refuses `0`, negative numbers, and non-integer values so a bad Compose override does not create a crash loop or tight polling loop.
- Scheduler subprocesses run `python -m src.cli` from the resolved project root, so scheduled and immediate Docker downloads do not depend on the scheduler process's current working directory.

This matters because a first-time Docker deployment now inherits the repo defaults instead of silently falling back to the code-level defaults.

## Root Tree

```text
podcast-downloader/
├── Dockerfile
├── config.ini
├── docs/
├── docker-compose.yml
├── docker-entrypoint.sh
├── activity.log
├── download.log
├── downloaded_urls.txt
├── downloads/
├── main.py
├── pyproject.toml
├── src/
├── start.py
├── test_sponsorblock.py
├── tests/
├── urls.txt
└── uv.lock
```

## Subfolder Overview

### `src/`

- Responsibility: application code for CLI, downloader adapter, download service, file-backed state stores, config loading, API, and URL normalization.
- Key files: `cli.py`, `downloader.py`, `downloads/`, `state/`, `api.py`, `url_utils.py`, `config.py`.
- Artifacts: writes into the root-level queue, archive, bypass-age file, diagnostic log, activity log, and downloads folders.

### `tests/`

- Responsibility: automated regression coverage for security-sensitive behavior and downloader correctness.
- Key files: `test_security.py`, `test_api_behavior.py`, `test_downloader.py`, `test_url_utils_behavior.py`.
- Artifacts: no durable project artifacts; only local pytest cache when tests run.

### `docs/`

- Responsibility: Docusaurus-ready project documentation for users and operators.
- Key files: `intro.md`, `architecture.md`, `web-ui-security.md`, `review-and-safety.md`.
- Artifacts: Markdown docs only. See `docs/GUIDE_docs.md` for the full map.

### `downloads/`

- Responsibility: output folder for extracted MP3 files.
- Key files: generated audio files only.
- Artifacts: final deliverables consumed by the user, grouped into source folders such as `channel-one/`, `playlist-name1/`, and `singles/`.

## Code Reference

### Root files

- [`main.py`](/Users/gwh/projects/one-time-projects/podcast-downloader/main.py): one-line handoff into the packaged CLI.
- [`config.ini`](/Users/gwh/projects/one-time-projects/podcast-downloader/config.ini): editable operational defaults.
- [`start.py`](/Users/gwh/projects/one-time-projects/podcast-downloader/start.py): container entrypoint that keeps the web server tied to PID 1 and dispatches scheduled full-queue runs plus direct-video single-URL immediate runs.
- [`docker-entrypoint.sh`](/Users/gwh/projects/one-time-projects/podcast-downloader/docker-entrypoint.sh): Docker bootstrap script for config seeding, state-file creation, hashed UI password setup, and best-effort `yt-dlp` updates.
- [`Dockerfile`](/Users/gwh/projects/one-time-projects/podcast-downloader/Dockerfile): image definition for the deployable container.
- [`docker-compose.yml`](/Users/gwh/projects/one-time-projects/podcast-downloader/docker-compose.yml): default Compose deployment for local or VPS use.
- [`test_sponsorblock.py`](/Users/gwh/projects/one-time-projects/podcast-downloader/test_sponsorblock.py): manual live-network debugging script.

### Common workflows

- Install dependencies: `uv sync --dev`
- Run downloader: `uv run python main.py`
- Queue a direct URL and bypass the age gate once: `uv run python main.py --add-url "https://www.youtube.com/watch?v=..." --skip-age-check`
- Run exactly one direct video from the queue through the single-item path: `uv run python main.py --download-single-url "https://videos.example.com/watch/episode-1"`
- Run web UI: `uv run uvicorn src.api:app --host 127.0.0.1 --port 8000`
- Run tests: `uv run python -m pytest -q`
- Run SponsorBlock smoke script manually: `uv run python test_sponsorblock.py`

## Journal

- 2026-05-16: YouTube channel expansion now uses `/videos` for bare channels and preserves explicit `/streams` URLs for livestream-only monitoring.
- 2026-05-15: Direct YouTube downloads now try without cookies first and retry once with a configured cookie file only after the plain attempt fails.
- 2026-06-07: Added `always_use_cookies` so YouTube cookie usage can stay fallback-only or switch to always-on across downloads, expansion, and metadata.
- 2026-04-30: Corrected direct-video completion behavior so one-off URLs are removed from the queue without being written to the expanded-item archive.
- 2026-04-30: Downloaded MP3 files now expose local completion time through embedded date metadata so Audiobookshelf shows the download date.
- 2026-04-30: Direct-video UI additions now trigger only a single-URL immediate run; channel and playlist additions remain queued for the scheduled full-queue cycle.
- 2026-04-28: Non-YouTube web video URLs are allowed as single direct downloads, while YouTube remains the only source type with channel/playlist expansion and SponsorBlock cleanup.
- 2026-06-02: Playlist sources now use `channel_count` as the default latest-entry cap and prefer readable playlist titles for output folder names.
- 2026-05-03: Direct Shorts skips now remove the skipped URL from the queue, date-only YouTube age checks wait conservatively until the configured hour threshold has elapsed after the upload date, `yt-dlp` `NA` timestamps fall back to upload dates, and `is_youtube_short_url()` makes the YouTube-only `/shorts/` rule explicit.
- 2026-05-03: MP3 date metadata rewrites now avoid temporary `.mp3` filenames and preserve the final MP3 inode so Audiobookshelf does not see a duplicate episode during scans.
- 2026-05-03: Remembered UI sessions now skip the login page when reopening `/` or `/login`.
- 2026-05-04: The web UI now reads concise `activity.log` events while `download.log` stays as the full diagnostic log.
- 2026-05-05: Config validation now rejects out-of-range values and blank paths, archive-backed expanded downloads are serialized under the archive lock, and Docker scheduler subprocesses run the package CLI from the project root.
- 2026-05-06: File-backed queue, archive, bypass, and activity-log behavior moved into `src/state/` stores so persistence rules have one owner.
- 2026-05-15: YouTube `/live/VIDEO_ID` URLs now normalize to standard watch URLs so completed livestreams are treated like ordinary videos without archiving direct downloads.
- 2026-05-15: MP3 outputs now route into direct source folders under `downloads/`, and retention cleanup deletes only YouTube channel files older than the configurable embedded-download-date window while removing their URLs from the archive.
