# Source Guide

## Purpose and Problem Statement

[`src/`](/Users/gwh/projects/one-time-projects/podcast-downloader/src) contains the actual application code for the downloader and the browser UI. The folder exists to keep the queue-processing logic, URL handling, configuration loading, and web endpoints separated by responsibility instead of collapsing everything into one script.

The folder solves four distinct problems:

1. Turn a mixed queue of media URLs into concrete video URLs.
2. Download those videos as MP3 files, using SponsorBlock removal only for YouTube.
3. Keep repeat channel polling idempotent.
4. Provide a minimal authenticated UI for adding new queue items remotely, pruning monitored URLs, and replacing the YouTube cookie file from the browser.

## The Spine of the Logic

### CLI path

1. [`cli.py`](/Users/gwh/projects/one-time-projects/podcast-downloader/src/cli.py) loads the project config and resolves CLI overrides.
2. The CLI either appends URLs to the queue and exits, or instantiates the downloader.
3. When the CLI is used with `--skip-age-check`, each added direct YouTube video URL is also written to a dedicated bypass file so the next downloader run can ignore the YouTube minimum-age gate for that URL.
4. The internal `--download-single-url` path considers exactly one queued direct media URL. Direct YouTube URLs still honor the configured age gate unless that URL appears in the one-shot bypass file.
5. [`downloads/service.py`](/Users/gwh/projects/one-time-projects/podcast-downloader/src/downloads/service.py) reads the queue file, expands channels and playlists, and runs the download loop.
6. [`downloader.py`](/Users/gwh/projects/one-time-projects/podcast-downloader/src/downloader.py) stays as a compatibility adapter for older imports and tests.
7. [`url_utils.py`](/Users/gwh/projects/one-time-projects/podcast-downloader/src/url_utils.py) classifies each URL:
   - direct media URL
   - YouTube Shorts URL
   - channel
   - playlist
8. YouTube channel and playlist URLs are expanded into direct video URLs using `yt-dlp --flat-playlist`. For channel URLs, `/videos` means normal uploads, `/streams` means livestream entries, and a bare channel URL is expanded as `/videos` so the downloader does not pull other channel tabs. Playlist expansion is capped to `channel_count`, matching the channel polling depth instead of enumerating the whole playlist.
9. Direct YouTube video URLs go through the same minimum-age gate as channel items when the uploader timestamp or upload date is known, unless that URL appears in the bypass file. When only a calendar upload date is available, or when `yt-dlp` reports the timestamp as `NA`, the downloader waits conservatively until the configured hour threshold has elapsed after that date.
10. Non-YouTube URLs are treated as single direct media URLs, are downloaded with `--no-playlist`, and skip SponsorBlock flags.
11. The downloader assigns each concrete URL an output folder derived from the source queue entry. Channel and playlist sources write to direct child folders under the configured download directory; playlist folders prefer the playlist title from `yt-dlp` and fall back to the `list=` identifier. Direct individual videos write to `singles/`.
12. The downloader loops through those concrete URLs, launches `yt-dlp`, and tracks success by comparing recursive MP3 file state before and after the subprocess run.
13. On success:
   - the queue file is cleaned up for single-video URLs
   - expanded channel and playlist URLs are checked against the archive under an exclusive archive lock and written back after success
   - any matching one-shot bypass entry is removed
   - changed MP3 files get embedded date metadata stamped with the local download completion time and comment metadata stamped with the source URL
   - if `yt-dlp` reports success without changing an MP3, the downloader looks for the expected output file and stamps it if it already exists
   - the event is written to the full diagnostic log and the concise browser activity log
14. On scheduled full-queue runs, retention cleanup deletes only YouTube channel MP3 files older than `retention_days` before archive-backed candidates are checked, then removes the deleted file's concrete video URL from `downloaded_urls.txt` so that URL can be downloaded again in the same cycle.

### Web path

