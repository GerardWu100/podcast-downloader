# Podcast Downloader

Podcast Downloader turns online videos into local MP3 files for
[Audiobookshelf](https://www.audiobookshelf.org/). It watches YouTube channels
and playlists, downloads individual URLs, removes SponsorBlock segments when
available, and runs from the command line or a browser.

## Features

- Check channels and playlists for new videos, or queue individual URLs.
- Skip YouTube Shorts and wait before downloading new videos so SponsorBlock
  has time to publish segment data.
- Convert audio to MP3 and organize it by source.
- Remove channel MP3 files after the retention period.
- Keep the queue, download history, and one-use age-check exceptions in
  `urls.txt`, `downloaded_urls.txt`, and `bypass_age_check_urls.txt`.
- Manage sources, activity, logs, cookies, and error notifications in the
  password-protected web interface.
- Install the web interface on a phone or use the companion Chrome extension
  to queue the current page.

See [docs/architecture.md](docs/architecture.md) for the pipeline and module
map, or [docs/intro.md](docs/intro.md) for a shorter overview.

## Requirements

- Python 3.13 or newer
- `ffmpeg`
- `uv`
- `yt-dlp`, installed separately during setup

Create `.env` from `.env.example`, then set:

- `UI_USERNAME` and `UI_PASSWORD` for the web interface. Add
  `UI_USERNAME_2`/`UI_PASSWORD_2` or `UI_USERNAME_3`/`UI_PASSWORD_3` for
  more accounts.
- `PODCAST_DATA_DIR` to move state files, `.env`, and cookies. Docker uses
  this directory for its mounted data folder.
- `PODCAST_DOWNLOAD_DIR` or `PODCAST_INTERMEDIATE_DIR` to override the
  matching `config.ini` paths.

## Setup

```bash
uv sync --dev
uv pip install --prerelease allow "yt-dlp[default,curl-cffi]"
cp .env.example .env
# Edit .env and set UI_USERNAME and UI_PASSWORD.
```

`yt-dlp` is installed separately because media sites change frequently.
Nightly releases usually receive fixes first. `curl-cffi` lets Rumble requests
use the browser network fingerprint needed for its Cloudflare checks.

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
output folder, and number of recent channel or playlist entries. The remaining
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

`extension/` contains a Chrome extension that adds the page you are viewing—or
a link on that page—to the queue. Click the toolbar icon, right-click a
YouTube or Rumble link, or press `Alt+Shift+D`. The right-click items appear
only on those two sites, as set by `MENU_SITE_PATTERNS` in
`extension/background.js`; the toolbar icon works anywhere.

Load `extension/` through **Load unpacked** at `chrome://extensions`, then open
its options and enter your server address plus the same username and password
you use on the web page. Nothing needs to be configured on the server.

The extension signs in with an `Authorization` header instead of the browser
session. The session cookie is `HttpOnly` and `SameSite=lax`, so an extension
script cannot use it. The same two routes work from any script:

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
when the base image changed, or when you want to recreate the container. If
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
- `extension/`: Chrome extension; it is not part of the server or Docker image.
- `tests/`: automated tests.
- `scripts/`: manual checks outside the test suite.
- `docs/`: architecture, operations, security, configuration, and extension docs.

## Known limits

- The downloader depends on `yt-dlp` output to expand channels and playlists.
  Changes to `yt-dlp` or YouTube can break that step.
- YouTube player clients and proof-of-origin requirements change over time.
  The `youtube_player_client` setting may need to change too.
- Rumble's Cloudflare checks change over time, even with Chrome request
  impersonation.
- SponsorBlock removal depends on community-submitted segment data.
- The web interface uses shared `.env` accounts and has no per-user
  permissions. Keep it on a personal, trusted network.
- The browser extension keeps your web interface password in Chrome's
  extension storage. Anyone with access to that Chrome profile can read it,
  and revoking it means changing the password, which signs the web interface
  out too.
