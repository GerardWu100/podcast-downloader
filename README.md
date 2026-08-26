# Podcast Downloader

Podcast Downloader turns online videos into local MP3 files for
[Audiobookshelf](https://www.audiobookshelf.org/). It can watch YouTube
channels and playlists, download individual URLs, remove SponsorBlock
segments when data is available, and run from the command line or a browser.

## Features

- Check channels and playlists for new videos, or queue individual URLs.
- Skip YouTube Shorts and delay new videos while SponsorBlock publishes segment
  data.
- Convert audio to MP3, organize it by source, and remove old channel files.
- Store the queue, download history, and one-use age-check exceptions in
  `urls.txt`, `downloaded_urls.txt`, and `bypass_age_check_urls.txt`.
- Manage sources, activity, logs, cookies, and error notifications in the
  password-protected web interface.
- Install the web interface on a phone, or use the Chrome and Firefox extension
  to queue the current page.

See [docs/architecture.md](docs/architecture.md) for the pipeline and module
map, or [docs/intro.md](docs/intro.md) for a shorter overview.

## Requirements

- Python 3.13 or newer
- `ffmpeg`
- `uv`
- `yt-dlp`, installed separately during setup

Create `.env` from `.env.example`, then set the following values as needed:

- `UI_USERNAME` and `UI_PASSWORD` for the web interface. Add
  `UI_USERNAME_2`/`UI_PASSWORD_2` or `UI_USERNAME_3`/`UI_PASSWORD_3` for
  more accounts.
- `PODCAST_DATA_DIR` to move state files, `.env`, and cookies. Docker mounts
  this directory as its data folder.
- `PODCAST_DOWNLOAD_DIR` or `PODCAST_INTERMEDIATE_DIR` to override the
  matching `config.ini` paths.

## Setup

```bash
uv sync --dev
uv pip install --prerelease allow "yt-dlp[default,curl-cffi]"
cp .env.example .env
# Edit .env and set UI_USERNAME and UI_PASSWORD.
```

`yt-dlp` is installed separately because media sites change frequently. Nightly
releases usually receive fixes first. `curl-cffi` gives Rumble requests the
browser network fingerprint needed for its Cloudflare checks.

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

The first command runs one queue pass. The second overrides the queue file,
output folder, and number of recent channel or playlist entries. The other
commands add URLs, download one URL or a full playlist, start the web
interface, run offline tests, or run the live SponsorBlock check.

To use the web interface, start Uvicorn and open `http://127.0.0.1:8000/`.
Sign in, then manage the queue from the home page. The settings page handles
cookies and notifications. Open `/help` for cookie export instructions.

On a phone, open the site in Chrome or Safari and choose **Install app** or
**Add to Home Screen**. The app opens without an address bar, and its 30-day
session keeps you signed in. Installation needs HTTPS, so use a deployed
instance rather than `http://127.0.0.1`.

If YouTube blocks downloads, export fresh browser cookies:

```bash
yt-dlp --cookies-from-browser chrome --cookies cookies.txt
```

Upload the file on the **Settings** page. See
[docs/web-ui-security.md](docs/web-ui-security.md) for sign-in and session
details and [docs/operations.md](docs/operations.md) for cookies and Docker.

## Configuration

Change the main settings in `config.ini`:

- `urls_file`, `output_dir`, and `intermediate_dir`: queue, library, and
  scratch paths.
- `channel_count`: recent channel or playlist entries to check.
- `min_channel_video_age_hours`: minimum age for a YouTube video.
- `delay_seconds`: pause between downloads.
- `retention_days`: how long to keep channel MP3 files.
- `download_timeout_seconds`: limit for one `yt-dlp` attempt; the default is
  3600 seconds.
- `cookies_file` and `always_use_cookies`: whether and when YouTube cookies
  are used.
- `youtube_player_client`: YouTube player API used by `yt-dlp`; blank lets
  `yt-dlp` choose.
- `ytdlp_verbose`: add `-v` to every `yt-dlp` attempt.
- `trust_x_forwarded_for`: trust client-IP headers from a reverse proxy.

See [docs/cli-and-config.md](docs/cli-and-config.md) for the full reference.

## Browser extension

`extension/` contains a Chrome and Firefox extension for adding the current
page—or a link on it—to the queue. It uses the same username and password as
the web interface and needs no server-side setup.

See [docs/browser-extension.md](docs/browser-extension.md) for installation,
configuration, API details, and security notes.

Once configured, the toolbar button and `Alt+Shift+D` add the current page; the
context menu can add a page or link on YouTube and Rumble. The badge shows
`OK`, `=`, or `!` for a new, already handled, or failed submission.

### The same API, from a script

The extension signs in with an `Authorization` header rather than the browser
session. The session cookie is `HttpOnly` and `SameSite=lax`, so extension code
cannot use it. Other clients can call the same two routes:

```bash
curl -u "$USERNAME:$PASSWORD" https://your-server/api/ping
curl -X POST https://your-server/api/add-url \
  -u "$USERNAME:$PASSWORD" -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=...", "skip_age_check": false}'
```

Wrong passwords count toward the same ban as the login page: five failures in
ten minutes block that address for fifteen minutes. See
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
repository `.env` when the host uses different IDs.

See [docs/operations.md](docs/operations.md) for the deployment flow.

## Layout

- `main.py` and `start.py`: command-line entry point and Docker supervisor.
- `src/`: application code for downloads, media, state, and the web interface.
- `extension/`: browser extension for Chrome and Firefox; not part of the
  server or the Docker image.
- `tests/`: automated tests.
- `scripts/`: manual checks outside the test suite, plus the Firefox
  extension build.
- `docs/`: architecture, operations, security, configuration, and extension docs.

## Known limits

- The downloader depends on `yt-dlp` to expand channels and playlists. Changes
  to `yt-dlp` or YouTube can break that step.
- YouTube player clients and proof-of-origin requirements change over time.
  The `youtube_player_client` setting may need to change too.
- Rumble's Cloudflare checks change over time, even with Chrome request
  impersonation.
- SponsorBlock removal depends on community-submitted segment data.
- The web interface uses shared `.env` accounts and has no per-user
  permissions. Keep it on a personal, trusted network.
- The browser extension stores your web interface password in the browser's
  extension storage. Anyone with access to that browser profile can read it.
  Revoking it means changing the password, which also signs the web interface
  out.
