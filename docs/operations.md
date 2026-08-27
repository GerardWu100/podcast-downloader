---
title: Operations
sidebar_position: 5
---

# Running the downloader

## Local development

Install the dependencies and run the tests:

```bash
uv sync --dev
uv run python -m pytest -q
```

Start the API locally:

```bash
uv run uvicorn src.api:app --host 127.0.0.1 --port 8000
```

Set the web UI login by copying `.env.example` to `.env` and changing the username and password:

```bash
cp .env.example .env
# edit .env: set UI_USERNAME and UI_PASSWORD
```

At startup, the app reads `.env`, hashes each `UI_PASSWORD` with PBKDF2, and stores only the hashes in `.ui_credentials.json`. You do not need to hash passwords yourself. Edit `.env` and restart to change a password. Optional second and third accounts use `UI_USERNAME_2`/`UI_PASSWORD_2` and `UI_USERNAME_3`/`UI_PASSWORD_3`.

For Docker, create `.env` in the repository before copying the project to the server or running `docker compose up -d`. The image places it at `/app/.env`, and the first start copies it to the mounted `/data/.env`. After that, edit `$HOME/.containers/podcast-downloader/.env` on the host.

Compose expects a shared proxy network named `single`. Create it once if it does not exist:

```bash
docker network inspect single >/dev/null 2>&1 || docker network create single
```

## Docker behavior

When the container starts, it:

1. Copies the repository `config.ini` into the mounted data directory if it is missing.
2. Copies the image’s `.env` into the mounted data directory if no mounted `.env` exists. If the repository has no `.env`, it uses `.env.example`. The copied file is owner-only.
3. Keeps an existing `/data/cookies.txt`, fixes its permissions to owner-only, and seeds it from the image’s repository-root `cookies.txt` only when the mounted data directory has no cookie file.
4. Creates missing runtime files such as `urls.txt`, `downloaded_urls.txt`, `download.log`, and `.login_state.json`.
5. Performs a best-effort update to the latest `yt-dlp` nightly release and its browser-impersonation dependency when `YT_DLP_AUTO_UPDATE=true`.
6. Changes existing files in the three mounted application directories to the configured host user and group, then runs the application as that identity. This repairs root-owned files from earlier runs and prevents new ones.

`HOST_UID` and `HOST_GID` default to `1000`, the usual IDs of the first Linux
account. If your account uses different values, place them in the repository
`.env` before starting Compose:

```bash
id -u
id -g
```

For example, if those commands both print `1001`, add:

```dotenv
HOST_UID=1001
HOST_GID=1001
```

The next `docker compose up --build -d` repairs existing podcast ownership.
The entrypoint needs root only during setup; the web server and downloader run
with the configured host identity.

`start.py` then checks the `.env` password before starting the web server. If it is still the example password `changeme`, startup logs a warning.

## Error notifications

Configure these in the web UI, not in `config.ini`. See [notifications.md](notifications.md).

Inside Docker, `localhost` in the notify URL means the downloader's own container. Use the Apprise container name and put both containers on the same network. The `single` network in `docker-compose.yml` is the natural choice.

## YouTube cookies

If YouTube blocks a normal request, provide a Netscape-format cookie file named `cookies.txt`. With Docker Compose, the host path is `$HOME/.containers/podcast-downloader/cookies.txt`; the container path is `/data/cookies.txt`.

The app uses the mounted cookie file. Restarts and rebuilds do not replace it; the entrypoint only applies `chmod 600`. If `/data/cookies.txt` is missing, the entrypoint copies `/app/cookies.txt` when that file exists.

You can update cookies through the web UI instead of copying a file over SSH. The upload requires a signed-in session, checks the Netscape header, converts line endings to LF, and writes the file with mode `600`.

Set `cookies_file` in `config.ini` to use another mounted path.

`always_use_cookies` defaults to `true`, so YouTube calls use `--cookies <file>` first and retry once without cookies. Set it to `false` to reverse that order. Keep the file private: it contains browser sign-in data.

### Cookie file format

`yt-dlp` expects a Mozilla/Netscape cookie jar, not JSON or a browser SQLite export pasted directly into a file.

| Requirement | Detail |
|---|---|
| Header | The first line must be `# Netscape HTTP Cookie File` for browser uploads. Manually managed files may also use `# HTTP Cookie File` |
| Line endings | LF (`\n`) on Linux/macOS; CRLF (`\r\n`) on Windows |
| Bad-newline symptom | `HTTP Error 400: Bad Request` from `yt-dlp --cookies cookies.txt ...` |

On Linux, convert a Windows-exported file with:

```bash
sed -i 's/\r$//' cookies.txt
```

The web UI performs this conversion during upload.

## What goes into the image

The Dockerfile copies the whole repository in one `COPY . .`, so
`.dockerignore` decides what ships. The container runs the server and nothing
else, so these stay out:

| Excluded | Why |
|---|---|
| `extension/` and `build/` | Browser code. It runs in your browser, never on the server. `build/` holds the generated Firefox copy |
| `tests/`, `scripts/`, `docs/`, `blog/` | Developer material. Nothing under `src/`, `start.py`, or `docker-entrypoint.sh` imports them |
| Queue files, logs, sessions, credentials, cookies | Runtime state. The entrypoint creates these in the mounted data directory; a copy baked into the image would leak yours and be overwritten anyway |

