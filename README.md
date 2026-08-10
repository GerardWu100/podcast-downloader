# Podcast Downloader

Podcast Downloader is a small, self-hosted tool for [Audiobookshelf](https://www.audiobookshelf.org/). It turns online videos into local MP3 files and removes sponsor segments from YouTube downloads when SponsorBlock has data for them. You can manage the download queue from the command line or the small web interface.

## What It Does

- Finds the latest configured videos from monitored YouTube channels and playlists.
- Downloads a direct video URL as one item.
- Removes SponsorBlock segments from supported YouTube downloads.
- Writes finished MP3 files to a configurable folder.
- Keeps the queue, download history, and login state in simple local files.
- Provides a small browser UI for adding and removing monitored sources.

## Docker First

The project is designed to run cleanly in Docker for the common Audiobookshelf workflow.

```bash
docker compose up --build -d
```

On startup, the container creates missing runtime files. It also copies the repo-root `.env` (or `.env.example` when no `.env` exists) into the mounted data directory the first time that directory is used. The app hashes the `.env` password into `.ui_credentials.json` and checks the hash automatically; no separate hashing command is needed. Runtime cookies live at `$HOME/.containers/podcast-downloader/cookies.txt` on the host and are mounted as `/data/cookies.txt` in the container. A repo-root Netscape-format `cookies.txt` is used only to seed a missing mounted cookie file.

Finished MP3 files are written to the configured download directory. Point Audiobookshelf at that folder so it can scan the completed audio library.

## Requirements

- Python 3.13+
- `ffmpeg`
- `uv`

`yt-dlp` is installed outside the lockfile with `uv pip install "yt-dlp[default]"`. Docker builds and container starts install the current PyPI release and its default YouTube challenge-solving dependencies. The image also includes Deno, the JavaScript runtime used by current YouTube extraction.

## Quick Start

1. Install system dependencies.
2. Sync the Python environment:

```bash
uv sync --dev
uv pip install "yt-dlp[default]"
```

`yt-dlp` is intentionally **not** pinned in `uv.lock`. Run `uv pip install "yt-dlp[default]"` after syncing to install the current release. Docker does this during the image build and at container startup.

3. Add one source URL per line to `urls.txt`.
4. Review `config.ini` for output paths, delay settings, channel polling depth, retention, and proxy behavior.
5. If you plan to use the web UI, copy `.env.example` to `.env` and set `UI_USERNAME` and `UI_PASSWORD`:

```bash
cp .env.example .env
# edit .env: set UI_USERNAME and UI_PASSWORD
```

On startup the app hashes `UI_PASSWORD` with Password-Based Key Derivation Function 2 (PBKDF2), checks the hash, and stores only the hash in `.ui_credentials.json`. The login form asks for the username and password from `.env`.

Start the downloader:

```bash
uv run python main.py
```

## Common Commands

```bash
uv run python main.py --add-url "https://www.youtube.com/watch?v=..."
uv run python main.py --add-url "https://www.youtube.com/watch?v=..." --skip-age-check
uv run python main.py --add-url-stdin < new_urls.txt
uv run python main.py --download-single-url "https://videos.example.com/watch/episode-1"
uv run python main.py -f custom_urls.txt -o ./custom_downloads -n 3
uv run uvicorn src.api:app --host 127.0.0.1 --port 8000
uv run python -m pytest -q
uv run python scripts/sponsorblock_smoke_check.py
```

`--skip-age-check` only applies with `--add-url` or `--add-url-stdin`, and only for direct YouTube URLs. `--download-single-url` runs exactly one direct media URL through the single-item path.

## Web UI

Open [http://127.0.0.1:8000/login](http://127.0.0.1:8000/login) after starting the API with `uv run uvicorn src.api:app --host 127.0.0.1 --port 8000`.

The UI lets you add sources, remove entries from `urls.txt`, upload a replacement YouTube `cookies.txt`, and view recent activity or the end of `download.log`. Its status row shows whether the service is online, how many sources are monitored, and when activity was last recorded. A short usage and cookie-export guide is available at [http://127.0.0.1:8000/help](http://127.0.0.1:8000/help). Remembered sessions can survive restarts for up to 30 days, and failed logins are tracked in `.login_state.json`.

## Getting YouTube Cookies

When YouTube asks yt-dlp to sign in or confirm that you are not a bot, export fresh browser cookies and upload the file through the web UI. Follow the official yt-dlp FAQ: [How do I pass cookies to yt-dlp?](https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp).

Recommended export command on the machine where your browser profile is available:

```bash
yt-dlp --cookies-from-browser chrome --cookies cookies.txt
```

Replace `chrome` with your browser name if needed. The resulting file can have any local filename before upload, but its contents must be Mozilla/Netscape cookie text. For this app's browser upload, the first line should be:

```text
# Netscape HTTP Cookie File
```

Keep the exported file private. yt-dlp warns that it can contain cookies for every site in that browser profile, not just YouTube.

## Key Configuration

All runtime settings live in `config.ini`.

- `urls_file`: monitored queue file.
- `output_dir`: destination for finished MP3 files.
- `intermediate_dir`: temporary folder used before files are published.
- `channel_count`: how many recent channel or playlist videos to consider.
- `min_channel_video_age_hours`: minimum age for YouTube direct videos and channel uploads.
- `delay_seconds`: sleep between downloads.
- `retention_days`: how long to keep channel MP3 files before cleanup.
- `download_timeout_seconds`: time limit for one `yt-dlp` attempt, covering the download plus the MP3 conversion. Defaults to 3600 (one hour). Raise it if long episodes time out.
- `log_file`: full runtime log path. The file rotates at 5 MB and keeps three older copies.
- `downloaded_urls_file`: history of expanded URLs that finished successfully.
- `bypass_age_check_file`: one-use overrides for the YouTube age wait.
- `cookies_file`: optional Netscape-format cookie file for YouTube.
- `always_use_cookies`: when `true` (default), use cookies first and retry without them once; when `false`, try without cookies first and retry with them once.
- `trust_x_forwarded_for`: whether the UI trusts client IP information supplied by your reverse proxy.

## Project Layout

- `main.py`: CLI compatibility entrypoint.
- `start.py`: Docker-oriented process supervisor.
- `config.ini`: default runtime configuration.
- `src/`: application code.
- `tests/`: automated regression coverage.
- `downloads/`: generated MP3 files.
- `docs/`: longer-form project documentation.
- `scripts/`: manual, run-by-hand checks that are not part of the test suite.

## Documentation

If you want the deeper design and operations details, start with these files:

- [docs/intro.md](docs/intro.md)
- [docs/architecture.md](docs/architecture.md)
- [docs/cli-and-config.md](docs/cli-and-config.md)
- [docs/web-ui-security.md](docs/web-ui-security.md)
- [docs/operations.md](docs/operations.md)

## Notes

- The project is intended for a personal Audiobookshelf workflow, not a public multi-user service.
- The web UI is intentionally small and uses local files for the queue and login state.
- Docker deployments seed missing files on first boot so a fresh volume can start without manual setup. Compose keeps runtime cookies in the mounted data directory and only uses repo-root `cookies.txt` as a missing-file seed.

## Known limits

- Downloads depend on `yt-dlp`, `ffmpeg`, and current YouTube behavior. Channel and playlist expansion parses `yt-dlp` output, so an upstream format change can break it.
- SponsorBlock removal is only as good as the community-submitted segment data for a given video.
- Login is one shared account from `.env`, not per-user authentication. Suitable for personal admin use, not broad public exposure.