1. [`api.py`](/Users/gwh/projects/one-time-projects/podcast-downloader/src/api.py) loads the same config as the CLI.
2. In Docker deployments, that config is read from the mounted data directory, which is seeded from the repo default `config.ini` on first boot.
3. The Docker scheduler reads `DOWNLOAD_INTERVAL_HOURS` during module import and now aborts startup immediately if the value is not a positive integer.
4. Login checks `.ui_password`, which now stores a PBKDF2 hash in Docker deployments. Docker first copies an image-bundled repo `.ui_password` into the mounted data directory when one exists, then the API rejects blank or legacy placeholder values, rate-limits repeated failures by client IP, and creates a persistent session.
5. Public entry pages check for that remembered session before rendering the login form, so reopening `/` or `/login` goes straight to `/ui` when the session is still valid.
6. Authenticated users see the current monitored URLs loaded from `urls.txt` under a shared file lock.
7. Each listed URL is rendered with a CSRF-protected remove form so the operator can stop monitoring it from the browser without opening the file manually.
8. Authenticated users can also submit a new URL through a simple HTML form.
9. Authenticated users can upload a replacement YouTube cookie file. The endpoint requires the same session and CSRF token as queue edits, validates the Netscape header, normalizes line endings to LF, overwrites the configured cookie path, and sets permission mode `600`.
10. The submitted URL is normalized and appended to the queue file through the shared URL utility layer.
11. The UI offers a `Download now` checkbox. For direct YouTube videos it writes a one-shot age-gate bypass into the same file used by the CLI. For playlist URLs it queues an immediate full-playlist download instead of waiting for the scheduled `channel_count`-limited run.
12. Direct-video submissions enqueue a single-URL scheduler payload, so Docker considers only that submitted video immediately without processing unrelated queue entries.
13. Checked playlist submissions enqueue a full-playlist scheduler payload, so Docker expands and downloads every playlist entry immediately.
14. Unchecked channel and playlist submissions stay queued for the normal scheduled full-queue run.
14. If a UI submission arrives during the Docker startup post-update delay, the scheduler handles that UI trigger before the startup full-queue run.
15. Queue, archive, bypass, and activity-log reads and writes go through [`state/`](/Users/gwh/projects/one-time-projects/podcast-downloader/src/state) stores so each file-backed state rule has one owner.
16. Archive-file reads and writes now use the same locking model because the UI checks `downloaded_urls.txt` before accepting a URL.

## Inputs and Outputs

| Input | Source | Output | Destination |
|---|---|---|---|
| Queue URLs | `urls.txt` | Concrete media URLs | in-memory download loop |
| Channel metadata | `yt-dlp --flat-playlist` | filtered video URLs | in-memory download loop |
| Download subprocess result | `yt-dlp` | MP3 files | source folders under `downloads/` |
| Login attempts | browser UI | lockout state | `.login_state.json` |
| Login sessions | browser UI | remembered session state | `.ui_sessions.json` |
| UI submissions | browser form | normalized queue entries | `urls.txt` |
| UI removals | browser form | deleted monitored queue entries | `urls.txt` |
| Cookie uploads | browser form | Netscape cookie file with LF endings and mode `600` | configured `cookies_file` |
| CLI/UI age-bypass requests | shell flag or browser checkbox | one-shot bypass entries | `bypass_age_check_urls.txt` |
| Direct-video UI submissions | browser form | single-URL scheduler payloads | in-memory trigger queue |
| Checked playlist UI submissions | browser form | full-playlist scheduler payloads | in-memory trigger queue |
| Download outcomes | downloader | concise browser activity feed | `activity.log` |

## Key Design Decisions

### Why shell out to `yt-dlp`

The project uses the `yt-dlp` CLI through subprocess calls instead of building directly on the library APIs inside the main downloader flow. That keeps the runtime behavior close to the command-line tool the user already trusts and makes debugging operational flags easier.

### Why age-filter channel uploads

SponsorBlock coverage can lag shortly after a video is published. The minimum-age filter for channel polling reduces the chance of grabbing a new upload before sponsor segments have been added upstream.

