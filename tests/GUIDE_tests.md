# Tests Guide

## Purpose

[`tests/`](/Users/gwh/projects/one-time-projects/podcast-downloader/tests) contains the automated regression coverage for the project. These tests are intentionally narrow and operational: they focus on the places where subtle changes can quietly break security or downloader correctness.

The folder exists to catch regressions in three areas:

1. Queue and URL handling behavior.
2. Web UI security behavior.
3. Download success detection semantics.
4. File-backed state locking and store behavior.

## Test Strategy

The suite avoids live network downloads. Instead, it uses behavioral contract tests and monkeypatched subprocess calls where necessary.

That choice is deliberate:

- The downloader depends on external services and `yt-dlp`.
- Network tests are slow and flaky.
- The important logic to protect is mostly local policy: command construction, URL normalization, session checks, and how subprocess outcomes are interpreted.

The separate root-level `test_sponsorblock.py` script remains available for manual live-network verification when needed.

## Folder Tree

```text
tests/
├── GUIDE_tests.md
├── test_activity_log.py
├── test_archive_locking.py
├── test_cli_behavior.py
├── test_config.py
├── test_api_behavior.py
├── test_downloader.py
├── test_security.py
├── test_start.py
└── test_url_utils_behavior.py
```

- `test_archive_locking.py`: covers downloaded archive locking for concurrent reads and writes.
- `test_activity_log.py`: covers concise activity-log path derivation, locked reads during writes, and tail reading.
- `test_cli_behavior.py`: covers CLI-only queue append behavior such as age-gate bypass marking, config validation failures, and `python -m src.cli` module execution.
- `test_config.py`: covers strict config validation for numeric ranges, retention settings, and blank path settings.
- `test_api_behavior.py`: covers forwarded-header trust defaults, persistent session behavior, Cloudflare HTTPS handling, monitored-URL rendering, queue removal, activity-log display, and immediate single-URL trigger policy.
- `test_downloader.py`: covers the file-change based success criterion, source-folder output routing, MP3 date and source URL metadata stamping, channel-only retention cleanup, recoverable partial-success handling, concise activity events, direct URL queue/archive behavior, completed-livestream queue cleanup, concurrent archive-backed download serialization, and single-URL age-gate behavior in the downloader.
- `test_security.py`: covers command separator usage, YouTube channel tab expansion, password authentication behavior, timing-safe password comparison, session expiry, and URL utility regressions.
- `test_start.py`: covers Docker scheduler interval validation in `start.py`.
- `test_url_utils_behavior.py`: covers queue-file locking, sample queue creation for nested paths, and YouTube host/live URL normalization.

## Code Reference

### `test_security.py`

- Responsibility: long-lived security and normalization regressions already present in the project.
- Key checks:
  - `yt-dlp` command includes `--` before the user URL.
  - bare YouTube channel URLs expand through `/videos`, explicit `/videos` stays upload-only, and explicit `/streams` stays livestream-only.
  - login accepts the correct configured password and rejects an incorrect password.
  - password hash and legacy plain-text comparison reject near misses.
  - expired sessions are rejected.
  - URL normalization and Shorts/channel detection behave as expected.

### `test_activity_log.py`

- Responsibility: protect the concise activity feed shown in the browser.
- Key checks:
  - `activity.log` is derived from the directory containing `download.log`.
  - `activity.log` and `download.log` timestamps use Toronto/Eastern time and omit seconds.
  - only the requested number of recent activity lines are returned.
  - a missing activity file shows a short empty-state message.
  - `ActivityLogStore` can write concise events and read a bounded tail.

### `test_api_behavior.py`

- Responsibility: new behavior around trusted proxy configuration and persistent sessions.
- Key checks:
  - forwarded headers are ignored unless explicitly enabled.
  - forwarded headers are honored when explicitly enabled.
  - remembered sessions persist across restarts and are not IP-bound.
  - remembered sessions skip the login form when reopening `/` or `/login`.
  - the queue UI emits a CSP nonce and avoids inline event handlers.
  - the immediate-download checkbox label follows the configured threshold and disappears when the gate is disabled.
  - direct-video UI additions enqueue a single immediate URL whether or not the checkbox is checked.
  - non-YouTube direct-video submissions do not write to the YouTube-only bypass file.
  - channel/list UI additions do not enqueue an immediate full-queue run.
  - the queue UI renders current `urls.txt` entries with remove controls.
  - removing a monitored URL updates `urls.txt` and redirects with the expected success message.

