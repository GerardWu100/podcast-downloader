---
title: Architecture
sidebar_position: 2
---

# Architecture

## End-to-end flow

1. The downloader reads `urls.txt`.
2. Each non-comment line is validated as an `http` or `https` media URL that `yt-dlp` can attempt.
3. YouTube direct video URLs are normalized into canonical watch URLs.
4. YouTube channel and playlist URLs are expanded into concrete videos through `yt-dlp --flat-playlist`. For channel URLs, `/videos` polls normal uploads, `/streams` polls livestream entries, and a bare channel URL is normalized to `/videos` before expansion. Playlists are capped to the configured `channel_count` instead of enumerating the whole playlist.
5. YouTube direct video URLs are age-checked too when `min_channel_video_age_hours > 0`, unless the user explicitly bypassed that gate from the CLI or web UI.
6. Channel results are filtered:
   - YouTube Shorts are skipped.
   - Videos newer than `min_channel_video_age_hours` are skipped when upload age is known, including when `yt-dlp` reports a timestamp placeholder but still provides an upload date.
7. Each selected video is downloaded as audio. SponsorBlock removal is enabled only for YouTube URLs.
8. If a direct YouTube download fails or produces no usable MP3 and a cookie file is configured, the downloader retries that same URL once with `yt-dlp --cookies`.
9. MP3 output goes directly under the configured download directory: channel and playlist sources each get their own folder, while direct individual videos go into `singles/`.
10. A download only counts as successful if an MP3 file was created or changed anywhere under the configured download directory.
11. Successful MP3 files get an embedded MP3 date tag set to the local download completion time and a comment tag containing the source URL.
12. After the cycle, YouTube channel MP3 files older than `retention_days` are deleted when embedded metadata proves both the download date and source video URL. Playlist and single-video MP3 files are not retention-deleted.
13. The downloader writes full diagnostic detail to `download.log` and concise browser-facing events to `activity.log`.
14. Successful direct-video URLs are removed from `urls.txt`.
15. Successful expanded URLs are written to `downloaded_urls.txt` so future channel scans stay idempotent.

## Why the downloader checks file changes

A plain subprocess exit code is not enough. `yt-dlp` can exit with code `0` even when no MP3 was created or updated in the target folder. The project therefore snapshots MP3 file state before and after each run.

Let:

- $B$ = the set of MP3 files before the download attempt
- $A$ = the set of MP3 files after the download attempt
- $s(p)$ = the file state of file $p$, represented by its modification time and file size

Then a file is treated as changed if either:

$$
p \notin B
$$

or

$$
s_A(p) \ne s_B(p)
$$

The download is considered successful if at least one MP3 file satisfies that condition.

The downloader also passes `--no-mtime` to `yt-dlp`. That flag is useful hygiene because it prevents source timestamps from being preserved on the output file, but Audiobookshelf's visible podcast episode date comes from embedded audio metadata. After a successful download, the downloader runs a small `ffmpeg` copy pass over each changed MP3, preserves existing streams and metadata, and overwrites the embedded `date` metadata with the local completion timestamp. The same pass writes the source URL to the embedded `comment` metadata. YouTube URLs are normalized to canonical watch URLs before writing that comment, so `https://www.youtube.com/live/VIDEO_ID` and `https://www.youtube.com/watch?v=VIDEO_ID` do not create separate metadata identities. The rewrite uses a non-`.mp3` temporary filename, then copies the rewritten bytes back into the original MP3 path without replacing that path's inode. That matters because Audiobookshelf's scanner and watcher use file paths and inode values when matching library files. Audiobookshelf maps the embedded audio date into `podcastEpisode.pubDate` / `podcastEpisode.publishedAt`.

The same embedded date is the retention clock. A retention clock is the timestamp used to decide whether a file is old enough to delete. The project intentionally uses the local download completion date, not YouTube release date and not filesystem modification time. Retention applies only to files in current YouTube channel output folders. Playlist and single-video files are kept. Files with missing or unreadable embedded date metadata, or missing source URL comment metadata, are left in place because cleanup cannot prove both that they are expired and which archive URL to remove.

When a channel MP3 is deleted, the downloader removes the same concrete video URL from `downloaded_urls.txt`. That keeps the audio file and expanded-item archive consistent: an old file removed from disk is no longer treated as already downloaded forever.

## YouTube cookie fallback

