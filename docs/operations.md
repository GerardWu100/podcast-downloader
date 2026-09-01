---
title: Operations
sidebar_position: 5
---

# Running the downloader

## Local development

Install the dependencies, then run the tests:

```bash
uv sync --dev
uv run python -m pytest -q
```

Start the API locally:

```bash
uv run uvicorn src.api:app --host 127.0.0.1 --port 8000
```

Set the web UI login by copying `.env.example` to `.env`, then changing the username and password:

```bash
cp .env.example .env
# edit .env: set UI_USERNAME and UI_PASSWORD
```

At startup, the app reads `.env`, hashes each `UI_PASSWORD` with PBKDF2, and stores only the hashes in `.ui_credentials.json`. You do not need to hash passwords yourself. To change a password, edit `.env` and restart. Optional second and third accounts use `UI_USERNAME_2`/`UI_PASSWORD_2` and `UI_USERNAME_3`/`UI_PASSWORD_3`.

For Docker, create `.env` in the repository before running
`docker compose up -d`. Compose mounts it as a read-only runtime secret; it
never enters an image layer. The first start copies it to the mounted
`/data/.env`. After that, edit
`$HOME/.containers/podcast-downloader/.env` on the host. The repository file is
still required because Compose resolves the secret before the container starts.

Compose expects a shared proxy network named `single`. Create it once if needed:

```bash
docker network inspect single >/dev/null 2>&1 || docker network create single
```

## Docker behavior

When the container starts, it:

1. Copies the repository `config.ini` into the mounted data directory if it is missing.
2. Copies the runtime `.env` secret into the mounted data directory if no mounted `.env` exists. Outside Compose, it falls back to `.env.example`. The copied file is owner-only.
3. Keeps an existing `/data/cookies.txt` and makes it owner-only. Cookie files are never copied into the image; add one to the host data directory or upload it through the web UI.
4. Creates missing runtime files such as `urls.txt`, `downloaded_urls.txt`, `download.log`, and `.login_state.json`.
5. Attempts to update the latest `yt-dlp` nightly release and its browser-impersonation dependency when `YT_DLP_AUTO_UPDATE=true`.
6. Changes existing files in the three mounted application directories to the configured host user and group, then runs the application as that identity. This repairs files owned by root from earlier runs and prevents new ones.

`HOST_UID` and `HOST_GID` default to `1000`, the usual IDs for the first Linux
account. If your account uses different values, add them to the repository
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
as the configured host identity.

`start.py` checks the `.env` password before starting the web server. If it is still the example password `changeme`, startup logs a warning.

## Error notifications

Configure notifications in the web UI, not in `config.ini`. See [notifications.md](notifications.md).

Inside Docker, `localhost` in the notify URL means the downloader container. Use the Apprise container name and put both containers on the same network. The `single` network in `docker-compose.yml` is the natural choice.

## YouTube cookies

If YouTube blocks a normal request, provide a Netscape-format cookie file named `cookies.txt`. With Docker Compose, it lives at `$HOME/.containers/podcast-downloader/cookies.txt` on the host and `/data/cookies.txt` in the container.

The app uses the mounted cookie file. Restarts and rebuilds do not replace it;
the entrypoint only applies `chmod 600`. If `/data/cookies.txt` is missing, use
the web UI or copy the file directly to the host data directory.

You can update cookies through the web UI instead of copying a file over SSH. Uploads require a signed-in session, must have the Netscape header, convert line endings to LF, and write the file with mode `600`.

Set `cookies_file` in `config.ini` to use another mounted path.

`always_use_cookies` defaults to `true`: YouTube calls use `--cookies <file>` first, then retry once without cookies. Set it to `false` to reverse that order. Keep the file private; it contains browser sign-in data.

### Cookie file format

Use a Mozilla/Netscape cookie jar with `yt-dlp`, not JSON or a browser SQLite export pasted directly into a file.

| Requirement | Detail |
|---|---|
| Header | The first line must be `# Netscape HTTP Cookie File` for browser uploads. Manually managed files may also use `# HTTP Cookie File` |
| Line endings | LF (`\n`) on Linux/macOS; CRLF (`\r\n`) on Windows |
| Bad-newline symptom | `HTTP Error 400: Bad Request` from `yt-dlp --cookies cookies.txt ...` |

On Linux, convert a file exported on Windows with:

```bash
sed -i 's/\r$//' cookies.txt
```

The web UI performs this conversion during upload.

## What goes into the image

The Dockerfile copies only named runtime entry points plus `src/`. This is the
primary boundary that prevents a forgotten local file from entering an image.
`.dockerignore` also removes secrets, state, developer material, and generated
output from the build context as defense in depth:

