# Architecture Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Find likely bugs, reduce accidental coupling, and make the project easier to reason about without turning a small personal downloader into an overbuilt platform.

**Architecture:** Keep plain files as the durable state store for now, but put all file-backed state behind explicit store objects. Split URL policy, download execution, web authentication, and scheduler dispatch so each boundary has one owner and one set of tests.

**Tech Stack:** Python 3.13, FastAPI, `yt-dlp`, `ffmpeg`, `uv`, pytest, locked text files using `fcntl`.

---

## Current Architecture Criticism

The project works, and the test suite currently passes, but the design is brittle in the exact places where download tools usually fail: state mutation, subprocess calls, and web entrypoints.

| Area | Current shape | Criticism | Risk |
|---|---|---|---|
| Web UI | `src/api.py` is 972 lines of routing, authentication, state persistence, HTML, CSS, and JavaScript | This is a "god module": one file owns too many reasons to change | Security bugs and UI bugs become hard to isolate |
| URL layer | `src/url_utils.py` validates URLs, normalizes YouTube links, expands channels, edits queue files, edits archive files, and edits bypass files | URL policy and file storage are mixed together | A URL parsing change can accidentally affect persistence behavior |
| Downloader | `src/downloader.py` builds commands, runs subprocesses, detects file changes, stamps MP3 metadata, updates queues, updates archives, and writes activity logs | Orchestration and side effects are fused | Retry bugs and partial-success bugs are likely |
| State | Queue, archive, bypass, activity log, login state, and session state are handled by scattered functions | There is no explicit state boundary | Concurrency rules are inconsistent |
| Scheduler | `start.py` shells out to `main.py` by relative path and uses an in-memory trigger queue | Runtime behavior depends on current working directory and process lifetime | UI-triggered downloads can be delayed or lost after restart |
| Config | `load_config()` silently falls back on malformed numeric values | Bad config can look like a successful startup | Operational mistakes are hidden |
| Tests | Good regression coverage exists, but many tests inspect implementation source or patch private methods | Tests protect symptoms more than contracts | Refactors will be noisy unless public seams are introduced |

## Potential Bugs To Hunt First

1. **Partial MP3 success can poison retries.** If `yt-dlp` creates an MP3 but the metadata stamping step fails, the URL stays queued. On the next run, `yt-dlp` may skip or reuse the existing MP3, the file snapshot may show no change, and the downloader can fail forever even though the audio file exists.
2. **Concurrent downloader processes can duplicate work.** `PodcastDownloader` loads `downloaded_urls.txt` once at construction. If two processes start close together, both can see the same URL as not archived and both can download it before either writes the archive.
3. **Activity log reads and writes are not locked.** `activity.log` can be read by the web UI while the downloader is appending. The usual result is harmless, but partial lines or platform-dependent read behavior are possible.
4. **Session and login state are not safe across multiple web workers.** The code uses process-local globals plus JSON files without file locks for all paths. One Uvicorn worker is fine; two workers are not.
5. **Configuration mistakes are hidden.** Invalid `channel_count`, `delay_seconds`, or `min_channel_video_age_hours` values silently default or clamp. A negative channel count can flow into `yt-dlp --playlist-end` in surprising ways.
6. **Logger handler lifecycle is leaky.** `_setup_logging()` clears handlers on a named logger but does not close old file handlers. It is low impact in the current subprocess-heavy scheduler, but it is a real bug if the downloader is reused in-process.
7. **YouTube host parsing is too exact.** `is_youtube_url()` does not normalize host case or strip ports. Valid URLs such as uppercase hosts may skip YouTube-specific policy.
8. **The scheduler update flag is misleading.** `update_ytdlp()` returns `True` even when the package update fails, which still triggers the post-update delay.

## Target File Structure

Create focused subpackages and keep compatibility shims so the refactor can be staged safely.

```text
src/
├── api.py                         # compatibility shim: exports app
├── cli.py                         # command-line parsing only
├── config.py                      # validated runtime config
├── state/
│   ├── __init__.py
│   ├── file_locks.py              # shared locked text-file helpers
│   ├── queue_store.py             # urls.txt read, append, remove
│   ├── archive_store.py           # downloaded_urls.txt read, append, claim
│   ├── bypass_store.py            # one-shot age bypass state
│   ├── activity_store.py          # activity.log write and tail
│   └── auth_store.py              # login/session JSON persistence
├── media/
│   ├── __init__.py
│   ├── urls.py                    # generic URL validation and normalization
│   └── youtube.py                 # YouTube classification, expansion, age metadata
├── downloads/
│   ├── __init__.py
│   ├── ytdlp_client.py            # command building and subprocess execution
│   ├── audio_metadata.py          # ffmpeg metadata stamping
│   └── service.py                 # download orchestration
├── web/
│   ├── __init__.py
│   ├── app.py                     # create_app()
│   ├── auth.py                    # login, logout, session, CSRF
│   ├── routes.py                  # queue and log endpoints
│   └── templates.py               # HTML rendering strings
└── runtime.py                     # shared run_downloader() entrypoint
```