The same reasoning applies to direct YouTube video URLs. If the user pastes a newly published YouTube single-video link, the default behavior is to wait until the configured age threshold has passed. The bypass file exists so this policy can be overridden intentionally for a specific URL instead of disabled globally. Non-YouTube direct URLs skip this policy because SponsorBlock does not apply to them.

For the web UI, the immediate path is intentionally narrow. Every direct-video submission queues that exact normalized URL for a single immediate scheduler run. The checkbox adds a one-shot YouTube age-gate bypass for direct videos, and for playlist URLs it queues an immediate full-playlist run that downloads every entry instead of the configured `channel_count` cap. Channel URLs ignore the checkbox and always wait for the scheduled run. Unchecked channel and playlist submissions do not wake an immediate run, because an immediate UI click should not accidentally expand old monitored channels or other queued lists.

Direct-video success removes the URL from `urls.txt` but does not write it to `downloaded_urls.txt`. The archive is reserved for expanded channel and playlist entries, where future scheduled scans need a memory of concrete videos that have already been handled. For expanded entries, the downloader holds the archive lock across duplicate detection, the download attempt, and the success append. That serializes competing downloader processes for the same archive file and avoids duplicate work without marking failed attempts as completed.

YouTube live URLs use the same normalized identity as ordinary watch URLs. For example, `https://www.youtube.com/live/VIDEO_ID` becomes `https://www.youtube.com/watch?v=VIDEO_ID`. This keeps completed livestreams from lingering in `urls.txt` or being accepted as separate queue entries just because YouTube exposed the same video through the live route.

YouTube channel tab URLs choose the source mode before expansion. `https://www.youtube.com/@PBDPodcast/videos` monitors ordinary uploads only. `https://www.youtube.com/@PBDPodcast/streams` monitors livestream entries only. `https://www.youtube.com/@PBDPodcast/` is treated like the `/videos` tab.

### Why success is based on file changes

A plain exit code is not enough, and counting MP3 files is also wrong. A successful run can overwrite an existing filename without increasing the number of MP3s. The downloader therefore snapshots MP3 modification times and file sizes before and after each subprocess call and treats any created or changed MP3 as a real success. The snapshot is recursive because downloads now live in source folders under the configured download directory.

The downloader tells `yt-dlp` not to preserve source modification times. That is useful hygiene, but the Audiobookshelf-visible date comes from embedded audio metadata. The downloader uses a small `ffmpeg` copy pass to overwrite the MP3 `date` metadata with the local completion time, because Audiobookshelf maps that embedded audio date into `podcastEpisode.pubDate` / `podcastEpisode.publishedAt`. That pass also writes the source URL to the MP3 `comment` metadata. YouTube URLs are normalized before this point, so live links and watch links for the same video share one canonical watch URL in the metadata. The copy pass writes to a non-`.mp3` temporary file, then copies the rewritten bytes into the existing MP3 path without replacing the inode. This keeps both extension-based and inode-based library scanners from seeing a duplicate audio item.

That embedded date is also the retention timestamp. The cleanup pass applies only to current YouTube channel output folders. On scheduled full-queue runs it runs before archive-backed download checks, so an expired channel file is removed from disk and from `downloaded_urls.txt` before the downloader decides whether the concrete source URL has already been handled. It leaves playlists, singles, files with missing date metadata, and files with missing source URL metadata untouched.

### Why `X-Forwarded-For` is opt-in

Trusting forwarded headers only makes sense behind a reverse proxy you control. On a directly exposed app, that header is user-controlled input and would let an attacker rotate apparent source IPs to sidestep the login ban logic.

### Why the UI now uses a concise activity feed

The full `download.log` keeps diagnostic detail for debugging. The browser UI defaults to `activity.log`, which contains concise user-facing events such as skipped Shorts, age-gate waits, completed downloads, failures, and run summaries. Operators can switch the log viewer to `download.log` when they need the full runtime tail. The activity log lives beside `download.log` and is derived from that path rather than being a separate config setting.

### Why the UI now uses a CSP nonce

