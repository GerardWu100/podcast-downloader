# Podcast Downloader

Podcast Downloader turns online videos into local MP3 files for
[Audiobookshelf](https://www.audiobookshelf.org/). It can monitor YouTube
channels and playlists, download individual URLs, remove SponsorBlock
segments when available, and run from the command line or a web browser.

## Features

- Monitor channels and playlists, or add individual URLs.
- Skip YouTube Shorts and wait for SponsorBlock data before downloading new
  videos.
- Convert audio to MP3, organize it by source, and remove old channel files.
- Run the queue automatically at a fixed time of day, 06:00 every other day by
  default, or start a run by hand from the web page.
- Keep the queue, download history, and one-use age-check exceptions in
  `urls.txt`, `downloaded_urls.txt`, and `bypass_age_check_urls.txt`.
- Manage sources, activity, logs, cookies, and error notifications from the
  password-protected web interface. The activity feed is grouped by day and by
  run, and the settings page says when the YouTube cookies expire.
- Install the web interface on a phone, or use the Chrome and Firefox
  extension to queue the page you are viewing.

See [docs/architecture.md](docs/architecture.md) for the pipeline and module
map, or [docs/intro.md](docs/intro.md) for a shorter overview.

## Requirements

- Python 3.13 or newer
- `ffmpeg`
- `uv`
- `yt-dlp`, installed separately during setup

Create `.env` from `.env.example`, then set the values you need:

- `UI_USERNAME` and `UI_PASSWORD` protect the web interface. Add
  `UI_USERNAME_2`/`UI_PASSWORD_2` or `UI_USERNAME_3`/`UI_PASSWORD_3` for more
  accounts.
- `PODCAST_DATA_DIR` moves state files, `.env`, and cookies. Docker mounts
  this directory as its data folder.
- `PODCAST_DOWNLOAD_DIR` and `PODCAST_INTERMEDIATE_DIR` override the matching
  paths in `config.ini`.

## Setup

```bash
uv sync --dev
uv pip install --prerelease allow "yt-dlp[default,curl-cffi]"
cp .env.example .env
# Edit .env and set UI_USERNAME and UI_PASSWORD.
```

`yt-dlp` is installed separately because media sites change often and fixes
usually appear in nightly releases first. `curl-cffi` helps Rumble requests
pass its Cloudflare checks.

Add one source URL per line to `urls.txt`, then review `config.ini` for paths,
delays, and retention.

## Usage

```bash
uv run python main.py
uv run python main.py -f custom_urls.txt -o ./custom_downloads -n 3
uv run python main.py --add-url "https://www.youtube.com/watch?v=..." [--skip-age-check]
uv run python main.py --add-url-stdin < new_urls.txt
uv run python main.py --download-single-url "https://videos.example.com/watch/episode-1"
uv run python main.py --download-full-playlist "https://www.youtube.com/playlist?list=..."
uv run uvicorn src.api:app --host 127.0.0.1 --port 8000
uv run python -m pytest -q
uv run python scripts/sponsorblock_smoke_check.py
```

The first command runs one queue pass. The second uses a different queue file,
output folder, and number of recent channel or playlist entries. The remaining
commands add URLs, download one URL or a full playlist, start the web
interface, run offline tests, or check the live SponsorBlock service.

To open the web interface, start Uvicorn and visit
`http://127.0.0.1:8000/`. Sign in to manage the queue. The line under the
add-source box shows the last download, when the queue last ran and how long
ago, and when the next run is due; **Run queue now** beside it starts a run
immediately without changing the schedule. Use **Settings** for cookies and
notifications, and open `/help` for cookie-export instructions.

On a phone, open the site in Chrome or Safari and choose **Install app** or
**Add to Home Screen**. The app hides the address bar and keeps you signed in
for 30 days. Installation needs HTTPS, so use a deployed instance rather than
`http://127.0.0.1`.

If YouTube blocks downloads, export fresh browser cookies:

```bash
yt-dlp --cookies-from-browser chrome --cookies cookies.txt
```

Upload the file on the **Settings** page, which then shows how many cookies
the file holds and when its sign-in stops working. That date is read from the
file, so it is an upper bound: YouTube can end a sign-in earlier. See
[docs/web-ui-security.md](docs/web-ui-security.md) for sign-in and session
details, and [docs/operations.md](docs/operations.md) for cookies and Docker.

## Configuration

Set the main options in `config.ini`:

- `urls_file`, `output_dir`, and `intermediate_dir`: queue, library, and
  temporary directories.
- `channel_count`: recent channel or playlist entries to check.
- `min_channel_video_age_hours`: minimum age for a YouTube video.
- `delay_seconds`: pause between downloads.
- `retention_days`: how long to keep channel MP3 files.
- `download_timeout_seconds`: limit for one `yt-dlp` attempt; the default is
  3600 seconds.
- `scheduled_run_hour` and `scheduled_run_interval_days`: when automatic runs
  happen. The defaults, `6` and `2`, mean 06:00 every other day on the local
  clock. The time comes from the calendar, so restarting or redeploying the
  container does not move it.
- `cookies_file` and `always_use_cookies`: whether and when to use YouTube
  cookies.
- `youtube_player_client`: YouTube player API used by `yt-dlp`; blank lets
  `yt-dlp` choose.
- `ytdlp_verbose`: add `-v` to every `yt-dlp` attempt.
- `trust_x_forwarded_for`: trust client-IP headers from a reverse proxy.

See [docs/cli-and-config.md](docs/cli-and-config.md) for the full reference.

## Browser extension

The `extension/` folder contains the Chrome and Firefox extension. It adds the
current page, or a link on it, to the queue without changing tabs or copying a
URL. It uses the same username and password as the web interface and needs no
server configuration.

Download your browser's archive from the
[latest release](https://github.com/GerardWu100/podcast-downloader/releases/latest),
or use a clone. The files must be on the computer where you browse, which may
be different from the server.

### Install it in Chrome

1. Unzip `podcast-downloader-chrome-<version>.zip`, or use this repository's
   `extension/` folder.
2. Open `chrome://extensions`.
3. Turn on **Developer mode**.
4. Select **Load unpacked** and choose the folder.

Edge, Brave, and other Chromium browsers work the same way.

### Install it in Firefox

1. Download **`podcast-downloader-firefox-<version>.xpi`** from the
   [latest release](https://github.com/GerardWu100/podcast-downloader/releases/latest).
2. Drag it onto a Firefox window.
3. Select **Add**.

Do not unzip the `.xpi`. It is signed and stays installed through restarts.
Firefox 140 or newer is required. Firefox has no release `.zip` because it
rejects unsigned add-ons through the normal install path.

For development, build the extension and load it temporarily:

```bash
uv run python scripts/build_extensions.py
```

1. Open `about:debugging#/runtime/this-firefox`.
2. Select **Load Temporary Add-on**.
3. Choose `build/firefox-extension/manifest.json`.

Firefox removes a temporary add-on when it restarts. To create a signed build
that stays installed, run:

```bash
uv run python scripts/build_extensions.py --sign
```

This writes `build/podcast-downloader-firefox-<version>.xpi`. See
[docs/browser-extension.md](docs/browser-extension.md) for the one-time API
key setup.

### Set it up once

Click the toolbar icon. Until the extension is configured, it opens the
settings page. You can also open it later by right-clicking the icon and
choosing **Options** in Chrome, or **Preferences** on its card in `about:addons`
in Firefox. Enter:

| Field | Value |
|---|---|
| Server address | Where you open the web page, such as `https://podcast.example.com` |
| Username and password | The same ones you use on the web page |

Select **Save**, allow the requested permission, then select **Test
connection**. **Connected** means setup is complete.

The extension sends only the URL, so the server applies the same rules as a URL
added on the web page.

### Use it

| Action | What gets added | Where it appears |
|---|---|---|
| Select the toolbar icon | The current page | Any page |
| Press `Alt+Shift+D` | The current page | Any page |
| Right-click the page and choose the podcast item | The current page | YouTube and Rumble |
| Right-click a link and choose the podcast item | The link | YouTube and Rumble links, anywhere you find them |

The badge shows `OK` for a new item, `=` for one already queued or downloaded,
and `!` for a problem. A notification explains errors. To show the right-click
items on another site, add its match pattern to `MENU_SITE_PATTERNS` in
`extension/background.js`.

For troubleshooting, security notes, and the equivalent API calls, see
[docs/browser-extension.md](docs/browser-extension.md).

## Error notifications

The web interface can send failed downloads to Apprise, which can forward them
to Telegram, email, Discord, or another service. In **Settings**, enter the
Apprise notification URL and select **Send test notification** before saving.

See [docs/notifications.md](docs/notifications.md).

## Docker

```bash
docker network inspect single >/dev/null 2>&1 || docker network create single
docker compose up --build -d
```

Run `./update.sh` to update a deployment. It pulls committed code and rebuilds
only when something changed. Use `./update.sh --force` after editing `.env`,
when the base image changes, or when you want to recreate the container. If
nothing is running, the script starts the deployment.

On first boot, the container creates missing files and `.env`, points
Audiobookshelf at the mounted download folder, and stores host cookies at
`$HOME/.containers/podcast-downloader/cookies.txt`. Mounted files belong to
user and group `1000:1000` by default. Set `HOST_UID` and `HOST_GID` in the
repository `.env` when the host uses different IDs. Compose mounts that file as
a runtime secret; passwords and cookies are never copied into the image.

See [docs/operations.md](docs/operations.md) for the deployment flow.

## Layout

- `main.py` and `start.py`: command-line entry point and Docker supervisor.
- `src/`: application code for downloads, media, state, and the web interface.
- `extension/`: Chrome and Firefox extension; it is not part of the server or
  Docker image.
- `tests/`: automated tests.
- `scripts/`: manual checks outside the test suite and the extension packaging
  script.
