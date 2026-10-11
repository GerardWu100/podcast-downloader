---
name: podcast-downloader
description: Control the user's self-hosted Podcast Downloader, which turns YouTube channels, playlists, and videos into sponsor-free MP3 podcasts for Audiobookshelf. Use when the user wants to add a video, channel, or playlist to their podcasts, asks what new episodes downloaded, whether something failed, whether the downloader is working, or wants a download run now. Not for podcast research, search, or transcripts.
---

# Podcast Downloader

The user runs Podcast Downloader on their own server. You talk to it over its
small JSON API with `curl`. Everything here works from this one file.

## Install this skill

If the user asked you to install this skill, save this file as `SKILL.md` in a
folder named `podcast-downloader` in your skills directory, then do **First
use** below.

| Agent | How |
|---|---|
| Hermes | `hermes skills install https://raw.githubusercontent.com/GerardWu100/podcast-downloader/master/.agents/skills/podcast-downloader/SKILL.md` |
| OpenClaw | Save to `~/.openclaw/skills/podcast-downloader/SKILL.md`, then check with `openclaw skills list` |
| Claude Code | Save to `~/.claude/skills/podcast-downloader/SKILL.md` |
| Codex and other agents that read `~/.agents/skills` | Save to `~/.agents/skills/podcast-downloader/SKILL.md` |

## First use: connect to the server

1. Ask the user: "What address do you open Podcast Downloader at?" For
   example `http://192.168.1.20:6847`. Add `http://` to a home-network address
   typed without a scheme.
2. Save it, with no trailing slash, as the only line of
   `~/.config/podcast-downloader/server`.
3. Test it:

   ```bash
   PD_SERVER=$(cat ~/.config/podcast-downloader/server)
   curl -sS --max-time 15 "$PD_SERVER/api/ping"
   ```

   - `{"ok": true, "app": "podcast-downloader", "login_required": false, ...}`:
     done. Most servers have no login.
   - HTTP 401: the server has a login. Ask the user for the username and
     password from the server's `.env` (`UI_USERNAME`, `UI_PASSWORD`), or ask
     them to create the file themselves. Write
     `~/.config/podcast-downloader/curl.conf` containing exactly
     `user = "USERNAME:PASSWORD"`, then run
     `chmod 600 ~/.config/podcast-downloader/curl.conf`. Never print, echo, or
     repeat the password, and never put it on a command line.
   - Any other answer: show it to the user. The address is probably wrong.

## Calling the API

Start every shell session with these two lines. The second one adds the login
only when `curl.conf` exists.

```bash
PD_SERVER=$(cat ~/.config/podcast-downloader/server)
PD=(curl -sS --max-time 15); [ -f ~/.config/podcast-downloader/curl.conf ] && PD+=(-K ~/.config/podcast-downloader/curl.conf)
```

| To | Run |
|---|---|
| Add a video, channel, or playlist | `"${PD[@]}" -H 'Content-Type: application/json' -d '{"url": "URL"}' "$PD_SERVER/api/add-url"` |
| Add and download now (skip the one-day wait, or a whole playlist) | same, with `-d '{"url": "URL", "skip_age_check": true}'` |
| See what happened recently | `"${PD[@]}" "$PD_SERVER/api/activity?lines=50"` |
| List the sources | `"${PD[@]}" "$PD_SERVER/api/queue"` |
| Run every source now | `"${PD[@]}" -X POST "$PD_SERVER/api/run"` |
| Check that it is working | `"${PD[@]}" -i "$PD_SERVER/api/health"` |
| Check the connection and version | `"${PD[@]}" "$PD_SERVER/api/ping"` |

Put the URL into the JSON as is; escape a `"` or `\` inside it if there is one.

## Reading the answers

**`/api/add-url`** returns `outcome`:

| `outcome` | Tell the user |
|---|---|
| `added` with `immediate: true` | Added; a single video starts downloading now |
| `added` with `immediate: false` | Added; it downloads on the next scheduled run (06:00 every other day by default) |
| `duplicate` | Already in the queue |
| `downloaded` | Already downloaded |
| `invalid` (HTTP 400) | Not a video, channel, or playlist link |

"Added" is not "downloaded". A new YouTube video normally waits about a day,
so SponsorBlock can mark the sponsors, unless `skip_age_check` is true.

**`/api/activity`** returns `{"lines": [...]}`, oldest first, each
`[YYYY-MM-DD HH:MM] Event: detail`:

| Line starts with | Meaning |
|---|---|
| `Run started:` / `Run finished:` | Bracket one run; the finished line counts downloads and failures |
| `Downloaded:` | An MP3 is in the library; the text is the file name |
| `Failed:` | That video did not download; the reason follows the URL |
| `Waiting for age gate:` | Too new; it downloads on a later run |
| `Skipped Short:` | A YouTube Short, skipped on purpose |
| `Needs attention:` | Something the user must fix, such as YouTube blocking the server |
| `Deleted expired MP3:` | Retention removed an old episode |

To answer "what's new?", list the `Downloaded:` lines since the last time the
user asked, or from today, with show names taken from the file names.

**`/api/health`** answers 200 while runs happen on schedule, and 503 when the
due run is more than a few hours late, which means the downloader has stopped.
A brand-new server also answers 503 until its first run finishes.
**`/api/run`** answers 202 when a run started, and 409 when one is already
running.

## Rules

- On 401 the saved login is wrong; on 429 the server has blocked this machine
  for 15 minutes after repeated wrong passwords. Stop and tell the user. Never
  guess passwords.
- If an add times out, check `/api/queue` before sending it again.
- Do not start `/api/run` again while one is running, and do not run it on a
  timer. The server keeps its own schedule.
- Repeated `Failed:` lines mentioning HTTP 403 or "Sign in to confirm" mean
  YouTube is blocking the server. Tell the user to upload fresh YouTube
  cookies on the web page's **Settings** page. You cannot do that through the
  API.
- Removing a source, changing settings, cookies, and alerts are on the web
  page at the same address. Point the user there.

More detail: https://github.com/GerardWu100/podcast-downloader/wiki