Browser cookies are authentication state, so the downloader does not spend them on the normal direct YouTube path. When a cookie file is configured, a direct YouTube download still starts with a plain `yt-dlp` attempt. The service retries once with `--cookies <file>` only if that attempt exits non-zero or returns without a changed or recoverable MP3. Non-YouTube downloads do not use this fallback.

The configured cookie file is a Netscape/Mozilla-format text file, usually `cookies.txt` in the active data directory. In Docker, the default active data directory is the mounted `/data` volume.

## Download folder layout

The configured `output_dir` is the root for finished MP3 files only. `intermediate_dir` holds scratch downloads until they are published. Neither path contains or mirrors `urls.txt`.

```text
downloads/
├── channel-one/
├── channel-two/
├── playlist-name1/
└── singles/
```

YouTube channel folder names are derived from the source URL and sanitized for the filesystem. YouTube playlist folder names prefer the playlist title reported by `yt-dlp`; if that metadata is unavailable, the downloader falls back to the `list=` identifier. Direct individual videos, including direct YouTube videos and non-YouTube videos, are written to `singles/`.

## Queue-file mutation model

Both the CLI and the web UI mutate `urls.txt`. In Docker deployments, the downloader may be removing completed video URLs at the same time the web UI is appending new URLs. To avoid lost updates, queue-file reads and writes now use an interprocess file lock.

That matters because this race is otherwise possible:

1. Downloader reads `urls.txt`.
2. Web UI appends a new URL.
3. Downloader writes an older in-memory copy of the file back to disk.
4. The newly appended URL disappears.

The lock forces those operations to run one at a time.

YouTube URL normalization also treats the `/live/VIDEO_ID` route as the same concrete video as `/watch?v=VIDEO_ID`. Completed livestreams can move between those shapes in user-submitted links and YouTube surfaces, so the queue and bypass stores collapse them to the watch URL before comparing entries.

The same locking model now applies to `downloaded_urls.txt` because the archive file is written by the downloader and read synchronously by the web UI during duplicate detection. That prevents the UI from reading stale or partial archive contents while a download completion is being recorded.

The lock and file-mutation rules are owned by `src/state/` stores:

- `QueueStore` owns `urls.txt` reads, appends, and removals.
- `ArchiveStore` owns `downloaded_urls.txt` reads, appends, claims, and long transactions.
- `BypassStore` owns one-shot age-bypass entries.
- `ActivityLogStore` owns `activity.log` appends and tail reads.

`src/url_utils.py` and `src/activity_log.py` still expose the older function names, but those functions now delegate to the stores. That keeps existing callers stable while making the state boundary explicit.

Activity-log timestamps are written in `America/Toronto` time so the browser feed matches the operator's local clock even when the container's default timezone is UTC.

Expanded channel and playlist downloads also hold the archive lock across the duplicate check, the download attempt, and the success append. That long lock is intentional. It means a second scheduler process will wait instead of downloading the same expanded video while the first process is still working. The URL is appended only after a successful download, so a failed attempt remains retryable.

## Deployment modes

### Local CLI mode

- Run `uv run python main.py`
- Reads `config.ini` from the project root.
- Writes downloads to `downloads/` by default.
- Groups MP3 files under direct child folders of `downloads/`.

### Docker scheduled mode

- `start.py` keeps the FastAPI app in the main process.
- A background thread runs the scheduler.
- The scheduler launches `python -m src.cli` from the project root at a fixed interval for the full queue.
- Direct video URLs added through the web UI use an immediate single-URL run, which does not inspect the rest of `urls.txt`.
- Channel and playlist URLs added through the web UI wait for the scheduled full-queue run.
- Runtime state lives in `PODCAST_DATA_DIR`.

## Trust boundaries

- `yt-dlp` and SponsorBlock are external dependencies.
- SponsorBlock is a YouTube-only cleanup step in this project; non-YouTube URLs are passed through `yt-dlp` without SponsorBlock flags and with `--no-playlist`.
- Queue URLs are user input and are always passed to `yt-dlp` after `--` so they cannot be interpreted as command-line flags.
- Proxy headers are only trusted when `trust_x_forwarded_for = true`.
- Browser sessions are persisted to `.ui_sessions.json` and are not bound to the authenticating IP address; the client IP is used only for login failure bans. Public entry pages redirect a browser with a valid remembered session to `/ui`.
