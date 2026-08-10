---
title: Review and Safety Notes
sidebar_position: 6
---

# Review and Safety Notes

This page captures the current review outcome for the repository.

## Changes made during this review

### 1. Queue-file race fixed

`urls.txt` updates now use an interprocess file lock. This prevents lost URLs when:

- the downloader is removing a completed URL
- the browser UI is appending a new URL at the same time

### 2. UI Content Security Policy fixed

The queue page previously shipped a strict Content Security Policy while also depending on inline JavaScript and an inline `onclick` handler for the browser activity viewer. That combination breaks the refresh behavior in modern browsers.

The page now:

- uses a per-response nonce for the inline script
- removes inline event-handler attributes
- explicitly allows same-origin `fetch()` requests to `/logs`

### 3. Config validation tightened

Malformed numeric values in `config.ini` now fail fast with a `ConfigError` instead of silently falling back to defaults. Out-of-range values now fail too, including `channel_count < 1`, `min_channel_video_age_hours < 0`, and `delay_seconds < 0`. Blank path settings also fail before they can collapse to the data directory.

### 4. Archive-backed download race fixed

Expanded channel and playlist URLs now hold the archive lock across duplicate detection, the download attempt, and the success append. That prevents two downloader processes from doing the same expanded URL at the same time while still leaving failed attempts retryable.

### 5. Scheduler update handling tightened

Failed `yt-dlp` package updates now log a warning, report the current installed version, and skip the post-update wait.

### 6. Scheduler subprocess invocation hardened

The Docker scheduler now launches `python -m src.cli` from the resolved project root instead of relying on a relative `main.py` path.

### 7. Artifact recovery scoped to the active source

MP3 snapshots and zero-delta metadata recovery now inspect only the current source work folder. The former intermediate-tree scan could mistake the sole MP3 from another source for the current URL's output. Output filenames now include the extractor media ID so equal channel-title pairs do not collide.

### 8. Optional live smoke dependency isolated

`scripts/sponsorblock_smoke_check.py` imports the optional `yt-dlp` Python package only when the script is run directly. The documented offline pytest command can therefore collect the repository without that separately installed package. The smoke script uses the same `sponsor` and `selfpromo` categories as production.

## Verification performed

- `uv run python -m pytest -q`
- `uv run ruff check .`
- `uv run python -m compileall src tests start.py main.py`

## Current residual risks

### Operational

- The project still depends on `yt-dlp`, `ffmpeg`, and upstream YouTube behavior.
- SponsorBlock quality depends on upstream community-submitted segment data.

### Security

- The web UI is appropriate for personal admin use, not broad public exposure.
- Login is still one shared account (username and password from `.env`), not per-user authentication.
- In-memory sessions mean a process restart logs everyone out.

### Product behavior

- Channel and playlist expansion remain dependent on `yt-dlp` output format.
- The app is designed around a single queue and a single operator, not multi-user workflows.