Do not move everything at once. Each task below creates one stable seam first, then migrates callers.

## Task 1: Baseline Bug Tests

**Files:**
- Modify: `tests/test_downloader.py`
- Modify: `tests/test_url_utils_behavior.py`
- Modify: `tests/test_activity_log.py`
- Modify: `tests/test_api_behavior.py`
- Modify: `tests/test_start.py`

- [ ] Add a regression test showing that metadata-stamp failure after MP3 creation does not make a retry impossible. The expected final behavior is: if a prior run created an MP3 but failed while stamping metadata, the next run can stamp the existing file and remove the URL from the queue.
- [ ] Add a regression test showing two downloader instances do not both download the same archived expanded URL. Use two `PodcastDownloader` objects with the same archive file and assert the second object reloads or claims archive state before download.
- [ ] Add a regression test for locked `activity.log` reads during writes. The expected behavior is: the UI receives whole lines only.
- [ ] Add tests for YouTube URL host normalization: uppercase host, trailing default port, and `m.youtube.com`.
- [ ] Add config tests for invalid numeric values. The expected behavior is a clear `ValueError` naming the bad key, not a silent fallback.
- [ ] Add a scheduler test showing a failed `yt-dlp` package update does not trigger the post-update wait.

Run:

```bash
uv run python -m pytest tests/test_downloader.py tests/test_url_utils_behavior.py tests/test_activity_log.py tests/test_api_behavior.py tests/test_start.py -q
```

Expected before implementation: the new tests fail for the reasons listed above.

## Task 2: Centralize File-Backed State

**Files:**
- Create: `src/state/__init__.py`
- Create: `src/state/file_locks.py`
- Create: `src/state/queue_store.py`
- Create: `src/state/archive_store.py`
- Create: `src/state/bypass_store.py`
- Create: `src/state/activity_store.py`
- Modify: `src/url_utils.py`
- Modify: `src/activity_log.py`
- Modify: `tests/test_url_utils_behavior.py`
- Modify: `tests/test_archive_locking.py`
- Modify: `tests/test_activity_log.py`

- [ ] Move `_locked_file()` into `src/state/file_locks.py` and make it the only low-level advisory lock helper.
- [ ] Move queue mutation functions into `QueueStore`: read valid entries, append normalized entries, remove direct video entries, and remove monitored entries.
- [ ] Move archive functions into `ArchiveStore`: load, append, and `claim(url)` under an exclusive lock. `claim(url)` should return `True` exactly once for a URL.
- [ ] Move bypass functions into `BypassStore`: load, add, and remove.
- [ ] Move activity log helpers into `ActivityLogStore`, using the same lock helper for append and tail reads.
- [ ] Leave thin wrappers in `url_utils.py` and `activity_log.py` for existing imports during the transition. Mark those wrappers as compatibility only in docstrings.

Run:

```bash
uv run python -m pytest tests/test_url_utils_behavior.py tests/test_archive_locking.py tests/test_activity_log.py -q
```

Expected after implementation: queue, archive, bypass, and activity tests pass with storage behavior owned by `src/state/`.

## Task 3: Split URL Policy From Persistence

**Files:**
- Create: `src/media/__init__.py`
- Create: `src/media/urls.py`
- Create: `src/media/youtube.py`
- Modify: `src/url_utils.py`
- Modify: `tests/test_url_utils_behavior.py`
- Modify: `tests/test_security.py`

- [ ] Move generic URL validation into `src/media/urls.py`.
- [ ] Move YouTube host detection, video normalization, Shorts detection, channel/playlist detection, age checks, metadata fetching, and expansion into `src/media/youtube.py`.
- [ ] Normalize host names with `parsed.hostname.lower()` instead of raw `parsed.netloc`.
- [ ] Preserve the `--` separator in every `yt-dlp` call.
- [ ] Keep `url_utils.py` as a narrow compatibility facade that imports from `state` and `media`.

