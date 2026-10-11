---
title: Development
sidebar_position: 8
---

# Development

How to run the code from a checkout, test it, and ship it. For what the parts
do, read [Architecture](architecture.md) first.

## Run from a checkout

You need Python 3.13+, `ffmpeg`, and [`uv`](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/GerardWu100/podcast-downloader.git
cd podcast-downloader
uv sync --dev
uv pip install --prerelease allow "yt-dlp[default,curl-cffi]"
cp .env.example .env    # optional: set UI_USERNAME and UI_PASSWORD for a login
uv run uvicorn src.api:app --host 127.0.0.1 --port 8000
```

`yt-dlp` is not in `uv.lock`. It is installed separately because YouTube fixes
usually appear in its nightly releases first, and the container upgrades it at
every start. `curl-cffi` gets Rumble past its Cloudflare checks.

A local run keeps `config.toml`, the queue, logs, and state in the project
root. Set `PODCAST_DATA_DIR` to keep them somewhere else.

`uvicorn` alone serves the web page but never runs the schedule. `start.py`
runs both, the way the container does:

```bash
uv run python start.py
```

## Command line

Everything the web page does is also a command, so scripts and agents need no
browser session.

| Command | Does |
|---|---|
| `uv run python main.py` | One pass over the queue in `urls.txt` |
| `uv run python main.py -f my_urls.txt -o ./out -n 3` | Same, with another queue file, output folder, and number of recent videos |
| `uv run python main.py --add-url "<url>"` | Add a URL to the queue (`--skip-age-check` to skip the wait once) |
| `uv run python main.py --add-url-stdin < new_urls.txt` | Add many URLs |
| `uv run python main.py --download-single-url "<url>"` | Download one video now |
| `uv run python main.py --download-full-playlist "<url>"` | Download a whole playlist |
| `uv run python main.py --download-source-now "<url>"` | Run one saved source now |

See [CLI and Config](cli-and-config.md) for every flag and setting.

AI agents can use [the CLI skill](https://github.com/GerardWu100/podcast-downloader/blob/master/.agents/skills/podcast-downloader-cli/SKILL.md).
Keep the server address and login in an ignored `.env`, never in the skill.

## Tests and checks

```bash
uv run python -m pytest -q                         # offline test suite
uv run python scripts/sponsorblock_smoke_check.py  # live SponsorBlock check
```

The suite needs no network. The smoke check calls the real SponsorBlock API,
so it stays outside `tests/`.

## Project layout

| Path | Holds |
|---|---|
| `main.py`, `start.py` | Command-line entry point; container supervisor (web server plus scheduler) |
| `src/downloads/` | Download orchestration, `yt-dlp`, MP3 tags |
| `src/media/` | URL validation and YouTube rules |
| `src/state/` | Queue, archive, activity, login, and last-run files, each behind a lock |
| `src/web/` | Web pages, JSON API, login, and browser security |
| `src/notifications/` | Apprise alerts |
| `config.toml` | Shipped settings; the container copies it on first start |
| `extension/` | Chrome and Firefox extension; not part of the server image |
| `docs/` | This documentation; the source of the GitHub wiki |
| `tests/`, `scripts/` | Automated tests; manual checks and packaging tools |

Each folder that needs one has a `GUIDE_*.md` with the design reasons and a
dated journal of changes.

## Docker from a checkout

`docker-compose.yml` builds the image from the checkout instead of pulling it.
It needs a `.env` in the repository and the `single` network:

```bash
cp .env.example .env
docker network inspect single >/dev/null 2>&1 || docker network create single
docker compose up --build -d
```

`./update.sh` pulls new commits and rebuilds only when something changed.
`./update.sh --force` rebuilds anyway, for example after editing `.env`.

## Releases

| What | How it ships |
|---|---|
| Server image | Each push to `master` that changes the server builds `ghcr.io/gerardwu100/podcast-downloader` for amd64 and arm64, tagged `latest` and `sha-<commit>`. Start a build by hand from the Actions tab. |
| Browser extension | `uv run python scripts/build_extensions.py --zip --sign`, then attach the archives to a GitHub release. See [Browser Extension](browser-extension.md). |
| Wiki | `uv run python scripts/publish_wiki.py` copies `docs/` to the GitHub wiki. Edit `docs/`, never the wiki itself; the next publish overwrites it. |
