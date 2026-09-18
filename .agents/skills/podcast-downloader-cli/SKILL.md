---
name: podcast-downloader-cli
description: Use Podcast Downloader to queue videos, download podcast audio locally, check remote service health, and operate its web app. Use for this application's listening library, not podcast research or transcription.
---

# Podcast Downloader

Use the existing deployment when the user means their live library. The local
CLI writes local files; it does not control a remote server. Do not start a
server, deploy updates, or change schedules just to add a video.

## Locate the app and credentials

The usual checkout is `~/projects/one-time-projects/podcast-downloader`.
Find `main.py` and `pyproject.toml` there before running local commands.
Run examples from that checkout. Use `uv sync --dev` if dependencies are missing.

Keep `PODCAST_SERVER_URL`, `UI_USERNAME`, and `UI_PASSWORD` in its ignored `.env`.
Accounts 2 and 3 use `UI_USERNAME_2`/`UI_PASSWORD_2` and the corresponding `_3`
pair. `.env.example` contains placeholders only. Never print or commit real
values, paste them into commands, or put them in this skill. Do not overwrite an
existing `.env`. If configuration is missing, ask the user to populate it locally.

## Remote commands

This skill includes `scripts/remote.py`. It reads the specified `.env` using
python-dotenv, without shell evaluation, and sends HTTP Basic authentication.
It requires HTTPS except for loopback HTTP, refuses redirects, and makes one
request per invocation. Use the script's installed location if the skill was copied.

```bash
uv run --with python-dotenv python .agents/skills/podcast-downloader-cli/scripts/remote.py --env-file .env ping
uv run --with python-dotenv python .agents/skills/podcast-downloader-cli/scripts/remote.py --env-file .env health
uv run --with python-dotenv python .agents/skills/podcast-downloader-cli/scripts/remote.py --env-file .env add-url 'https://www.youtube.com/watch?v=VIDEO_ID'
```

Put `--account 2` before the command to select the second account. Use
`add-url ... --skip-age-check` only when the user wants to bypass the waiting
period for a new YouTube video, or explicitly download an entire playlist now.

- `ping` checks the server and account, not download success.
- `health` checks scheduling; HTTP 503 means unhealthy or unconfigured, not
  necessarily a dead web server.
- `add-url` may start a direct video immediately. Channels and playlists wait
  for a scheduled pass unless a dedicated playlist is submitted with
  `--skip-age-check`, which starts the full playlist. YouTube's video age gate
  still applies unless explicitly bypassed.
- Read `outcome`: `added`, `duplicate`, `downloaded`, or `invalid`. `immediate`
  means processing was triggered, not that an MP3 was produced.
- Stop after 401 or 429 and fix credentials or wait out the ban. Do not guess
  passwords. If a write times out, inspect the queue before retrying.

The JSON API supports `/api/ping`, `/api/health`, and `/api/add-url`. Queue listing,
removal, and Run now are browser actions, not additional JSON endpoints.

## Local CLI

```bash
uv run python main.py --help
uv run python main.py --add-url 'https://www.youtube.com/@CHANNEL'
uv run python main.py --add-url-stdin < new_urls.txt
uv run python main.py
uv run python main.py --download-single-url 'https://www.youtube.com/watch?v=VIDEO_ID'
uv run python main.py --download-source-now 'https://www.youtube.com/@CHANNEL'
uv run python main.py --download-full-playlist 'https://www.youtube.com/playlist?list=PLAYLIST_ID'
```

Local add commands append to the queue and exit; they do not start downloads.
`--add-url` can repeat; `--skip-age-check` with an add command records a one-use
override. No arguments runs the entire queue and can apply retention cleanup.
Choose only one immediate-download mode:

| Mode | Behavior |
|---|---|
| `--download-single-url` | One direct URL; preserves the YouTube age gate unless a bypass exists |
| `--download-source-now` | One saved source; direct videos bypass age, channels/playlists keep age and entry limits |
| `--download-full-playlist` | Every entry in a dedicated YouTube playlist; potentially a large download |

`-f` selects a queue file, `-o` the output directory, and `-n` the number of recent
channel/playlist entries (at least 1). Local downloads require `ffmpeg` and
`yt-dlp`; read `docs/cli-and-config.md` for installation and config options.
`PODCAST_DATA_DIR` selects active runtime state when set in the process environment;
do not assume the local CLI loads arbitrary root `.env` settings.

## Browser workflow and verification

Open the configured server address using the available browser tool and sign in
with the selected `.env` account without exposing its values. The queue page
adds/removes sources and offers **Run queue now** and per-source **Run now**.
**Settings** manages cookies and notifications; `/help` explains cookie export.
Use existing browser automation instructions when the agent environment provides them.

Confirm downloads through activity/logs and, when filesystem access exists,
a new or changed MP3 in the active source folder. An accepted URL or exit code
alone is not proof. Never rewrite MP3 `date` or `comment` tags: retention and
Audiobookshelf tracking depend on them. Preserve cookies and runtime state.
Report queued, started, and downloaded as distinct outcomes.

## Portability

Copy this entire `podcast-downloader-cli` folder, including `scripts/`, into the
target agent's skill directory (for example `~/.hermes/skills/` for Hermes or
`~/.agents/skills/` for agents using shared discovery). Keep the `.env` separate
and pass its path explicitly. Installation is optional; an agent can also read
this file directly. Never bundle credentials with the skill.