The queue page includes an activity viewer implemented with browser-side JavaScript. A strict Content Security Policy is still desirable, but `default-src 'none'` blocks inline scripts and event-handler attributes unless the page explicitly authorizes them. The UI therefore generates a per-response nonce, attaches it to the `<script>` tag, removes inline `onclick` handlers, and allows same-origin `fetch()` calls for `/logs`.

## Assumptions and Edge Cases

- Invalid lines in the queue file are skipped with a warning instead of aborting the run.
- Missing parent directories for the queue file are created automatically when the sample file is generated or URLs are appended.
- Unknown upload age is allowed for channel items rather than dropped, but `yt-dlp` placeholder values such as `NA` are treated as missing so usable fallback fields can still be checked.
- Unknown upload age is also allowed for direct YouTube video URLs rather than blocking the download forever.
- YouTube Shorts are skipped before download.
- Direct Shorts URLs are removed from the queue when skipped so they do not get retried forever.
- Missing `yt-dlp` on `PATH` aborts the CLI run early.
- Docker auto-update of `yt-dlp` is best-effort rather than mandatory, so transient package-index failures do not block startup.
- UI-triggered runs interrupt the Docker post-update delay, so a direct-video submission during startup does not wait for or fall into the full scheduled queue pass.
- Docker startup refuses invalid `DOWNLOAD_INTERVAL_HOURS` values rather than silently coercing them, because `0` or negative values would break the scheduler semantics.
- Runtime config rejects out-of-range numeric settings and blank paths before the CLI or API starts. `channel_count` and `retention_days` must be at least `1`; `min_channel_video_age_hours` and `delay_seconds` must be at least `0`.
- API sessions are persisted to `.ui_sessions.json`, so they survive FastAPI restarts until they expire.
- Session access is no longer IP-bound; only the login failure ban logic uses the client IP.
- Reopening `/` or `/login` with a valid remembered session redirects to `/ui` instead of rendering a new password form.
- Anonymous login CSRF tokens now expire so repeated visits to `/login` do not grow unbounded in memory.
- Login failures now redirect back to `/login` with a short message code that the HTML page renders as an inline error banner, instead of returning a JSON error body directly to the browser.

## Key Configuration Parameters

| Key | Default | Effect |
|---|---|---|
| `channel_count` | `2` in code and checked-in config | Number of recent channel or playlist videos to target; must be at least `1` |
| `min_channel_video_age_hours` | `24` | Rejects fresh direct-video and channel uploads when age is known; must be at least `0` |
| `bypass_age_check_file` | `bypass_age_check_urls.txt` | Stores one-shot age-gate bypasses requested from the CLI or UI |
| `delay_seconds` | `2.0` in code, user-overridable in config | Sleep between downloads; must be at least `0` |
| `retention_days` | `30` | Number of days to keep YouTube channel MP3 files based on embedded download-date metadata; must be at least `1` |
| `cookies_file` | auto-detected `cookies.txt` when present | Optional YouTube cookie file; UI upload can create or overwrite this path |
| `trust_x_forwarded_for` | `false` in code fallback, `true` in the checked-in `config.ini` | Proxy-forwarded client IP behavior |

## Folder Tree

```text
src/
├── GUIDE_src.md
├── __init__.py
├── activity_log.py
├── api.py
├── cli.py
├── config.py
├── downloader.py
├── downloads/
├── state/
├── trigger.py
└── url_utils.py
```

- `__init__.py`: package marker.
- `activity_log.py`: path, write, and tail-read helpers for the concise browser activity feed.
- `api.py`: FastAPI app for login, queue submission, monitored-URL display, queue removal, dark-mode UI, and activity viewing.
- `cli.py`: command-line entrypoint, queue mutation, age-bypass flag handling, and single-URL immediate download dispatch.
- `config.py`: typed config loading from `config.ini` with explicit validation errors for malformed numeric values.
- `downloader.py`: compatibility adapter that still exports the public downloader class and a few helper names for older callers.
- `downloads/`: download execution service, yt-dlp subprocess client, MP3 metadata writer, source-folder routing, and retention cleanup.
- `state/`: locked file-backed stores for queue, archive, bypass, and activity-log state.
- `trigger.py`: in-memory scheduler wake-up state for full-queue and single-URL UI-triggered runs.
- `url_utils.py`: URL parsing, normalization, expansion, and compatibility wrappers around the state stores.