| Excluded | Why |
|---|---|
| `extension/` and `build/` | Browser code. It runs in your browser, never on the server. `build/` holds the generated Firefox copy |
| `tests/`, `scripts/`, `docs/`, `blog/` | Developer material. Nothing under `src/`, `start.py`, or `docker-entrypoint.sh` imports them |
| `.env`, cookies, notification settings, queue files, logs, sessions, credentials, the last-run record | Secrets and runtime state belong in the runtime secret or mounted data directory; image layers are durable and may be pushed to a registry |

`tests/test_docker_build_context.py` fails if one of those entries is removed,
and `tests/test_docker_entrypoint.py` refuses a broad `COPY . .` instruction.
Generated folders matter most: they are absent from a clean checkout, so a
missing entry appears only on a machine that ran the generator before building.

## Scheduler behavior

- Runs happen on a wall clock, not a countdown: at `scheduled_run_hour` on
  every `scheduled_run_interval_days`-th calendar day. The shipped values are
  06:00 and 2, so runs land at 06:00 every other day on the container's `TZ`
  clock. Restarting the container, redeploying, or pressing **Run queue now**
  never moves the next run.
- Run days come from the date itself, not from a saved starting point, so two
  machines with the same settings agree on which mornings are run mornings.
- The two settings live in `config.ini`. Docker copies the repository file to
  `/data/config.ini` on first boot only, so an existing deployment keeps its own
  copy; add the two keys there to change the time.
- On startup the scheduler checks whether it missed a run: if no full queue run
  has finished since the last scheduled time, it runs once immediately and then
  returns to the fixed schedule. A container that was down at 06:00 therefore
  catches up instead of waiting for the next run day.
- **Run queue now** on the queue page starts the same whole-queue pass by hand.
  It is refused while a run is already going, and it does not shift the
  schedule.
- The queue page shows when the last run finished, how long ago that was, and
  when the next one is due. The record lives in `run_state.json` beside the
  other state files.
- Scheduler subprocesses run `python -m src.cli` from the project root, so Docker behavior does not depend on where the scheduler thread started.
- `yt-dlp` is not pinned in `uv.lock`. Docker installs the latest nightly release with `yt-dlp[default,curl-cffi]` during `docker build` and upgrades it at each container start when `YT_DLP_AUTO_UPDATE=true`. Locally, run `uv pip install --prerelease allow "yt-dlp[default,curl-cffi]"` after `uv sync`.
- The Docker image includes Deno, a supported JavaScript runtime for current `yt-dlp` YouTube extraction.
- Rumble downloads pass `--impersonate chrome`; `curl-cffi` supplies the browser-like network transport Rumble’s Cloudflare checks require.
- `ERROR: unable to download video data: HTTP Error 403: Forbidden` usually means YouTube now requires a GVS PO Token, not that the network or cookies are broken. Metadata succeeds, but the audio transfer is refused. See `youtube_player_client` in [cli-and-config.md](cli-and-config.md).
- When a download fails, `download.log` holds the exact `yt-dlp` command and complete output for every attempt. `activity.log` records the cause in one line. Copy the logged command to reproduce the failure by hand.
- Scheduled updates affect only `yt-dlp` and the dependencies in its `default` and `curl-cffi` groups.
- After a scheduled update, the downloader waits five minutes before starting. A URL added from the browser during that pause is downloaded straight away, and the scheduled run still follows.
- If the update fails, the scheduler logs a warning, reports the current `yt-dlp` version, and skips the five-minute wait.
- A direct video URL added through the web UI starts an immediate run for that URL only.
- Direct non-YouTube URLs always run immediately because they do not use the YouTube age gate.
- Direct YouTube URLs run immediately only when they pass the configured minimum-age check, unless `Download now` is selected.
- A selected playlist starts an immediate full-playlist run and downloads every entry instead of applying the `channel_count` limit.
- Channel and playlist additions stay queued for the scheduled full-queue run. Each run considers only the newest `channel_count` entries from each monitored source.
- An immediate single-URL run does not inspect the rest of `urls.txt` or expand older channel and playlist entries.
- An immediate run never changes the next scheduled time.

## Knowing when it has stopped working

A downloader can fail by doing nothing, and doing nothing is silent. If YouTube
refuses to list a channel, no video is attempted, so no download fails, so no
failure notification is sent. The run ends with `0 successful, 0 failed` and
looks exactly like a week with no new episodes.

Four things now break that silence. All of them are sent as Apprise failures,
so a setup that only forwards errors still receives them:

| Situation | What is sent | Sent by |
|---|---|---|
| Every monitored channel and playlist returned no videos | One alert naming the cookie file and `youtube_player_client` as what to check | The download run |
| The sign-in cookies expired, or expire within `cookie_expiry_warning_days` | The expiry date and what to do | The download run |
| The downloader process stopped before downloading anything | The exit status, plus where to look | The scheduler |
| A scheduled run did not happen while the container was down | The run time that was missed and the last run that finished | The scheduler, on the next start |

