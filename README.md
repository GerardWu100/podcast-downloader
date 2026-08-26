# Podcast Downloader

A small, self-hosted tool that turns online videos into local MP3 files for
[Audiobookshelf](https://www.audiobookshelf.org/). It watches YouTube channels
and playlists, downloads individual video URLs, removes SponsorBlock segments,
and runs from either the command line or a browser.

## What it does

- Checks YouTube channels and playlists for new videos, and downloads individual URLs.
- Skips YouTube Shorts and waits before downloading new videos so SponsorBlock has time to publish segment data.
- Removes SponsorBlock segments when data is available.
- Converts downloads to MP3 and groups them by source.
- Removes old channel MP3 files after the retention period.
- Stores the queue, download history, and one-time age-check exceptions in `urls.txt`, `downloaded_urls.txt`, and `bypass_age_check_urls.txt`.
- Provides a password-protected browser interface for sources, activity, logs, YouTube cookies, and error notifications.
- Can be installed on a phone from any browser, without an app store or extension.

See [docs/architecture.md](docs/architecture.md) for the pipeline and module
map. [docs/intro.md](docs/intro.md) is a shorter overview.

## Requirements

- Python 3.13+
- `ffmpeg`
- `uv`
- `yt-dlp` (installed separately during setup)

Create `.env` from `.env.example`, then set these values:

- `UI_USERNAME` and `UI_PASSWORD` are required for the browser interface. Add a second or third account with `UI_USERNAME_2`/`UI_PASSWORD_2` and `UI_USERNAME_3`/`UI_PASSWORD_3` if needed.
- `PODCAST_DATA_DIR` changes where state files, `.env`, and cookies are stored. Docker uses it for the mounted data folder.
- `PODCAST_DOWNLOAD_DIR` and `PODCAST_INTERMEDIATE_DIR` override `output_dir` and `intermediate_dir` in `config.ini`.

## Setup

```bash
uv sync --dev
uv pip install --prerelease allow "yt-dlp[default,curl-cffi]"
cp .env.example .env
# edit .env: set UI_USERNAME and UI_PASSWORD
```

`yt-dlp` is installed separately because media sites change often. Nightly
releases usually get extractor fixes first. The `curl-cffi` package lets Rumble
requests use the browser fingerprint needed for its Cloudflare checks.

Add one source URL per line to `urls.txt`, then review `config.ini` for paths,
delays, and retention.

## Usage

```bash
uv run python main.py                                              # run one queue pass with config.ini defaults
uv run python main.py -f custom_urls.txt -o ./custom_downloads -n 3  # override the URLs file, output dir, and video count
uv run python main.py --add-url "https://www.youtube.com/watch?v=..." [--skip-age-check]
uv run python main.py --add-url-stdin < new_urls.txt                # append URLs from stdin
uv run python main.py --download-single-url "https://videos.example.com/watch/episode-1"
uv run python main.py --download-full-playlist "https://www.youtube.com/playlist?list=..."
uv run uvicorn src.api:app --host 127.0.0.1 --port 8000            # start the web interface; the queue is at /
uv run python -m pytest -q                                          # run the test suite
uv run python scripts/sponsorblock_smoke_check.py                   # run a live SponsorBlock check
```

On a phone, open the site in Chrome or Safari and choose "Install app" or
"Add to Home Screen". It opens in its own window without an address bar, and
the 30-day session keeps you signed in. Installation requires HTTPS, so use a
deployed instance rather than local `http://127.0.0.1`.

With the web interface running, open `http://127.0.0.1:8000/` and sign in.
You return to the queue after signing in. On the settings page, click the title
in the top-left corner to return to the queue.

Open `http://127.0.0.1:8000/help` for cookie-export instructions. If YouTube
blocks downloads, create fresh cookies with:

```bash
yt-dlp --cookies-from-browser chrome --cookies cookies.txt
```

Upload the resulting file on the **Settings** page. See
[docs/web-ui-security.md](docs/web-ui-security.md) for login and session
details. See [docs/operations.md](docs/operations.md) for cookies and Docker
deployment.

## Configuration

Change the main settings in `config.ini`:

- `urls_file`, `output_dir`, and `intermediate_dir` set the queue and download folders.
- `channel_count` sets how many recent channel or playlist videos to check.
- `min_channel_video_age_hours` sets how old a YouTube video must be before download.
- `delay_seconds` sets the pause between downloads.
- `retention_days` sets how long to keep channel MP3 files.
- `download_timeout_seconds` sets the timeout for one `yt-dlp` attempt (default: 3600 seconds).
- `cookies_file` and `always_use_cookies` control when YouTube cookies are used and the order of retries.
- `youtube_player_client` selects the YouTube player API used by `yt-dlp`. Leaving it blank lets `yt-dlp` choose; that currently fails with `HTTP Error 403: Forbidden` after audio starts downloading.
- `ytdlp_verbose` adds `-v` to every `yt-dlp` attempt. It is off by default because retry attempts are already verbose.
- `trust_x_forwarded_for` controls whether client IP headers from a reverse proxy are trusted.

See [docs/cli-and-config.md](docs/cli-and-config.md) for the complete
reference.

## Error notifications

The browser interface can send failed downloads to Apprise, which can forward
them to Telegram, email, Discord, or another service. Open **Settings**, enter
the Apprise notification URL under **Error notifications**, and press **Send
test notification** before saving. Each field includes an example.

See [docs/notifications.md](docs/notifications.md).

## Docker

```bash
docker network inspect single >/dev/null 2>&1 || docker network create single
docker compose up --build -d
```

To update a running deployment, run `./update.sh`. It pulls the committed code,
then stops, rebuilds, and restarts the containers. It works from any directory
and stops at the first failure, so a failed pull cannot quietly redeploy old
code.

On first boot, the container creates missing files and `.env`, points
Audiobookshelf at the mounted download folder, and stores host cookies at
`$HOME/.containers/podcast-downloader/cookies.txt`. Mounted files belong to
user and group `1000:1000` by default, so downloaded podcasts can be deleted
without `sudo`. If the host uses different IDs, set `HOST_UID` and `HOST_GID`
in the repository `.env` to the values from `id -u` and `id -g`.
See [docs/operations.md](docs/operations.md) for the deployment flow.

## Layout

- `main.py` / `start.py` — command-line entry point and Docker process supervisor.
- `src/` — application code (`cli.py`, `api.py`, `downloads/`, `media/`, `state/`, `web/`).
- `tests/` — automated tests.
- `scripts/` — manual checks that are not part of the test suite.
- `docs/` — architecture, CLI/configuration, web UI security, and operations documentation.

## Known limits

- The downloader reads `yt-dlp` output to find videos in channels and playlists, so an update to either `yt-dlp` or YouTube can break this step.
- YouTube is tightening access to player clients that provide stream URLs without a proof-of-origin token. `youtube_player_client` may need to change over time.
- Rumble uses changing Cloudflare checks. The downloader uses Chrome request impersonation, but a future Rumble change may still require a newer `yt-dlp` nightly release.
- SponsorBlock removal depends on community-submitted segment data.
- The browser interface uses shared accounts from `.env` and has no per-user permissions. Use it on a personal, trusted network rather than exposing it publicly.
