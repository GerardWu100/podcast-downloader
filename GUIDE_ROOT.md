# Root guide

## Project map

Podcast Downloader is one Python application with three interfaces:

1. The command line reads the queue and downloads audio.
2. The web interface manages the queue, sign-in, cookies, and logs.
3. The JSON API at `/api` accepts URLs from the browser extension and other
   programs. It uses the web interface's accounts.

Root files handle deployment and operator settings. Application code is in
[`src/`](src/), offline tests are in [`tests/`](tests/), and user and operator
documentation is in [`docs/`](docs/).

The portable agent instructions and remote API client live in
[`.agents/skills/podcast-downloader-cli/`](.agents/skills/podcast-downloader-cli/SKILL.md).
The helper reads an explicitly selected `.env` with python-dotenv, using
`PODCAST_SERVER_URL` and one UI account pair. It does not load server runtime
state or change schedules. Its dependency is supplied with `uv run --with
python-dotenv`; it is not part of the deployed application.

```text
podcast-downloader/
├── README.md
├── config.toml
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

`extension/` contains browser code, not server code. The Dockerfile copies only
named runtime sources, `.dockerignore` also excludes the extension, and `src/`
does not import it.

Runtime state lives in plain files:

| File | Owner | Purpose |
|---|---|---|
| `urls.txt` | `QueueStore` | Monitored sources and direct URLs |
| `downloaded_urls.txt` | `ArchiveStore` | Successfully expanded items |
| `bypass_age_check_urls.txt` | `BypassStore` | One-use YouTube age overrides |
| `.ui_sessions.json` | `AuthStore` | Browser sessions |
| `.login_state.json` | `AuthStore` | Login failures and temporary bans |
| `activity.log` | `ActivityLogStore` | Short messages for the web interface |
| `download.log` | Python logging | Detailed diagnostics |
| `run_state.json` | `RunStateStore` | When the queue last ran, and whether one is running |
| `failed_downloads.json` | `FailedDownloadStore` | Failed attempts per video, so a dead video is dropped instead of retried forever |
| `source_folders.json` | `SourceFolderStore` | Library folder names that needed a lookup, so a failed lookup cannot move a podcast |

State stores use advisory file locks so concurrent processes do not overwrite
one another. Authentication files are written to a temporary sibling first and
then moved into place, so an interrupted write cannot leave a partial JSON file.

## Root files

- `README.md`: setup, usage, configuration, limits, and links to detailed docs.
- `main.py`: wrapper that calls `src.cli.main()`.
- `start.py`: Docker supervisor. It runs Uvicorn in the main process and runs
  the queue at a fixed time of day, 06:00 every other day by default. It also
  reports the two failures only it can see: a run that stopped before
  downloading anything, and a scheduled run that never happened.
- `config.toml`: checked-in runtime defaults, including the run hour
  (`scheduled_run_hour`) and how many days apart runs are
  (`scheduled_run_interval_days`).
- `docker-entrypoint.sh`: prepares mounted state, `.env`, and cookies; updates
  `yt-dlp`; repairs ownership; and starts the app as the configured host user.
- `Dockerfile` and `docker-compose.yml`: container build and default deployment.
- `docker-compose.example.yml` and `.github/workflows/publish-image.yml`: the
  published GHCR image and the clone-free deployment that pulls it.
- `pyproject.toml` and `uv.lock`: runtime and development dependencies.
- `scripts/publish_wiki.py`: copies `docs/` to the GitHub wiki. Run it by hand after changing `docs/`.
- `scripts/sponsorblock_smoke_check.py`: optional live check. It stays outside
  `tests/` so the offline suite does not collect it.

Useful commands:

```bash
uv sync --dev
uv run python main.py
uv run uvicorn src.api:app --host 127.0.0.1 --port 8000
uv run python -m pytest -q
```

## Journal

- 2026-09-01: The failures that used to be silent now send Apprise alerts, and `GET /api/health` lets an outside monitor catch a container that stopped running.
- 2026-09-01: Scheduled runs became a wall-clock rule instead of a countdown, the queue page gained last-run and next-run times, and a Run button starts the same pass by hand.
- 2026-07-26: Split web, media, download, and state ownership and removed the old adapter modules.
- 2026-08-08: Stopped tracking runtime queue state, moved the live smoke check to `scripts/`, and excluded runtime files from the Docker build.
- 2026-08-10: Made download timeouts configurable, added log rotation and bounded browser log reads, and removed stale engineering records.
- 2026-08-19: Docker startup began repairing mounted directories and running the app as `HOST_UID:HOST_GID`.
- 2026-08-23: Docker and scheduler updates moved to nightly `yt-dlp` with the `curl-cffi` extra for Rumble.
- 2026-08-26: Added the browser extension and JSON API. Shared queue rules
  moved to `queue_actions.py`; account checks and the failed-login ban moved to
  `account_auth.py`. The API uses the web account in an `Authorization: Basic`
  header because the session cookie is `HttpOnly` and `SameSite=lax`.
- 2026-08-26: Added the Firefox build. Firefox needs a separate manifest for
  its event-page model, stable add-on id, and `options_ui` setting. The build
  script assembles the shared files into `build/firefox-extension/`; Chrome
  still loads `extension/` directly.
- 2026-08-26: `build/` joined `.dockerignore`. It was in `.gitignore` but not
  `.dockerignore`, so after anyone ran the Firefox extension build,
  `docker compose up --build` would have copied that browser code into the
  server image. `tests/test_docker_build_context.py` now names every folder
  that must stay out of the build context, including generated folders, because
  a missing entry is invisible on a clean checkout.
- 2026-08-27: Docker images stopped copying the repository wholesale. Compose
  now supplies `.env` as a runtime secret, cookies stay only in the data mount,
  and explicit runtime copies plus ignore rules keep credentials, cookies, and
  notification keys out of image layers.
- 2026-10-10: Removed the dated AI review notes (`astra_thoughts_*.md`, `fable_thoughts_*.md`). Their goal statement now lives in `AGENTS.md`, and their findings are fixed or tracked there.
- 2026-10-10: Removed the generated `CODE_EXPLAINED.html`. It went stale after each code change; `docs/architecture.md` and the folder guides cover the same ground.
- 2026-10-11: Added the drop rule: a video is dropped after `max_download_attempts` failures that blame the video. Hang recovery (a watchdog or Docker `HEALTHCHECK`) and a PO-token helper container were considered and declined; Docker's restart policy ignores health status anyway.
- 2026-10-11: Added a GHCR image (amd64 and arm64) built by GitHub Actions, plus `docker-compose.example.yml`, so a server can deploy without cloning. `docker-compose.yml` still builds from source. Automatic image updates (Watchtower) were declined: updates stay a manual `docker compose pull`.
- 2026-10-11: Login became optional and is off by default (`.env.example` leaves it blank); an account set wrongly locks the page instead of opening it. The published-image compose no longer needs a `.env` or a pre-made network, so setup is one file. Retention moved onto the settings page, and the activity panel's dropdowns became tabs and count filters.
- 2026-10-11: Settings moved from `config.ini` to `config.toml`, read with `tomllib`. The INI loader silently fell back to the default on a mistyped `true`/`false`, and ignored misspelled keys; the TOML loader rejects a wrong type or an unknown key at startup. Existing deployments start from the shipped defaults and must copy any changed values across by hand.
- 2026-10-11: The README became the user guide (install with Compose or `docker run`, use, settings, troubleshooting) and the developer material moved to `docs/`, published as the GitHub wiki. The image now sets `PODCAST_DATA_DIR`, `PODCAST_DOWNLOAD_DIR`, and `PODCAST_INTERMEDIATE_DIR` itself, so a `docker run` needs only the three mounts.