### `test_cli_behavior.py`

- Responsibility: protect CLI queue append semantics that do not go through FastAPI.
- Key checks:
  - `--skip-age-check` writes the normalized direct YouTube video URL into the bypass file when adding from the shell.
  - `python -m src.cli --help` runs the same CLI module used by the Docker scheduler.

### `test_config.py`

- Responsibility: protect startup config validation before the CLI, API, or scheduler can run with surprising values.
- Key checks:
  - `channel_count` must be at least `1`.
  - playlist expansion passes `channel_count` to `yt-dlp --playlist-end` so large playlists are not fully enumerated by default.
  - `min_channel_video_age_hours` must be at least `0`.
  - `delay_seconds` must be at least `0`.
  - `retention_days` must be at least `1`.
  - configured path strings must not be blank.

### `test_downloader.py`

- Responsibility: downloader success detection around MP3 file changes.
- Key checks:
  - overwriting an existing MP3 still counts as success.
  - channel, playlist, and direct-video downloads write MP3 files into direct source folders under the configured output directory.
  - the `yt-dlp` command disables source modification time preservation.
  - the post-download `ffmpeg` pass writes MP3 date metadata to the local completion time.
  - the same metadata pass writes the source URL to the MP3 comment tag, with YouTube live and short links normalized to canonical watch URLs.
  - retention cleanup deletes only old YouTube channel MP3 files, removes their concrete URLs from `downloaded_urls.txt`, and leaves playlist, single-video, missing-date, and missing-source-URL files alone.
  - the post-download metadata pass does not expose a second `*.mp3` file to library scanners while rewriting tags.
  - the post-download metadata pass preserves the final MP3 inode so Audiobookshelf does not see remove/add replacement events.
  - a failed MP3 metadata pass leaves the URL queued for retry.
  - exit code `0` without any MP3 creation or modification still counts as failure.
  - failed non-YouTube download attempts are logged and left in the queue.
  - concise activity events are written without raw downloader error output.
  - successful direct queue and immediate single-video downloads are removed from `urls.txt` without entering `downloaded_urls.txt`.
  - completed livestreams are removed from `urls.txt` when the same video is processed through the ordinary watch URL.
  - concurrent archive-backed expanded downloads do not run `yt-dlp` twice for the same URL.
  - immediate single-URL YouTube attempts honor the configured age gate unless the URL is in the bypass file.

### `test_start.py`

- Responsibility: protect Docker startup behavior against invalid scheduler settings.
- Key checks:
  - positive integer intervals are accepted.
  - `0`, negative integers, and malformed strings are rejected before the scheduler starts.
  - immediate scheduler subprocesses run `python -m src.cli` from the project root.
  - a plain scheduled-interval timeout does not clear a UI trigger that may arrive at the timeout boundary.

### `test_url_utils_behavior.py`

- Responsibility: protect queue-file correctness under real concurrent file access.
- Key checks:
  - nested queue paths can create a sample `urls.txt` without crashing.
  - appending a URL waits for an in-progress locked rewrite instead of losing data.
  - appending and reading accepts non-YouTube web video URLs.
  - removing a monitored URL matches normalized video URLs and leaves unrelated entries untouched.
  - `QueueStore`, `ArchiveStore`, and `BypassStore` preserve the same normalized storage behavior as the compatibility wrappers.
  - `ArchiveStore.remove()` rewrites the archive without duplicating entries.
  - `yt-dlp` `NA` metadata placeholders do not block upload-date age checks.
  - `is_youtube_short_url()` treats `/shorts/` paths as Shorts only on YouTube hosts.

### `test_archive_locking.py`

- Responsibility: protect `downloaded_urls.txt` against concurrent UI reads and downloader writes.
- Key checks:
  - archive reads wait for an in-progress exclusive rewrite and then see the latest contents.
  - archive appends wait for the same rewrite instead of losing the new URL.

## How To Run

```bash
uv run python -m pytest -q
```

Run that from the project root. The suite should remain fast and offline.
