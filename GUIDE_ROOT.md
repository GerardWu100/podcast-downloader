# Root Guide

## Part 1: Project Map

Podcast Downloader is one Python application with two ways in:

1. The command-line interface reads a queue file and downloads audio.
2. The FastAPI web interface manages the queue, sign-in, cookies, and logs.

The root holds deployment entrypoints and operator-owned files. Product code is
in [`src/`](src/), offline tests are in [`tests/`](tests/), and user/operator
documentation is in [`docs/`](docs/).

```text
podcast-downloader/
├── README.md
├── config.ini
├── main.py
├── start.py
├── src/
│   ├── downloads/
│   ├── media/
│   ├── state/
│   └── web/
├── tests/
├── docs/
├── pyproject.toml
└── uv.lock
```

Runtime state deliberately remains plain files:

| File | Owner | Meaning |
|---|---|---|
| `urls.txt` | `QueueStore` | Monitored sources and direct URLs |
| `downloaded_urls.txt` | `ArchiveStore` | Completed expanded items |
| `bypass_age_check_urls.txt` | `BypassStore` | One-shot YouTube age overrides |
| `.ui_sessions.json` | `AuthStore` | Remembered browser sessions |
| `.login_state.json` | `AuthStore` | Login failure and ban records |
| `activity.log` | `ActivityLogStore` | Concise browser-facing events |
| `download.log` | Python logging | Detailed diagnostics |

The state stores use advisory locks. Authentication JSON is written to a
temporary sibling file and then moved into place, so an interrupted process
does not leave a half-written document.

## Part 2: Root Files

- `README.md`: user-facing goal, setup, commands, configuration, and docs links.
- `main.py`: compatibility command that calls `src.cli.main()`.
- `start.py`: Docker process supervisor. It runs Uvicorn in the main process and
  starts `python -m src.cli` for scheduled downloads.
- `config.ini`: checked-in runtime defaults.
- `docker-entrypoint.sh`: initializes mounted state, `.env` and cookie files,
  then performs the best-effort `yt-dlp` update.
- `Dockerfile` and `docker-compose.yml`: container build and default deployment.
- `pyproject.toml` and `uv.lock`: runtime and development dependencies.
- `scripts/sponsorblock_smoke_check.py`: optional live-network check run by hand.
  It lives outside `tests/` and is not named like a test module so that the
  offline suite never collects it.

Useful commands:

```bash
uv sync --dev
uv run python main.py
uv run uvicorn src.api:app --host 127.0.0.1 --port 8000
uv run python -m pytest -q
```

## Part 3: Journal

- 2026-07-26: The refactor made `src/api.py` a deployment-only entrypoint,
  split web/media/download/state ownership, and removed the old
  `downloader.py`, `url_utils.py`, and `activity_log.py` adapters.
- 2026-08-08: Repository cleanup. `urls.txt` stopped being tracked because it is
  operator state that the app rewrites and recreates when missing; the live
  smoke script moved from the root to `scripts/`; a superseded 2025 blog draft
  under `content/` was deleted in favour of `blog/`. `.dockerignore` now excludes
  runtime state and session files that `COPY . .` was baking into the image.
- 2026-08-10: Bug-fix pass. The per-attempt download timeout became the
  configurable `download_timeout_seconds` with a one-hour default, replacing a
  hard-coded 300 seconds that could not finish a full-length episode; because a
  timed-out item is never archived, those episodes failed on every run.
  `download.log` gained rotation and bounded tail reads, `/logs` answers `401`
  instead of redirecting into the log box, and the web header states what the
  app does.
- 2026-08-10: Removed dead code and stale docs. The scheduler's batch-trigger
  path (`queue_batch_download`, `pop_batch_download_request`, and the
  `batch_requested` branch in `start.py`) was unreachable: no production caller
  ever set the flag, so it could only ever pop `False`. `AuthStore` lost the
  unreferenced `save_login_state`, and `web/routes.py` lost an `__all__` block
  that re-exported trigger functions nobody imported from there. Deleted
  `docs/superpowers/` (a completed 2026-07-26 plan describing three modules that
  no longer exist) and `docs/review-and-safety.md` (a past review's changelog
  that still claimed sessions were in-memory and lost on restart, which stopped
  being true when `AuthStore` began persisting them). The remaining-risk notes
  worth keeping moved to the README's "Known limits".
