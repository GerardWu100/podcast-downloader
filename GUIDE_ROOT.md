# Root guide

## Project map

Podcast Downloader is one Python application with three entry points:

1. The command line reads the queue and downloads audio.
2. The FastAPI web interface manages the queue, sign-in, cookies, and logs.
3. The JSON API at `/api` accepts URLs from the Chrome extension and other
   programs, using the web interface's accounts.

The root contains deployment entry points and operator-owned files. Application
code lives in [`src/`](src/), offline tests in [`tests/`](tests/), and
user/operator documentation in [`docs/`](docs/).

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
├── extension/
├── tests/
├── docs/
├── pyproject.toml
└── uv.lock
```

`extension/` is browser code, not server code. `.dockerignore` excludes it, and
nothing in `src/` imports it.

Runtime state stays in plain files:

| File | Owner | Purpose |
|---|---|---|
| `urls.txt` | `QueueStore` | Monitored sources and direct URLs |
| `downloaded_urls.txt` | `ArchiveStore` | Successfully expanded items |
| `bypass_age_check_urls.txt` | `BypassStore` | One-use YouTube age overrides |
| `.ui_sessions.json` | `AuthStore` | Browser sessions |
| `.login_state.json` | `AuthStore` | Login failures and temporary bans |
| `activity.log` | `ActivityLogStore` | Short messages for the web interface |
| `download.log` | Python logging | Detailed diagnostics |

State stores use advisory locks so concurrent processes do not overwrite one
another. Authentication files are written to a temporary sibling and then
moved into place, so an interrupted write cannot leave a partial JSON file.

## Root files

- `README.md`: setup, usage, configuration, limits, and links to detailed docs.
- `main.py`: wrapper that calls `src.cli.main()`.
- `start.py`: Docker supervisor. It runs Uvicorn in the main process and starts
  scheduled downloads.
- `config.ini`: checked-in runtime defaults.
- `docker-entrypoint.sh`: prepares mounted state, `.env`, and cookies; updates
  `yt-dlp`; repairs ownership; and starts the app as the configured host user.
- `Dockerfile` and `docker-compose.yml`: container build and default deployment.
- `pyproject.toml` and `uv.lock`: runtime and development dependencies.
- `scripts/sponsorblock_smoke_check.py`: optional live check, kept outside
  `tests/` so the offline suite does not collect it.

Useful commands:

```bash
uv sync --dev
uv run python main.py
uv run uvicorn src.api:app --host 127.0.0.1 --port 8000
uv run python -m pytest -q
```

## Journal

- 2026-07-26: Split web, media, download, and state ownership and removed the old adapter modules.
- 2026-08-08: Stopped tracking runtime queue state, moved the live smoke check to `scripts/`, and excluded runtime files from the Docker build.
- 2026-08-10: Made download timeouts configurable, added log rotation and bounded browser log reads, and removed stale engineering records.
- 2026-08-19: Docker startup began repairing mounted directories and running the app as `HOST_UID:HOST_GID`.
- 2026-08-23: Docker and scheduler updates moved to nightly `yt-dlp` with the `curl-cffi` extra for Rumble.
- 2026-08-26: Added the Chrome extension and its JSON API. The shared queue
  rules moved to `queue_actions.py`, and account checks plus the failed-login
  ban moved to `account_auth.py`. The API uses the web account in an
  `Authorization: Basic` header because the session cookie is `HttpOnly` and
  `SameSite=lax`; no extra server secret is needed.
