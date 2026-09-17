# Project thoughts, 2026-08-31

Written by Claude (Fable 5) after reviewing the full codebase, documentation,
extension, Docker setup, blog draft, and git history. No code was changed.

## First, a problem: AGENTS.md is empty

The instructions say that AGENTS.md contains the project's ultimate goal and
intent. It does not: the file is zero bytes and was committed empty on
2026-08-24 alongside CLAUDE.md and GEMINI.md (commit e3ac2da). CLAUDE.md only
says `@AGENTS.md`, so every AI session in this repository currently starts
without a goal statement.

Everything below therefore uses a goal inferred from README, docs/intro.md, and
the blog draft:

> Reliably turn selected online video sources (mostly YouTube channels and
> playlists) into a clean, sponsor-free MP3 podcast library in Audiobookshelf,
> self-hosted with as little ongoing manual attention as possible.

Two words matter most: *reliably* and *little attention*. The blog title makes
the same point: "A Podcast Downloader That Does Not Trust Exit Code 0". If
this inference is wrong, the first thing to do after reading this file is
correct it in AGENTS.md.

## 1. What the project does today

This is a mature, working system, not a prototype. The pipeline in
`src/downloads/service.py` and `src/media/youtube.py` does the following:

- Reads `urls.txt`, which holds three input kinds: direct media URLs, YouTube
  channels (with `/videos` vs `/streams` tab selection), and YouTube
  playlists.
- Expands channels and playlists with `yt-dlp --flat-playlist`, capped at
  `channel_count` recent entries. It filters out Shorts and videos younger than
  `min_channel_video_age_hours` (24 hours by default), giving SponsorBlock
  time to publish its data.
- Downloads audio as MP3. For YouTube, SponsorBlock removes sponsor segments
  and self-promotion. Rumble uses Chrome impersonation through `curl-cffi`.
  YouTube uses the pinned `web_embedded` player client to avoid the PO-token
  403 problem. Retries first use cookies and then fall back without cookies.
- Decides whether a download worked by checking the filesystem rather than the
  exit code. Before and after each attempt, it snapshots MP3 files in the
  source's scratch folder, including modification time and size. An attempt
  succeeds only when a file appears or changes. There is also a narrow recovery
  path for a folder containing exactly one pre-existing MP3.
- Adds the local completion time to the MP3's `date` tag and the source URL to
  its `comment` tag through an ffmpeg copy pass that preserves the inode. It
  then moves the file from the scratch directory into the Audiobookshelf
  library (`downloads/<source-folder>/`, with one-off files in `singles/`).
- Runs retention cleanup for channel MP3s older than `retention_days`. It uses
  the embedded metadata as proof, deletes the file, and removes the matching
  archive entry. Playlist and single files are never deleted automatically.
- Keeps state in advisory-locked plain files (`urls.txt`,
  `downloaded_urls.txt`, `bypass_age_check_urls.txt`, and session/login JSON).
  A separate download-claim lock keeps the web UI responsive while yt-dlp runs.

Around that core, the project includes:

- A FastAPI web UI (`src/web/`) with login, PBKDF2-hashed passwords, up to
  three accounts, IP bans after failed attempts, CSRF tokens, a strict CSP,
  30-day sessions, queue management, activity and log viewers, cookie upload
  with format validation, Apprise notification settings with a test button,
  and a PWA manifest for installation as a phone app.
- A JSON API (`/api/ping`, `/api/add-url`) using HTTP Basic authentication.
  It shares account and ban logic with the login form, and both interfaces use
  `queue_actions.py`, so their queue rules match.
- Chrome and Firefox extensions (Manifest V3), including a signed `.xpi` for
  Firefox built with AMO credentials. `scripts/build_extensions.py` builds the
  release archives.
- Docker deployment: `start.py` supervises Uvicorn and a scheduler thread
  that runs the CLI every `DOWNLOAD_INTERVAL_HOURS` (48 hours by default).
  The UI can also trigger immediate single-URL and full-playlist runs through
  in-process queues. The container updates yt-dlp nightly at startup, repairs
  file ownership, seeds state, and supports pull-and-rebuild deployments with
  `update.sh`.