A run that worked sends nothing. That is deliberate: a message that always
arrives cannot prove anything by arriving, and it trains you to ignore the
channel it arrives on.

Two things are deliberately not alerted. A single channel returning no videos
is ordinary, so it is written to the activity log as `No videos listed` and
shown with an `Empty` badge instead. Individual failed downloads already send
their own message.

## Watching from outside

Nothing inside a dead container can report that it is dead. The last case above
is covered only after the machine comes back, so a container that hangs or
never restarts stays silent. `GET /api/health` exists to be polled from outside
for exactly that:

```bash
curl -u "$UI_USERNAME:$UI_PASSWORD" http://127.0.0.1:50022/api/health
```

```json
{
  "ok": true,
  "status": "ok",
  "last_run_finished_at": "2026-09-03T06:04:11-04:00",
  "last_run_kind": "scheduled",
  "next_run_at": "2026-09-05T06:00:00-04:00"
}
```

The status code carries the answer, so a monitor needs no JSON parsing: `200`
while runs are happening on schedule, `503` once the run that was due is more
than three hours late. A run in progress stays `200` however long it takes, and
reports `"status": "running"`.
Point Uptime Kuma, Gatus, or any HTTP monitor at it with the web interface
username and password, and it will alert when the schedule stops being kept.

`GET /api/ping` cannot do this job. It stays cheerful as long as the web server
answers, which it does while the scheduler behind it is dead.

## Reading the activity log

- The browser groups activity by day and marks each run with a `Run started`
  and a `Run finished` line, so one run's work is everything between the two.
  An empty queue still writes both lines: a run that logs nothing looks the
  same as a scheduler that has died.
- The badge on each line is the event type: `Run`, `Done`, `Fail`, `Wait` (a
  video still inside `min_channel_video_age_hours`), `Skip` (a YouTube Short),
  and `Keep` (retention deleting a file).
- The counts beside the picker total the lines currently loaded, and
  **Problems only** hides everything that worked.
- URLs in the feed are links, so a failed line leads straight to the video.
- Both logs read the same way. `activity.log` is the summary; `download.log`
  keeps the full `yt-dlp` command and output and is chosen from the same picker.

## Cookie expiry

- The settings page names the cookie file in use, counts its cookies, and says
  when the sign-in stops working.
- The date is the earliest expiry among the YouTube sign-in cookies
  (`SID`, `HSID`, `SSID`, `APISID`, `SAPISID`, `LOGIN_INFO`, and the
  `__Secure-` variants), read from the file's own fifth field. It is an upper
  bound: YouTube can invalidate a sign-in before its cookies expire.
- The page warns within 14 days of that date, and marks a passed date in red.
- A file with no sign-in cookies is also called out. It will not get past an
  age check, whatever else it contains.

## The Google account behind the cookies

The cookie file is a live sign-in for whatever account exported it. Two things
follow from that.

It is a credential. Anyone who reads the file is signed in as that account, on
YouTube and on everything else the export covered. That is why the file is
stored with owner-only permissions, kept out of the image, and excluded from
the Docker build context.

The account also carries the risk. Automated downloading from a signed-in
account is not what YouTube's terms describe, and accounts have been rate
limited or disabled for it. If the account holds your email, photos, or
anything you would mind losing, use a separate throwaway Google account for the
cookies instead. A throwaway account also makes the recurring cookie refresh
easier: you can sign it in on one browser profile and export from there without
disturbing your own session.

## Downloaded file dates

Completed MP3 files receive an embedded MP3 `date` tag set to the Toronto/Eastern completion time. Audiobookshelf shows it as the episode date. The same pass stores the source URL in the MP3 `comment` tag.

YouTube URLs are stored in canonical watch form, including live URLs. Other URLs are stored as provided. The metadata rewrite uses two hidden temporary files, neither named `*.mp3`, then atomically renames the finished file over the original. A directory scan therefore sees exactly one `.mp3` at one stable path, so Audiobookshelf never indexes a temporary or duplicate file. The rename does replace the file’s inode. That trade protects the original: it is never opened for writing, so a mid-pass failure leaves the untagged MP3 intact instead of truncating it.

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

Channel folder names come from the source URL after filesystem-safe cleanup. Playlist folders prefer the title reported by `yt-dlp`; if that lookup fails, they use the `list=` identifier. Individual videos from YouTube or other supported sites go in `singles/`.

## Retention cleanup

During scheduled full-queue runs, the downloader scans MP3 files under the configured download directory before checking channel candidates recorded in the archive. Only files in current YouTube channel folders are eligible. This rule never deletes playlist or single-video files.

Cleanup reads the embedded MP3 `date` tag and deletes eligible channel files older than `retention_days` (30 days by default). It ignores the YouTube release date and filesystem modification time.

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