## Code Reference

### `api.py`

- Responsibility: UI login flow, session checks, dark-mode rendering, monitored-URL rendering, queue submission, queue removal, and activity display.
- Key objects: `app`, `_client_ip()`, `_require_login()`, `_has_valid_session()`, `_store_login_csrf_token()`, `_security_headers()`, `root()`, `login_form()`, `login_action()`, `add_url_form()`, `remove_url_form()`, `ui()`.
- Project relation: browser-facing layer only; no download orchestration.

### `cli.py`

- Responsibility: parse CLI flags and decide whether to append URLs, mark one-shot bypasses, run all downloads, or run one direct media URL immediately.
- Key objects: `build_parser()`, `main()`.
- Project relation: thin orchestrator above config + downloader.

### Root startup path

- [`start.py`](/Users/gwh/projects/one-time-projects/podcast-downloader/start.py) remains outside `src/`, but it is part of this folder's runtime story because it launches `src.api:app` and the downloader loop together in Docker.
- Key objects: `_parse_interval_hours()`, `_wait_for_post_update_delay_or_ui_trigger()`, `_run_immediate_downloads()`, `run_scheduler()`, `start_web()`.
- Project relation: validates Docker scheduler configuration before either the web server or the background download loop starts.

### `config.py`

- Responsibility: parse `config.ini` into a frozen dataclass with resolved paths.
- Key objects: `PodcastConfig`, `load_config()`.
- Project relation: shared by both CLI and API, so config behavior stays consistent.

### `activity_log.py`

- Responsibility: derive `activity.log` beside `download.log` and keep compatibility wrappers for concise activity writes and reads.
- Key objects: `activity_log_file_for()`, `write_activity_event()`, `read_activity_log_tail()`, `read_download_log_tail()`.
- Project relation: shared by the downloader and API; persistence is owned by `state/activity_store.py`.

### `downloader.py`

- Responsibility: compatibility wrapper around the new download service.
- Key objects: `PodcastDownloader`, `get_video_metadata`, `is_old_enough`, `remove_video_url_from_file`, `remove_from_bypass_age_file`.
- Project relation: keeps older imports and tests working while `src/downloads/` owns the real execution flow.

### `downloads/`

- Responsibility: yt-dlp execution, source-folder routing, recursive MP3 state comparison, metadata stamping, completed scratch-folder cleanup, channel-only retention cleanup, archive cleanup for deleted channel files, and recoverable partial-success handling.
- Key objects: `AudioSnapshot`, `AudioMetadataWriter`, `PodcastDownloadService`.
- Project relation: new core execution package used by the downloader adapter.

### `state/`

- Responsibility: own file-backed state and advisory locking for `urls.txt`, `downloaded_urls.txt`, `bypass_age_check_urls.txt`, and `activity.log`.
- Key objects: `QueueStore`, `ArchiveStore`, `LockedDownloadedUrlArchive`, `BypassStore`, `ActivityLogStore`, `locked_text_file()`.
- Project relation: central persistence layer used by the downloader, API, CLI wrappers, and activity-log wrappers.

### `trigger.py`

- Responsibility: share immediate-run wake-up state between the FastAPI UI thread and the Docker scheduler thread.
- Key objects: `download_trigger`, `queue_single_url_download()`, `queue_batch_download()`, `pop_single_url_download_requests()`, `pop_batch_download_request()`.
- Project relation: keeps scheduler dispatch explicit when UI submissions arrive.

### `url_utils.py`

