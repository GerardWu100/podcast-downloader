# State Guide

## Purpose and Flow

`state/` owns the project's durable plain-file state. The project still uses simple text files instead of a database, but the locking and mutation rules now live behind explicit store classes instead of being scattered across URL and activity helpers.

The important files are:

| State file | Store | Meaning |
|---|---|---|
| `urls.txt` | `QueueStore` | User-facing queue of direct media URLs plus monitored YouTube channels and playlists |
| `downloaded_urls.txt` | `ArchiveStore` | Machine-facing archive of expanded channel and playlist videos that succeeded |
| `bypass_age_check_urls.txt` | `BypassStore` | One-shot list of direct YouTube videos allowed to skip the minimum-age gate |
| `activity.log` | `ActivityLogStore` | Concise browser-facing activity feed derived from downloader events |

All stores use advisory `fcntl` locks through one shared helper. A shared lock means multiple readers can inspect a file together. An exclusive lock means one writer owns the file while it reads current contents, decides what to change, writes the result, and truncates or appends as needed. This protects the Docker scheduler and web UI from losing each other's updates.

Activity-log timestamps use the shared `LOG_TIME_ZONE` (`America/Toronto`), matching `download.log`. Human-facing log timestamps are written at minute precision so the browser UI does not show unnecessary seconds.

The archive store has one extra rule: expanded channel and playlist downloads can hold an exclusive archive transaction across duplicate detection, the download attempt, and the success append. That long lock is intentional because it prevents two downloader processes from downloading the same expanded video at the same time. Retention cleanup can also remove channel video URLs from the archive when it deletes the corresponding old channel MP3.

## Code Reference

- `file_locks.py`: provides `locked_text_file()`, the only low-level text-file lock helper used by the state stores.
- `queue_store.py`: provides `QueueStore` for sample queue creation, valid queue reads, normalized UI reads, append, direct-video removal, and monitored URL removal.
- `archive_store.py`: provides `ArchiveStore` plus `LockedDownloadedUrlArchive` for archive reads, appends, removals, claims, and long archive transactions.
- `bypass_store.py`: provides `BypassStore` for loading, adding, and removing normalized one-shot age-bypass URLs.
- `activity_store.py`: provides `ActivityLogStore` for timestamped activity writes and locked tail reads.
- `__init__.py`: exports the store classes for direct imports.

Start with `QueueStore` and `ArchiveStore` when changing downloader behavior. Start with `ActivityLogStore` when changing the browser activity feed.

## Journal

- 2026-05-06: File-backed queue, archive, bypass, and activity-log behavior moved behind explicit stores while existing `url_utils.py` and `activity_log.py` imports remain compatibility wrappers.
- 2026-05-06: Activity-log timestamps now use `America/Toronto` explicitly so the web UI does not show UTC timestamps beside a Toronto-local browser clock.
- 2026-06-07: `activity.log` and `download.log` now share `LOG_TIME_ZONE` (`America/Toronto`) so browser and diagnostic logs stay aligned in Docker.
- 2026-06-22: Human-facing activity timestamps now omit seconds while continuing to use the shared Toronto/Eastern timezone.
- 2026-05-15: Archive removal support was added so channel retention cleanup can delete an old MP3 and remove its concrete video URL from `downloaded_urls.txt` in the same cycle.
