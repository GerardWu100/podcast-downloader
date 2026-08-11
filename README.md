# Podcast Downloader

A small, self-hosted tool that turns online videos into local MP3 files for [Audiobookshelf](https://www.audiobookshelf.org/). It monitors YouTube channels, playlists, and direct video URLs, strips SponsorBlock-tagged segments from YouTube downloads, and exposes a queue you can manage from the command line or a small web UI.

## What it does

- Downloads a direct video URL, or expands a YouTube channel/playlist and downloads its most recent videos, using `yt-dlp`.
- Filters out YouTube Shorts and waits a configurable age before downloading new YouTube uploads, so SponsorBlock has time to get segment data.
- Removes SponsorBlock-tagged segments from YouTube downloads when data exists for that video.
- Converts downloads to MP3 and writes them to a configurable output folder, grouped by source.
- Deletes old channel MP3 files past a configurable retention period.
- Tracks the queue, download history, and one-use YouTube age-check bypasses in plain local files (`urls.txt`, `downloaded_urls.txt`, `bypass_age_check_urls.txt`).
- Serves a password-protected web UI for adding/removing sources, uploading YouTube cookies, and viewing recent activity and logs.

See [docs/architecture.md](docs/architecture.md) and [docs/intro.md](docs/intro.md) for the full pipeline and module map.

## Requirements

- Python 3.13+
- `ffmpeg`
- `uv`
- `yt-dlp` (installed separately, see Setup)

Environment variables (set in `.env`, see `.env.example`):

- `UI_USERNAME` / `UI_PASSWORD` — required for the web UI. Optional second and third accounts: `UI_USERNAME_2`/`UI_PASSWORD_2`, `UI_USERNAME_3`/`UI_PASSWORD_3`.
- `PODCAST_DATA_DIR` — overrides where state files, `.env`, and cookies live (defaults to the project root; used by Docker to point at a mounted volume).
- `PODCAST_DOWNLOAD_DIR` / `PODCAST_INTERMEDIATE_DIR` — override `output_dir` / `intermediate_dir` from `config.ini`.

## Setup

```bash
uv sync --dev
uv pip install "yt-dlp[default]"
cp .env.example .env
# edit .env: set UI_USERNAME and UI_PASSWORD
```

`yt-dlp` is intentionally not pinned in `uv.lock`; install it separately so you always get the current release, since YouTube extraction changes often. Add one source URL per line to `urls.txt`, and review `config.ini` for output paths, delay, and retention settings.

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

Open `http://127.0.0.1:8000/help` for cookie-export instructions once the API is running. To get fresh YouTube cookies when downloads are blocked:

```bash
yt-dlp --cookies-from-browser chrome --cookies cookies.txt
```

Upload the resulting file through the web UI. See [docs/web-ui-security.md](docs/web-ui-security.md) for the login and session model, and [docs/operations.md](docs/operations.md) for cookie file details and Docker deployment.

## Configuration

Runtime settings live in `config.ini`. The main knobs:

- `urls_file`, `output_dir`, `intermediate_dir` — queue file and download folders.
- `channel_count` — how many recent channel/playlist videos to consider.
- `min_channel_video_age_hours` — minimum YouTube video age before download.
- `delay_seconds` — pause between downloads.
- `retention_days` — how long to keep channel MP3 files.
- `download_timeout_seconds` — per-attempt `yt-dlp` timeout (default 3600).
- `cookies_file`, `always_use_cookies` — YouTube cookie file and retry order.
- `trust_x_forwarded_for` — trust client IP headers from a reverse proxy.

## Docker

```bash
docker network inspect single >/dev/null 2>&1 || docker network create single
docker compose up --build -d
```

The container seeds missing runtime files and `.env` on first boot, points Audiobookshelf at the mounted download folder, and keeps cookies at `$HOME/.containers/podcast-downloader/cookies.txt` on the host. See [docs/operations.md](docs/operations.md) for the full deployment flow.

## Layout

- `main.py` / `start.py` — CLI entrypoint and Docker process supervisor.
- `src/` — application code (`cli.py`, `api.py`, `downloads/`, `media/`, `state/`, `web/`).
- `tests/` — automated test suite.
- `scripts/` — manual checks not run by the test suite.
- `docs/` — architecture, CLI/config reference, web UI security, and operations docs.

## Known limits

- Channel and playlist expansion parses `yt-dlp` output, so an upstream `yt-dlp` or YouTube change can break it.
- SponsorBlock removal is only as good as the community-submitted segment data for a given video.
- The web UI uses shared accounts from `.env`, not per-user permissions. It is meant for personal, trusted-network use, not public exposure.

## License

MIT. See [LICENSE](LICENSE).