- Failure notifications through Apprise (Telegram, email, and other services).
- 302 offline tests, a complete `docs/` set, per-folder GUIDE files, a
  `CODE_EXPLAINED.html` walkthrough, and a finished bilingual blog draft.

The README and documentation describe the code accurately. That is worth
calling out: there is no meaningful gap between the claimed behavior and the
actual behavior.

## 2. The gap between today and the inferred goal

Against the goal of a reliable, low-attention podcast library, the build phase
is essentially **done**. The remaining problem is that the system cannot yet
tell you when it has quietly stopped working.

**Built and solid:** download correctness, concurrency safety, deployment, and
input convenience through the UI, API, extension, and phone app are complete
and tested.

**Half-built:**

- *Failure visibility.* Apprise reports each failed download, but there is no
  heartbeat. If the scheduler dies, cookies expire, or YouTube blocks the
  player client and every expansion returns empty, the system goes silent. That
  silence looks exactly like "no new episodes this week." For a low-attention
  tool, silent failure is the biggest remaining gap.
- *The PO-token contingency.* `config.ini` says that `web_embedded` works
  "currently" and that the durable fix is a PO-token provider plugin. The
  fallback is documented, but nothing detects when it becomes necessary or
  tells you what to change.
- *Per-source policy.* `channel_count`, `retention_days`, and the age gate are
  global. That is fine for now, but it will become a limitation when one
  prolific channel needs different settings from the rest.

**Not started:**

- AGENTS.md content (see above).
- Any success/health reporting: last successful run per source, cookie age,
  consecutive-failure counts.
- Anything beyond MP3 files in folders, such as chapters, RSS, or transcripts.
  This is mostly fine: Audiobookshelf makes RSS unnecessary.

## 3. Recommended next steps, in order

1. **Write AGENTS.md.** It is the stated anchor for every AI session, yet it is
   empty. State the goal, what "done" means, and what is out of scope. This
   gives future work a stable direction.

2. **Add a heartbeat or periodic digest notification.** The Apprise plumbing
   and scheduler already exist, so this is a small-to-medium addition. After
   each scheduled run, or once a week, send the number downloaded, the number
   failed, the last success for each source, and the cookie file's age. A run
   that crashes before sending anything will then be detectable by the missing
   message. This directly addresses the largest remaining threat.

3. **Detect the 403/PO-token failure mode.** This should be small. When YouTube
   attempts repeatedly fail with `HTTP Error 403`, or expansions return empty,
   send one targeted notification naming the likely cause and the fix: change
   `youtube_player_client` or install a PO-token provider. The configuration
   already contains this knowledge; the failure path should use it too.

4. **Show cookie freshness.** Cookie expiry is the most common recurring
   chore. Show the cookie file's age and the last cookie-assisted success in
   Settings, and include both in the digest. This turns "why did downloads
   stop?" into a one-line answer.

5. **Pin yt-dlp to the last known-good version and support rollback.** Today,
   every container start upgrades to the nightly build. If a nightly regresses,
   deployment breaks with no recorded way to reproduce yesterday's working
   state. Record the version after each fully successful run and fall back to
   it when failures spike. The counterargument is that nightlies often fix
   YouTube breakage faster than they cause it, so keep auto-update as the
   default and make rollback the exception.

Deliberately **not** on the list: per-source configuration, more sites,
transcripts, and multi-user support. None serves the goal of reliability and
low maintenance as directly as the five items above. Per-source configuration
can wait until there is a concrete need.

## 4. Implicit decisions and hidden assumptions

- **The episode-loss window is real and unrecorded.** With `channel_count = 2`
  and a scheduler that runs every 48 hours, a channel that publishes more than
  two eligible videos between runs silently loses the extras. They are never
  archived, so nothing retries them, and nothing records that they were seen
  but skipped. This is harmless for daily-or-slower podcasts but matters for a
  prolific channel. A cheap fix is to log a warning when an expansion returns
  exactly `channel_count` items, since the cap was probably reached. The more
  expensive lesson is that, without a record of what was seen, missing
  episodes may be impossible to reconstruct months later.
- **MP3 tags are the database.** Retention identity lives in the `date` and
  `comment` tags. This is elegant and self-healing, but another tool must not
  rewrite these tags without preserving them. A tag editor or future
  normalization pass could otherwise break retention. This invariant belongs
  in AGENTS.md.