- Responsibility: validate URLs, normalize duplicates, expand channels/playlists, and expose compatibility wrappers for existing queue/archive/bypass callers.
- Key objects: `locked_downloaded_url_archive()`, `is_supported_media_url()`, `normalize_youtube_url()`, `expand_channel_or_playlist()`, `append_urls()`, `load_queue_urls()`, `remove_url_from_queue()`, `load_downloaded_url_archive()`, `append_to_downloaded_url_archive()`, `remove_from_downloaded_url_archive()`, `remove_video_url_from_file()`.
- Project relation: shared URL policy used by both the downloader and API; durable file mutation is delegated to `src/state/`.

## Common Workflows

- Queue a URL from the shell: `uv run python main.py --add-url "https://www.youtube.com/watch?v=..."`
- Queue a URL from the shell and bypass the age gate once: `uv run python main.py --add-url "https://www.youtube.com/watch?v=..." --skip-age-check`
- Run exactly one queued direct media URL through the single-item path: `uv run python main.py --download-single-url "https://videos.example.com/watch/episode-1"`
- Run the package CLI directly: `uv run python -m src.cli --help`
- Run the full downloader: `uv run python main.py`
- Start the API: `uv run uvicorn src.api:app --host 127.0.0.1 --port 8000`

## Journal

- 2026-06-17: The UI checkbox now queues immediate full-playlist downloads when a playlist URL is submitted, and the label was shortened to `Download now (skip age wait or full playlist)`.
- 2026-05-16: YouTube channel expansion now respects `/videos` versus `/streams`, and bare channel URLs default to `/videos`.
- 2026-04-30: Direct one-off video downloads now remove queue entries without adding them to the expanded-item archive, and bypass-file writes are limited to YouTube age-gate overrides.
- 2026-04-30: MP3 outputs now write local completion time into embedded date metadata so Audiobookshelf shows the download date.
- 2026-04-30: Web UI direct-video additions now use a single-URL immediate run whether or not the age-bypass checkbox is checked; channel and playlist additions wait for the scheduled full-queue run.
- 2026-04-28: Non-YouTube `http` and `https` URLs are supported as single direct media downloads; only YouTube uses channel/playlist expansion, age gating, and SponsorBlock removal.
- 2026-06-02: Playlist expansion now uses `channel_count` as the latest-entry cap, and playlist output folders prefer readable `yt-dlp` playlist titles over opaque `list=` identifiers.
- 2026-06-07: The authenticated web UI can now overwrite the configured YouTube cookie file after validating the Netscape header, normalizing line endings to LF, and setting mode `600`.
- 2026-05-03: Direct Shorts skips now clean up their queue entry, date-only age checks wait until the configured hour threshold has elapsed after the upload date, `yt-dlp` `NA` timestamps fall back to upload dates, and `is_youtube_short_url()` makes the YouTube-only `/shorts/` rule explicit.
- 2026-05-03: Metadata rewrites no longer create temporary `.mp3` files or replace final MP3 inodes, avoiding Audiobookshelf duplicate indexing during scans.
- 2026-05-15: Completed livestream URLs in the `/live/VIDEO_ID` shape now normalize to ordinary watch URLs so direct queue cleanup treats them as the same video.
- 2026-05-04: The web UI now reads concise `activity.log` events instead of tailing the full diagnostic `download.log`.
- 2026-05-05: The execution split into `src/downloads/` was restored after the refactor so the compatibility adapter could keep the public downloader surface intact.
- 2026-05-05: Expanded-item downloads now serialize on the archive lock, config validation rejects bad ranges and blank paths, and `src.cli` can run as a package module for scheduler subprocesses.
- 2026-05-06: Queue, archive, bypass, and activity-log persistence moved behind `src/state/` stores while compatibility wrappers kept existing imports working.
- 2026-05-15: Downloaded MP3 files now route into direct source folders under the output directory, with direct individual videos in `singles/`, and retention cleanup deletes only old YouTube channel files while removing their concrete URLs from the archive.
- 2026-06-22: Scheduled full-queue retention cleanup now runs before archive-backed download checks so expired channel audio can be replaced without waiting another scheduler interval.
