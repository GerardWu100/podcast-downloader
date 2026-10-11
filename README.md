# Podcast Downloader

Podcast Downloader turns YouTube channels, playlists, and single videos into
sponsor-free MP3 files for [Audiobookshelf](https://www.audiobookshelf.org/).
Add a source once in the web page; new episodes arrive in your podcast library
on their own.

```text
YouTube channel ──► wait for SponsorBlock ──► MP3, sponsors cut ──► Audiobookshelf
```

## What it does

- Checks your channels and playlists on a schedule (06:00 every other day by
  default) and downloads new videos. Single URLs work too.
- Skips YouTube Shorts and waits until SponsorBlock has marked the sponsor
  segments, then cuts them out.
- Sorts MP3 files into one folder per source and deletes old channel episodes
  after a set number of days.
- Gives up on a video after two failed attempts, so a deleted or private video
  stops failing every run. YouTube blocks and network errors do not count.
- Tells you when it has quietly stopped working: no channel would list, a run
  could not start, cookies are about to expire, or a scheduled run never
  happened.
- Runs as a password-protected web page that you can install on a phone, plus
  a Chrome and Firefox extension that queues the page you are watching.

## Quick start with Docker

You need Docker with Compose on the server. You do **not** need to clone this
repository or write any config: the image is published for both common server
types (amd64 and arm64), and Docker picks the right one.

**1. Download one file into an empty folder.**

```bash
mkdir podcast-downloader && cd podcast-downloader
curl -o docker-compose.yml https://raw.githubusercontent.com/GerardWu100/podcast-downloader/master/docker-compose.example.yml
```

**2. Check two things in `docker-compose.yml`.**

- **Folders.** Change the left side of a `volumes:` line to keep files
  somewhere else. By default:

  | On the server | Holds |
  |---|---|
  | `~/downloads/podcasts` | The MP3 library. Point Audiobookshelf here. |
  | `~/.containers/podcast-downloader` | Settings, queue, cookies, and logs |
  | `~/downloads/temporary` | Files still being processed |

- **File owner.** Run `id -u` and `id -g`. If either does not print `1000`,
  put those numbers in `HOST_UID` and `HOST_GID`, so you own the MP3 files.

**3. Start it.**

```bash
docker compose up -d
```

Open `http://<server address>:6847`. There is no login by default.

**Update** to the newest version:

```bash
docker compose pull && docker compose up -d
```

To go back to an older version, replace `latest` in `docker-compose.yml` with a
`sha-<commit>` tag from the
[package page](https://github.com/GerardWu100/podcast-downloader/pkgs/container/podcast-downloader).

### Add a password (optional)

Without a login, anyone who can reach the page can use it. That is fine on a
home network. Before you expose it to the internet, put a reverse proxy with
HTTPS in front and turn the login on:

1. Edit `~/.containers/podcast-downloader/.env` (the first start created it).
2. Set `UI_USERNAME` and `UI_PASSWORD`. Up to three accounts are allowed; see
   the comments in the file.
3. Run `docker compose restart`.

The container joins a Docker network named `single`, creating it if needed,
where a reverse proxy and Apprise (for alerts) can reach it. Your password and
cookies stay in the data folder and never go into the image. See
[docs/operations.md](docs/operations.md) for everything the container does at
start.

## First steps in the web page

1. Paste a channel, playlist, or video URL into the add-source box.
2. Select **Run queue now** to start a run, or wait for the schedule. The line
   under the box shows the last download, the last run, and the next one.
3. In Audiobookshelf, add a podcast library that points at the MP3 folder.
4. On the **Settings** page, choose how many days to keep channel episodes
   (30 by default). Videos added one by one are kept.

Each saved source has **Run now** and **Delete**. **Run now** on a single video
skips the wait for SponsorBlock. On a channel or playlist, it checks the recent
videos now but still waits for videos that are too new.

The activity panel has two tabs: **Activity** is the short story of each run,
**Detailed log** is the full `yt-dlp` output. The count buttons beside them,
such as **4 failed**, show only those lines.

To use it as a phone app, open the site over HTTPS in Chrome or Safari and
choose **Install app** or **Add to Home Screen**.

## Keep it working

**YouTube cookies.** When YouTube starts blocking downloads, export fresh
cookies from a browser where you are signed in to YouTube:

```bash
yt-dlp --cookies-from-browser chrome --cookies cookies.txt
```

Upload the file on the **Settings** page. The page shows when the sign-in
expires. That date comes from the file, so YouTube can end the sign-in earlier.
The `/help` page has step-by-step export instructions.

**Alerts.** On the **Settings** page, enter an
[Apprise](https://github.com/caronc/apprise) URL to get problems on Telegram,
email, Discord, or another service. Select **Send test notification** before
saving. See [docs/notifications.md](docs/notifications.md).

**Uptime.** `GET /api/health` lets an outside uptime monitor notice when the
container itself has stopped.

## Browser extension

The extension adds the page you are watching, or a link on it, to the queue
without copying a URL. It uses your web page login; with login off, type any
name and password.

| Browser | Install |
|---|---|
| Firefox 140+ | Download `podcast-downloader-firefox-<version>.xpi` from the [latest release](https://github.com/GerardWu100/podcast-downloader/releases/latest), drag it onto a Firefox window, and select **Add**. Do not unzip it. |
| Chrome, Edge, Brave | Unzip `podcast-downloader-chrome-<version>.zip` from the [latest release](https://github.com/GerardWu100/podcast-downloader/releases/latest). Open `chrome://extensions`, turn on **Developer mode**, select **Load unpacked**, and choose the folder. |

Install it on the computer where you browse, which can differ from the server.
Then click the toolbar icon to open its settings and enter:

| Field | Value |
|---|---|
| Server address | Where you open the web page, such as `https://podcast.example.com` |
| Username and password | Your web page login, or anything when login is off |

Select **Save**, allow the permission, then **Test connection**. **Connected**
means it works.

| To add | Do this |
|---|---|
| The current page | Click the toolbar icon, or press `Alt+Shift+D` |
| The current page, on YouTube or Rumble | Right-click the page and choose the podcast item |
| A YouTube or Rumble link | Right-click the link and choose the podcast item |

The icon badge shows `OK` for a new item, `=` for one already queued or
downloaded, and `!` for a problem. See
[docs/browser-extension.md](docs/browser-extension.md) for troubleshooting.

## Configuration

Retention is on the settings page. Everything else lives in `config.toml`.
With Docker, edit `~/.containers/podcast-downloader/config.toml` and restart the
container (`docker compose restart`). Numbers and `true`/`false` are written
bare and text goes in quotes; a typo stops startup with an error that names the
setting. The ones you are most likely to change:

| Setting | Default | What it does |
|---|---|---|
| `scheduled_run_hour` | `6` | Hour of the automatic run, on the server's `TZ` clock |
| `scheduled_run_interval_days` | `2` | Days between automatic runs |
| `retention_days` | `30` | Days to keep channel episodes; also on the settings page |
| `channel_count` | `2` | Recent videos to check per channel or playlist |
| `min_channel_video_age_hours` | `24` | How old a video must be, so SponsorBlock has time to mark it |
| `max_download_attempts` | `2` | Failed attempts before a video is dropped |
| `cookie_expiry_warning_days` | `14` | Days before cookie expiry to start warning; `0` turns it off |

The time zone is `TZ` in `docker-compose.yml` (`America/Toronto` by default).
See [docs/cli-and-config.md](docs/cli-and-config.md) for every setting.

## Run without Docker

You need Python 3.13+, `ffmpeg`, and [`uv`](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/GerardWu100/podcast-downloader.git
cd podcast-downloader
uv sync --dev
uv pip install --prerelease allow "yt-dlp[default,curl-cffi]"
cp .env.example .env    # optional: set UI_USERNAME and UI_PASSWORD for a login
uv run uvicorn src.api:app --host 127.0.0.1 --port 8000
```

`yt-dlp` is installed separately because YouTube fixes usually appear in its
nightly releases first. `curl-cffi` gets Rumble past its Cloudflare checks.

The command line works without the web page:

| Command | Does |
|---|---|
| `uv run python main.py` | One pass over the queue in `urls.txt` |
| `uv run python main.py -f my_urls.txt -o ./out -n 3` | Same, with another queue file, output folder, and number of recent videos |
| `uv run python main.py --add-url "<url>"` | Add a URL to the queue (`--skip-age-check` to skip the wait once) |
| `uv run python main.py --add-url-stdin < new_urls.txt` | Add many URLs |
| `uv run python main.py --download-single-url "<url>"` | Download one video now |
| `uv run python main.py --download-full-playlist "<url>"` | Download a whole playlist |
| `uv run python main.py --download-source-now "<url>"` | Run one saved source now |

### Docker from a clone

`docker-compose.yml` builds the image from your checkout instead of pulling it.
It needs a `.env` in the repository and the `single` network to exist:

```bash
cp .env.example .env
docker network inspect single >/dev/null 2>&1 || docker network create single
docker compose up --build -d
```

`./update.sh` pulls new commits and rebuilds only when something changed.
`./update.sh --force` rebuilds anyway, for example after editing `.env`.

## For developers

```bash
uv run python -m pytest -q                       # offline tests
uv run python scripts/sponsorblock_smoke_check.py  # live SponsorBlock check
uv run python scripts/build_extensions.py        # build the browser extensions
```

- `main.py` and `start.py`: command-line entry point and Docker supervisor.
- `src/`: downloads, media, state, and the web interface.
- `extension/`: Chrome and Firefox extension. It is not part of the server image.
- `tests/` and `scripts/`: automated tests, manual checks, and extension packaging.

Each push to `master` that changes the server builds and publishes the Docker
image to `ghcr.io/gerardwu100/podcast-downloader`.

[docs/architecture.md](docs/architecture.md) explains the pipeline and modules.
[docs/browser-extension.md](docs/browser-extension.md) covers signed Firefox
builds. AI agents can use [the CLI skill](.agents/skills/podcast-downloader-cli/SKILL.md);
keep the server address and login in an ignored `.env`, never in the skill.