- **The design assumes one host and one instance.** The advisory `fcntl` locks
  and in-process trigger queues assume one machine and one container. That is
  fine, but the data directory should never be mounted over a network
  filesystem or used by two replicas.
- **Retention only covers channels.** Playlist folders and `singles/` grow
  forever, so disk usage is unbounded over the long term. A digest line showing
  total library size would make the problem visible early.
- **Google-account risk is undocumented.** Automated downloading with cookies
  from a personal account could cause that account to be flagged. If the
  account matters, that risk is a real cost hidden behind the convenience. The
  documentation explains cookie mechanics thoroughly but never suggests using
  a throwaway account. One paragraph in docs/operations.md would help.
- **A simpler path was considered and passed over, and that is now fine.**
  Tools such as ytdl-sub, Pinchflat, and Tube Archivist cover much of this
  ground. The custom build is now tested and tailored to this use case,
  including the SponsorBlock timing gate and the inode-preserving tag pass for
  Audiobookshelf. Migrating would therefore be a loss. Still, before adding a
  feature, ask whether an existing tool already does it well enough that it
  should not be built here.

## 5. Improvement directions beyond the current plan

Judged strictly against the goal:

- **On-goal and cheap:** Embed chapter markers in the MP3 using video
  description timestamps or SponsorBlock segment boundaries. Audiobookshelf
  displays chapters, so this would improve listening with one additional ffmpeg
  metadata block per file.
- **On-goal and cheap:** Normalize loudness with ffmpeg `loudnorm` during the
  existing copy pass, so quiet interviews and loud intros play at a similar
  volume. Test it on a few files first: unlike the current copy, this re-encodes
  the audio.
- **On-goal and medium:** Turn the reliability history from step 2 into a
  small status page showing each source's last success and failure streak. It
  is worth doing only if the digest is not enough.
- **Off-goal, so say no for now:** transcripts and search (useful for research,
  not listening), multi-user tenancy (this is a personal tool and already has
  three accounts), more platforms beyond what yt-dlp handles incidentally, and
  a public RSS feed (Audiobookshelf already handles distribution to your
  phone). These are interesting, but none makes the library more reliable or
  less demanding to maintain.

## 6. What could go wrong

- **YouTube closes the `web_embedded` route.** The configuration already
  predicts this. The impact would be a near-total outage. Without step 3, the
  issue would appear as quiet failure notifications drifting past, or simply as
  silence if expansion itself fails. This is the top operational risk; write
  down the PO-token plugin plan before it happens.
- **Cookies expire or the account is flagged.** This is the second most likely
  outage and the one most likely to recur. Steps 2 and 4 would make it easy to
  diagnose.
- **A bad yt-dlp nightly is released.** Auto-update means the whole deployment
  adopts a regression within a day, with no recorded known-good version to
  restore. That is the reason for step 5.
- **The scheduler dies silently.** A hung container, full disk, or crashed
  thread is currently indistinguishable from a quiet week. The heartbeat is the
  only reliable defense.
- **The goal drifts toward infrastructure polishing.** Recent git history is
  centered on extension packaging, Firefox signing, documentation, the blog,
  and generated explainer pages. All of that is good work, but it serves
  publishing and presentation more than listening. A project meant to provide a
  low-attention podcast library can fail by becoming a high-attention
  downloader-maintenance hobby. An empty AGENTS.md makes that drift easier
  because nothing in the repository pushes back. Writing it is the cheapest
  correction available.
- **A second tool starts consuming the tags.** Any future feature that rewrites
  MP3 metadata, such as normalization or chapters, must preserve the `date` and
  `comment` tags and the inode-preserving copy behavior. Otherwise retention and
  Audiobookshelf tracking could break in subtle ways.

## TL;DR

The project has already reached the build phase of its inferred goal: the
pipeline, UI, API, extension, and deployment are complete, tested, and
accurately documented. The stated source of truth for that goal, AGENTS.md, is
empty, so write it first. After that, the highest-value work is not more
features but better visibility: a heartbeat digest, specific detection of the
YouTube 403/PO-token failure, cookie-age reporting, and a yt-dlp rollback path.
The main risks are YouTube countermeasures and silent failure. The main
meta-risk is polishing the downloader instead of listening to podcasts.