Run:

```bash
uv run python -m pytest tests/test_url_utils_behavior.py tests/test_security.py -q
```

Expected after implementation: URL behavior is unchanged except the new host-normalization tests pass.

## Task 4: Make Download Execution Recoverable

**Files:**
- Create: `src/downloads/__init__.py`
- Create: `src/downloads/ytdlp_client.py`
- Create: `src/downloads/audio_metadata.py`
- Create: `src/downloads/service.py`
- Modify: `src/downloader.py`
- Modify: `tests/test_downloader.py`

- [ ] Move `yt-dlp` command construction and subprocess execution into `YtDlpClient`.
- [ ] Move MP3 snapshot and changed-file detection into a small download result helper.
- [ ] Move `ffmpeg` date metadata stamping into `AudioMetadataWriter`.
- [ ] Add recovery behavior for partial MP3 success: when `yt-dlp` reports "already downloaded" or produces no changed MP3, inspect the expected output folder for the target MP3 and stamp it if it lacks the project date metadata.
- [ ] Replace the constructor-level archive cache with per-URL archive claiming for expanded items. For expanded URLs, call `ArchiveStore.claim(url)` immediately before downloading. If it returns `False`, skip the download.
- [ ] Keep `src/downloader.py` as the public `PodcastDownloader` adapter until all callers use `src/downloads/service.py` directly.
- [ ] Close replaced logger handlers before clearing them.

Run:

```bash
uv run python -m pytest tests/test_downloader.py tests/test_archive_locking.py -q
```

Expected after implementation: metadata retry, archive claim, and existing downloader behavior all pass.

## Task 5: Validate Runtime Configuration Explicitly

**Files:**
- Modify: `src/config.py`
- Modify: `src/cli.py`
- Modify: `start.py`
- Create or modify: `tests/test_config.py`
- Modify: `tests/test_start.py`

- [ ] Add a `ConfigError(ValueError)` exception with the config key in its message.
- [ ] Validate `channel_count >= 1`.
- [ ] Validate `min_channel_video_age_hours >= 0`.
- [ ] Validate `delay_seconds >= 0`.
- [ ] Validate configured path strings are non-empty after stripping whitespace.
- [ ] Make CLI startup print one clear error and exit with code `1` on `ConfigError`.
- [ ] Keep `DOWNLOAD_INTERVAL_HOURS` validation in `start.py`, but align its error style with `ConfigError`.
- [ ] Update `config.ini` comments to state accepted ranges.

Run:

```bash
uv run python -m pytest tests/test_config.py tests/test_cli_behavior.py tests/test_start.py -q
```

Expected after implementation: malformed config fails early and no numeric config silently defaults.

## Task 6: Split The Web UI Into Auth, Routes, And Templates

**Files:**
- Create: `src/web/__init__.py`
- Create: `src/web/app.py`
- Create: `src/web/auth.py`
- Create: `src/web/routes.py`
- Create: `src/web/templates.py`
- Modify: `src/api.py`
- Modify: `tests/test_api_behavior.py`
- Modify: `tests/test_security.py`

- [ ] Create `create_app(config, stores, trigger)` in `src/web/app.py`.
- [ ] Move password verification, login state, sessions, CSRF tokens, cookies, and security headers into `src/web/auth.py`.
- [ ] Store login and session state through `AuthStore` from `src/state/auth_store.py`, with file locks for JSON reads and writes.
- [ ] Move route handlers for `/ui`, `/logs`, `/add-url`, and `/remove-url` into `src/web/routes.py`.
- [ ] Move HTML rendering into `src/web/templates.py`.
- [ ] Keep `src/api.py` as a small compatibility shim:

```python
"""FastAPI compatibility entrypoint for uvicorn."""

from __future__ import annotations

import os
from pathlib import Path

from .config import load_config
from .web.app import create_app

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("PODCAST_DATA_DIR", str(PROJECT_ROOT)))
CONFIG = load_config(DATA_DIR / "config.ini", DATA_DIR)
app = create_app(CONFIG)
```

- [ ] Adjust tests to call the smaller auth helpers and app factory instead of mutating module globals directly.

Run:

```bash
uv run python -m pytest tests/test_api_behavior.py tests/test_security.py -q
```

Expected after implementation: web behavior is unchanged, but `src/api.py` is no longer the main implementation file.

## Task 7: Harden Scheduler Dispatch

**Files:**
- Create: `src/runtime.py`
- Modify: `src/cli.py`
- Modify: `start.py`
- Modify: `tests/test_start.py`
- Modify: `tests/test_cli_behavior.py`