`tests/test_docker_build_context.py` fails if one of those loses its exclusion.
The generated folders matter most: they are absent from a clean checkout, so a
missing entry shows up only on whichever machine ran the generator before
building.

## Scheduler behavior

- Scheduled runs happen every `DOWNLOAD_INTERVAL_HOURS`.
- Scheduler subprocesses run `python -m src.cli` from the project root, so Docker behavior does not depend on where the scheduler thread started.
- `yt-dlp` is not pinned in `uv.lock`. Docker installs the latest nightly release with `yt-dlp[default,curl-cffi]` during `docker build` and upgrades it at each container start when `YT_DLP_AUTO_UPDATE=true`. Locally, run `uv pip install --prerelease allow "yt-dlp[default,curl-cffi]"` after `uv sync`.
- The Docker image includes Deno, which gives current `yt-dlp` YouTube extraction a supported JavaScript runtime.
- Rumble downloads pass `--impersonate chrome`; `curl-cffi` supplies the browser-like network transport needed by Rumble's Cloudflare checks.
- `ERROR: unable to download video data: HTTP Error 403: Forbidden` usually means YouTube now requires a GVS PO Token, not that the network or cookies are broken. Metadata succeeds, but the audio transfer is refused. See `youtube_player_client` in [cli-and-config.md](cli-and-config.md).
- When a download fails, `download.log` holds the exact `yt-dlp` command and the complete output of every attempt, while `activity.log` holds a one-line cause. Copy the logged command to reproduce the failure by hand.
- Scheduled updates affect only `yt-dlp` and the dependencies in its `default` and `curl-cffi` groups.
- After a scheduled update, the downloader waits five minutes before starting the run unless a UI-triggered download arrives during that wait.
- If the update fails, the scheduler logs a warning, reports the current `yt-dlp` version, and skips the five-minute wait.
- A direct video URL added through the web UI starts an immediate run for that URL only.
- Direct non-YouTube URLs always run immediately because they do not use the YouTube age gate.
- Direct YouTube URLs run immediately only when they pass the configured minimum-age check, unless `Download now` is selected.
- A selected playlist starts an immediate full-playlist run and downloads every entry instead of applying the `channel_count` limit.
- Channel and playlist additions remain queued for the scheduled full-queue run. Each run considers only the newest `channel_count` entries from each monitored source.
- An immediate single-URL run does not inspect the rest of `urls.txt` or expand older channel and playlist entries.
- After an immediate run, the scheduler waits a full interval before the next scheduled run.

## Downloaded file dates

Completed MP3 files receive an embedded MP3 `date` tag set to the Toronto/Eastern completion time. Audiobookshelf uses it as the visible episode date. The same metadata pass stores the source URL in the MP3 `comment` tag.

YouTube URLs are stored in canonical watch form, including live URLs. Other URLs are stored as provided. The metadata rewrite stages its output in two hidden temporary files, neither of them named `*.mp3`, then swaps the finished file onto the original path with an atomic rename. A directory scan therefore always sees exactly one `.mp3` at one stable path, so Audiobookshelf never indexes a temporary or duplicate file. The rename does replace the file's inode. That is a deliberate trade for safety: the original file is never opened for writing, so a failure part-way through the metadata pass leaves the untagged MP3 intact instead of truncating it.

The downloader also uses `--no-mtime` in the `yt-dlp` command. It does not separately reset the filesystem timestamp for Audiobookshelf.

## Download folder layout

Only MP3 files go under the configured download directory. The queue file `urls.txt` stays in the data directory.

```text
downloads/
├── channel-one/
├── channel-two/
├── playlist-name1/
└── singles/
```

Channel folder names come from the source URL after filesystem-safe cleanup. Playlist folders prefer the title reported by `yt-dlp`; if that lookup fails, they use the `list=` identifier. Individual videos from YouTube or other supported sites go into `singles/`.

## Retention cleanup

During scheduled full-queue runs, the downloader scans MP3 files under the configured download directory before checking archive-backed channel candidates. Only files in current YouTube channel folders are eligible. Playlist and single-video files are never deleted by this rule.

Cleanup reads the embedded MP3 `date` tag and deletes eligible channel files older than `retention_days` (30 days by default). It does not use the YouTube release date or filesystem modification time.

If the date metadata is missing or unreadable, or the file has no source URL in its comment tag, the downloader logs the problem and leaves the file alone. When it deletes a channel MP3, it removes that video URL from `downloaded_urls.txt`.

## Operational files

| File | Purpose |
|---|---|
| `urls.txt` | Pending queue of user-supplied URLs |
| `downloaded_urls.txt` | Archive of expanded channel and playlist items |
| `download.log` | Main runtime log; rotates at 5 MB and keeps `download.log.1` through `download.log.3` |
| `activity.log` | Short browser activity feed, created on the first activity event |
| `notifications.json` | Apprise error-notification settings written by the web UI; owner-only because the endpoint usually embeds a key |
| `.login_state.json` | Failed-login counters and temporary bans |
| `.env` | Operator-set UI account names and plain-text passwords |
| `.ui_credentials.json` | UI account names and PBKDF2 password hashes generated from `.env` |

## Manual smoke check

This check uses the live network:

```bash
uv run --with "yt-dlp[default]" python scripts/sponsorblock_smoke_check.py
```

It is not part of the normal pytest suite because it depends on the live YouTube and SponsorBlock services.
