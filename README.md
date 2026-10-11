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
repository: the image is published for both common server types (amd64 and
arm64), and Docker picks the right one.

**1. Make a folder and download two files into it.**

```bash
mkdir podcast-downloader && cd podcast-downloader
curl -o docker-compose.yml https://raw.githubusercontent.com/GerardWu100/podcast-downloader/master/docker-compose.example.yml
curl -o .env https://raw.githubusercontent.com/GerardWu100/podcast-downloader/master/.env.example
```

**2. Edit `.env`.** Set `UI_USERNAME` and `UI_PASSWORD`; that is the web page
login. If `id -u` and `id -g` on the server do not both print `1000`, also set
`HOST_UID` and `HOST_GID` to those numbers, so you own the downloaded files.

**3. Check the folders in `docker-compose.yml`.** By default:

| On the server | Holds |
|---|---|
| `~/downloads/podcasts` | The MP3 library. Point Audiobookshelf here. |
| `~/.containers/podcast-downloader` | Settings, queue, cookies, and logs |
| `~/downloads/temporary` | Files still being processed |

Change the left side of a `volumes:` line to use another folder.

**4. Start it.**

```bash
docker network inspect single >/dev/null 2>&1 || docker network create single
docker compose up -d
```

The web page is at `http://127.0.0.1:50022` on the server. The `single`
network is where a reverse proxy (for HTTPS) and Apprise (for alerts) can reach
it.

**Update** to the newest version:

```bash
docker compose pull && docker compose up -d
```

To go back to an older version, replace `latest` in `docker-compose.yml` with a
`sha-<commit>` tag from the
[package page](https://github.com/GerardWu100/podcast-downloader/pkgs/container/podcast-downloader).

Your password and cookies never go into the image. Compose hands `.env` to the
container at start, and the first start copies it to
`~/.containers/podcast-downloader/.env`. After that, edit that copy to change
the login. See [docs/operations.md](docs/operations.md) for everything the
container does at start.

## First steps in the web page

1. Sign in with the login from `.env`.
2. Paste a channel, playlist, or video URL into the add-source box.
3. Select **Run queue now** to start a run, or wait for the schedule. The line
   under the box shows the last download, the last run, and the next one.
4. In Audiobookshelf, add a podcast library that points at the MP3 folder.

Each saved source has **Run now** and **Delete**. **Run now** on a single video
skips the wait for SponsorBlock. On a channel or playlist, it checks the recent
videos now but still waits for videos that are too new.

To use it as a phone app, open the site over HTTPS in Chrome or Safari and
choose **Install app** or **Add to Home Screen**. It keeps you signed in for 30
days.

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
without copying a URL. It uses your web page login.

| Browser | Install |
|---|---|
| Firefox 140+ | Download `podcast-downloader-firefox-<version>.xpi` from the [latest release](https://github.com/GerardWu100/podcast-downloader/releases/latest), drag it onto a Firefox window, and select **Add**. Do not unzip it. |
| Chrome, Edge, Brave | Unzip `podcast-downloader-chrome-<version>.zip` from the [latest release](https://github.com/GerardWu100/podcast-downloader/releases/latest). Open `chrome://extensions`, turn on **Developer mode**, select **Load unpacked**, and choose the folder. |

Install it on the computer where you browse, which can differ from the server.
Then click the toolbar icon to open its settings and enter:

| Field | Value |
|---|---|
| Server address | Where you open the web page, such as `https://podcast.example.com` |
| Username and password | Your web page login |

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

Settings live in `config.ini`. With Docker, edit
`~/.containers/podcast-downloader/config.ini` and restart the container
(`docker compose restart`). The ones you are most likely to change:

| Setting | Default | What it does |
|---|---|---|
| `scheduled_run_hour` | `6` | Hour of the automatic run, on the server's `TZ` clock |
| `scheduled_run_interval_days` | `2` | Days between automatic runs |
| `retention_days` | `30` | Days to keep channel episodes before deleting them |
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
cp .env.example .env    # then set UI_USERNAME and UI_PASSWORD
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

`docker-compose.yml` builds the image from your checkout instead of pulling it:

```bash
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