- [ ] Create `run_downloader(config, urls_file, output_dir, channel_count, single_url)` so CLI and scheduler share one runtime entrypoint.
- [ ] Keep subprocess isolation in `start.py`, but launch with `python -m src.cli` and set `cwd` to the project root resolved from `start.py`.
- [ ] Make `update_ytdlp()` return `True` only when the package update command succeeds.
- [ ] Log the current `yt-dlp` version separately from whether an update happened.
- [ ] Preserve current UI trigger behavior: direct video submissions run only the submitted URL; channel and playlist submissions wait for the next full scheduled run.

Run:

```bash
uv run python -m pytest tests/test_start.py tests/test_cli_behavior.py -q
```

Expected after implementation: scheduler behavior no longer depends on the shell current working directory, and failed package updates do not cause the post-update wait.

## Task 8: Replace Source-Inspection Tests With Contract Tests

**Files:**
- Modify: `tests/test_security.py`
- Modify: `tests/test_downloader.py`
- Modify: `tests/test_url_utils_behavior.py`

- [ ] Replace tests that inspect source text with tests that capture subprocess command lists and assert `--` appears before the URL.
- [ ] Replace broad monkeypatching of private downloader methods with tests against `YtDlpClient`, `AudioMetadataWriter`, stores, and the download service.
- [ ] Keep one high-level integration test for the full direct-video success path.
- [ ] Keep one high-level integration test for the full expanded-channel archive path.

Run:

```bash
uv run python -m pytest tests/test_security.py tests/test_downloader.py tests/test_url_utils_behavior.py -q
```

Expected after implementation: tests describe public contracts and tolerate internal file movement.

## Task 9: Update Documentation And Guides

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/cli-and-config.md`
- Modify: `docs/operations.md`
- Modify: `docs/review-and-safety.md`
- Modify: `GUIDE_ROOT.md`
- Modify: `src/GUIDE_src.md`
- Modify: `tests/GUIDE_tests.md`
- Modify: `docs/GUIDE_docs.md`

- [ ] Update the architecture docs to show the new `state`, `media`, `downloads`, and `web` boundaries.
- [ ] Update the CLI and config docs to explain config validation and accepted numeric ranges.
- [ ] Update operations docs to explain scheduler subprocess invocation and `yt-dlp` update behavior.
- [ ] Update review and safety notes with fixed bugs and remaining risks.
- [ ] Update guide files so future agents know where state, URL policy, download execution, and web logic live.

Run:

```bash
uv run python -m pytest -q
uv run python -m compileall src tests start.py main.py
```

Expected after implementation: all automated tests pass and docs match the new architecture.

## Execution Order

1. Baseline bug tests.
2. State stores.
3. URL policy split.
4. Download recovery and archive claiming.
5. Config validation.
6. Web split.
7. Scheduler hardening.
8. Test cleanup.
9. Documentation.

This order matters because state stores are the foundation for the URL, downloader, and web refactors. The web split should happen after state is explicit, otherwise it will just move globals into smaller files without fixing the real coupling.

## Definition Of Done

- `uv run python -m pytest -q` passes.
- `uv run python -m compileall src tests start.py main.py` passes.
- Every touched module has been executed directly or through tests.
- The plan's known potential bugs either have passing regression tests or are documented as residual risks.
- `README.md`, `docs/`, `GUIDE_ROOT.md`, `src/GUIDE_src.md`, and `tests/GUIDE_tests.md` match the final code.
- Work is committed with a message such as `refactor: harden downloader architecture`.

## What Else?

- The tempting but wrong move is to add a database immediately. A database would solve some locking problems, but it would also introduce migrations, backup concerns, and deployment complexity. The better next step is explicit file stores with clear invariants.
- If this project grows beyond one operator, replace file-backed auth and queue state with SQLite. SQLite is a local relational database stored in one file; it would give atomic transactions without needing a server.
- Consider adding a `--dry-run` mode after the architecture split. It would print which URLs would download, skip, archive, or remain queued without touching MP3 files.
- Consider a small command-builder snapshot test for `yt-dlp` flags. That is cheaper and more stable than live network tests.

## TL;DR

The main architectural problem is not that the app is small. The problem is that state, policy, process execution, and HTML are tangled in large modules. First add failing tests for the likely bugs, then introduce explicit state stores, split URL policy and download execution, break up the web module, harden config and scheduler behavior, and update docs.
