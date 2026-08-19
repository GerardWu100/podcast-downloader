# Podcast Downloader

A small, self-hosted downloader that turns online videos into local MP3 files for [Audiobookshelf](https://www.audiobookshelf.org/). It watches YouTube channels and playlists, accepts individual video URLs, removes SponsorBlock-marked sections, and gives you both a command-line interface and a small web UI.

## What it does

- Downloads a video URL, or the newest videos from a YouTube channel or playlist, with `yt-dlp`.
- Ignores YouTube Shorts and waits a configurable amount of time before downloading new YouTube videos. The delay gives SponsorBlock time to publish segment data.
- Removes SponsorBlock-marked sections when data is available.
- Converts downloads to MP3 and groups them by source in a configurable folder.
- Deletes old MP3 files from YouTube channel folders after the configured retention period.
- Keeps the queue, download history, and one-use age-check exceptions in local files: `urls.txt`, `downloaded_urls.txt`, and `bypass_age_check_urls.txt`.
- Provides a password-protected web UI for managing sources, uploading YouTube cookies, and viewing recent activity and logs.

For the full pipeline and module map, see [docs/architecture.md](docs/architecture.md) and [docs/intro.md](docs/intro.md).

## Requirements

- Python 3.13+
- `ffmpeg`
- `uv`
- `yt-dlp` (installed separately during setup)

Set these values in `.env`; see `.env.example`:

- `UI_USERNAME` and `UI_PASSWORD` are required for the web UI. You can add second and third accounts with `UI_USERNAME_2`/`UI_PASSWORD_2` and `UI_USERNAME_3`/`UI_PASSWORD_3`.
- `PODCAST_DATA_DIR` changes where state files, `.env`, and cookies are stored. Docker uses it for the mounted data volume.
- `PODCAST_DOWNLOAD_DIR` and `PODCAST_INTERMEDIATE_DIR` override `output_dir` and `intermediate_dir` in `config.ini`.

## Setup

```bash
uv sync --dev
uv pip install "yt-dlp[default]"
cp .env.example .env
# edit .env: set UI_USERNAME and UI_PASSWORD
```

`yt-dlp` is installed separately rather than pinned in `uv.lock`, because YouTube extraction changes often. Add one source URL per line to `urls.txt`, then review `config.ini` for paths, delays, and retention.

## Usage

```bash
uv run python main.py                                              # run one queue pass with config.ini defaults
uv run python main.py -f custom_urls.txt -o ./custom_downloads -n 3  # override the URLs file, output dir, and video count
uv run python main.py --add-url "https://www.youtube.com/watch?v=..." [--skip-age-check]
uv run python main.py --add-url-stdin < new_urls.txt                # append URLs from stdin
uv run python main.py --download-single-url "https://videos.example.com/watch/episode-1"
uv run python main.py --download-full-playlist "https://www.youtube.com/playlist?list=..."
uv run uvicorn src.api:app --host 127.0.0.1 --port 8000            # web UI at /login
uv run python -m pytest -q                                          # test suite
uv run python scripts/sponsorblock_smoke_check.py                   # manual, live-network SponsorBlock check
```

Once the API is running, open `http://127.0.0.1:8000/help` for cookie-export instructions. If YouTube blocks downloads, create fresh cookies with:

```bash
yt-dlp --cookies-from-browser chrome --cookies cookies.txt
```

Upload the resulting file through the web UI. For login and session details, see [docs/web-ui-security.md](docs/web-ui-security.md). For cookie files and Docker deployment, see [docs/operations.md](docs/operations.md).

## Configuration

Runtime settings live in `config.ini`:

- `urls_file`, `output_dir`, and `intermediate_dir` set the queue and download folders.
- `channel_count` sets how many recent channel or playlist videos to consider.
- `min_channel_video_age_hours` sets the minimum age of a YouTube video before download.
- `delay_seconds` sets the pause between downloads.
- `retention_days` sets how long to keep channel MP3 files.
- `download_timeout_seconds` sets the timeout for one `yt-dlp` attempt (default: 3600 seconds).
- `cookies_file` and `always_use_cookies` control YouTube cookie use and retry order.
- `youtube_player_client` selects the YouTube player API that `yt-dlp` uses. Leaving it blank lets `yt-dlp` choose; that currently fails with `HTTP Error 403: Forbidden` after audio begins downloading.
- `trust_x_forwarded_for` controls whether client IP headers from a reverse proxy are trusted.

See [docs/cli-and-config.md](docs/cli-and-config.md) for the complete reference.

## Docker

```bash
docker network inspect single >/dev/null 2>&1 || docker network create single
docker compose up --build -d
```

On first boot, the container creates missing runtime files and `.env`, points Audiobookshelf at the mounted download folder, and stores host cookies at `$HOME/.containers/podcast-downloader/cookies.txt`. See [docs/operations.md](docs/operations.md) for the deployment flow.

## Layout

- `main.py` / `start.py` — command-line entrypoint and Docker process supervisor.
- `src/` — application code (`cli.py`, `api.py`, `downloads/`, `media/`, `state/`, `web/`).
- `tests/` — automated tests.
- `scripts/` — manual checks that are not part of the test suite.
- `docs/` — architecture, CLI/configuration, web UI security, and operations documentation.

## Known limits

- Channel and playlist expansion parses `yt-dlp` output. An upstream `yt-dlp` or YouTube change can break it.
- YouTube is tightening access to player clients that provide stream URLs without a proof-of-origin token. `youtube_player_client` may need to change over time.
- SponsorBlock removal depends on community-submitted segment data.
- The web UI uses shared accounts from `.env`, with no per-user permissions. Use it on a personal, trusted network rather than exposing it publicly.

## License

MIT. See [LICENSE](LICENSE).
