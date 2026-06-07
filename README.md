# Podcast Downloader

Podcast Downloader is a self-hostable podcast downloader for [Audiobookshelf](https://www.audiobookshelf.org/) that turns web videos into MP3 files for local playback. It is designed for downloading podcasts without ads, including sponsor ads inserted by podcasters, by using `yt-dlp` and SponsorBlock. It handles YouTube channels, playlists, livestreams, and direct video URLs, removes SponsorBlock segments where available, and keeps the queue manageable from either the CLI or a small web UI.

## What It Does

- Expands YouTube channels and playlists into the latest configured number of individual video downloads.
- Downloads direct video URLs as single items.
- Removes SponsorBlock segments from supported YouTube downloads.
- Writes finished MP3 files into a configurable output folder.
- Keeps queue, archive, and login state in simple local files.
- Exposes a lightweight browser UI for adding URLs and removing monitored entries.

## Docker First

The project is designed to run cleanly in Docker for the common Audiobookshelf workflow.

```bash
docker compose up --build -d
```

On first boot, the container seeds missing runtime files, copies a repo-root `.ui_password` into the mounted data directory when present, and accepts both hashed and legacy plain-text password files. If you need browser cookies for blocked YouTube downloads, add a Netscape-format `cookies.txt` to the mounted data directory or set `cookies_file` in `config.ini`.

Finished MP3 files are written to the configured download directory. Point Audiobookshelf at that folder so it can scan the completed audio library.

## Requirements

- Python 3.13+
- `ffmpeg`
- `uv`

`yt-dlp` is installed as part of the project environment.

## Quick Start

1. Install system dependencies.
2. Sync the Python environment:

```bash
uv sync --dev
```

3. Add one source URL per line to `urls.txt`.
4. Review `config.ini` for output paths, delay settings, channel polling depth, retention, and proxy behavior.
5. If you plan to use the web UI, create `.ui_password`.

Generate a hashed UI password from the terminal:

```bash
uv run python -c 'from src.passwords import hash_password; import getpass; print(hash_password(getpass.getpass("Password: ")))' > .ui_password
```

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
uv run python test_sponsorblock.py
```

`--skip-age-check` only applies with `--add-url` or `--add-url-stdin`, and only for direct YouTube URLs. `--download-single-url` runs exactly one direct media URL through the single-item path.

## Web UI

Open [http://127.0.0.1:8000/login](http://127.0.0.1:8000/login) after starting the API with `uv run uvicorn src.api:app --host 127.0.0.1 --port 8000`.

The UI lets you add URLs, remove monitored entries from `urls.txt`, and view recent activity or the full `download.log` tail. Remembered sessions can survive restarts for up to 30 days, and failed logins are tracked in `.login_state.json`.

## Key Configuration

All runtime settings live in `config.ini`.

- `urls_file`: monitored queue file.
- `output_dir`: destination for finished MP3 files.
- `intermediate_dir`: scratch folder for downloads and metadata passes.
- `channel_count`: how many recent channel or playlist videos to consider.
- `min_channel_video_age_hours`: minimum age for YouTube direct videos and channel uploads.
- `delay_seconds`: sleep between downloads.
- `retention_days`: how long to keep channel MP3 files before cleanup.
- `log_file`: full runtime log path.
- `downloaded_urls_file`: archive for expanded URLs.
- `bypass_age_check_file`: one-shot age-gate overrides.
- `cookies_file`: optional Netscape-format cookie fallback.
- `trust_x_forwarded_for`: whether the UI trusts proxy-forwarded client IPs.

## Project Layout

- `main.py`: CLI compatibility entrypoint.
- `start.py`: Docker-oriented process supervisor.
- `config.ini`: default runtime configuration.
- `src/`: application code.
- `tests/`: automated regression coverage.
- `downloads/`: generated MP3 files.
- `docs/`: longer-form project documentation.
- `test_sponsorblock.py`: manual live-network smoke script.

## Documentation

If you want the deeper design and operations details, start with these files:

- [docs/intro.md](docs/intro.md)
- [docs/architecture.md](docs/architecture.md)
- [docs/cli-and-config.md](docs/cli-and-config.md)
- [docs/web-ui-security.md](docs/web-ui-security.md)
- [docs/operations.md](docs/operations.md)
- [docs/review-and-safety.md](docs/review-and-safety.md)

## Notes

- The project is optimized for a personal Audiobookshelf-backed workflow rather than a multi-user public service.
- The web UI is intentionally lightweight and uses local file-based state for queueing and login persistence.
- Docker deployments seed missing files on first boot so a fresh volume can start without manual setup.
