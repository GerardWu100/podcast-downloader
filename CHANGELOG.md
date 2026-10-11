# Changelog

One version covers the server, the Docker image, and the browser extension.

## Unreleased

- The queue lists sources by channel, playlist, or video name, with a
  Channel / Playlist / Video tag, instead of raw URLs. Names are looked up once
  in the background and kept in `source_names.json`.
- `GET /api/queue` returns `{"url", "name", "kind"}` for each source instead of
  a plain URL list.
- The list's heading is now just **Sources**.

## 2.0.0 — 2026-10-11

The first release of the server as a ready-made Docker image. Install with one
Compose file or one `docker run` command; no clone, no build, no config file to
write. See the [README](https://github.com/GerardWu100/podcast-downloader#readme).

### ⚠️ Upgrading from a clone-based setup

- **Settings moved from `config.ini` to `config.toml`.** The first start
  creates `config.toml` with the default values and ignores `config.ini`. Copy
  any value you changed into `config.toml` (text values now need quotes), run
  `docker compose restart`, then delete `config.ini`. A typo or wrong type now
  stops the container with a message naming the setting, instead of silently
  using the default.
- **Login is now optional.** If your `.env` sets `UI_USERNAME` and
  `UI_PASSWORD`, nothing changes. A new install has no login.

### Install and update

- Published image `ghcr.io/gerardwu100/podcast-downloader` for amd64 and arm64.
  Pin `:2.0.0`, `:2.0`, or `:2`, or follow `:latest`.
- The image sets its own folder paths, so `docker run` needs only three folder
  mounts, a port, and `TZ`.
- The example Compose file needs no `.env` and creates the shared `single`
  network itself.

### Web page

- Login is optional and off by default. A wrong account in `.env` locks the
  page instead of opening it.
- **Settings → Keep episodes**: choose how many days to keep channel episodes.
  The next run uses it; no restart.
- The activity panel's two dropdowns became **Activity / Detailed log** tabs
  and clickable counts (**4 failed**) that filter the log.

### For agents and scripts

- New agent skill: tell Hermes, OpenClaw, Claude Code, or Codex to install it
  from its URL, and it can add videos, report what downloaded, start runs, and
  check health.
- New API routes: `GET /api/queue`, `GET /api/activity`, `POST /api/run`.
  `GET /api/ping` now reports `version` and `login_required`.

### Browser extension

- Username and password are optional, for servers with login off.
- **Save and test** in one step; it reports the server version and login mode.
- A notification on success says whether the episode downloads now or on the
  next run (can be turned off). The button's tooltip repeats the last result.
- Right-clicking a YouTube player embedded in another site adds that video.
- Requests give up after 15 seconds instead of hanging.
- Clear errors when the address points at another app or a proxy login page,
  when the browser permission was removed, and for rejected requests.
- An address typed without `http://` uses http for home-network servers
  (`192.168.x.x`, `localhost`, `.local`) and https otherwise.
- The settings page shows the keyboard shortcut actually assigned, with a
  button to change it.

### Documentation

- The README is now a user guide with a diagram and screenshot.
- Developer documentation moved to the
  [wiki](https://github.com/GerardWu100/podcast-downloader/wiki).
