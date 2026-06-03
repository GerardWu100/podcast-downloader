# File Structure

## Root

```text
podcast-downloader/
├── config.ini
├── download_podcasts.sh
├── downloaded_urls.txt
├── downloads/
├── main.py
├── pyproject.toml
├── src/
├── test_sponsorblock.py
├── tests/
├── urls.txt
└── uv.lock
```

- `config.ini`: runtime settings for paths, channel polling, download delay, and proxy trust.
- `download_podcasts.sh`: legacy shell implementation kept as an alternative runner.
- `downloaded_urls.txt`: archive used to avoid replaying expanded channel or playlist items.
- `downloads/`: output directory for generated MP3 files.
- `main.py`: compatibility entrypoint that calls into the packaged CLI.
- `pyproject.toml`: project metadata and dependencies.
- `src/`: core Python package.
- `test_sponsorblock.py`: manual SponsorBlock smoke script that performs a live download.
- `tests/`: automated regression suite.
- `urls.txt`: queue of pending YouTube URLs.
- `uv.lock`: locked dependency graph for `uv`.

## `src/`

```text
src/
├── GUIDE_src.md
├── __init__.py
├── api.py
├── cli.py
├── config.py
├── downloader.py
└── url_utils.py
```

- `api.py`: FastAPI endpoints for login, logout, and queue submission.
- `cli.py`: command-line argument parsing and top-level CLI flow.
- `config.py`: loads `config.ini` into a typed config object.
- `downloader.py`: wraps `yt-dlp`, tracks success, logs, and updates queue/archive files.
- `url_utils.py`: URL validation, normalization, queue mutation, and channel expansion.

## `tests/`

```text
tests/
├── GUIDE_tests.md
├── test_api_behavior.py
├── test_downloader.py
└── test_security.py
```

- `test_api_behavior.py`: regression tests for forwarded-header trust and IP-bound sessions.
- `test_downloader.py`: regression tests for MP3 overwrite detection and zero-delta failures.
- `test_security.py`: existing security and URL-normalization regression coverage.
