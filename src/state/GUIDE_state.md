# State Guide

## Part 1: Plain-file state

`state/` owns every saved application state file. The project uses plain text and JSON instead of a database because it runs one web worker and one scheduler thread.

| Store | File | Rule that must always hold |
|---|---|---|
| `QueueStore` | `urls.txt` | URLs are validated and normalized under a lock |
| `ArchiveStore` | `downloaded_urls.txt` | Short archive locks stay separate from the long download-claim lock |
| `BypassStore` | `bypass_age_check_urls.txt` | Overrides are normalized and atomically consumed once |
| `ActivityLogStore` | `activity.log` or `download.log` | Appends and tail reads see whole lines; tails read only the final 256 KB |
| `NotificationStore` | `notifications.json` | Replaced atomically and kept owner-only; a missing or damaged file reads as defaults |
| `AuthStore` | `.ui_sessions.json`, `.login_state.json` | JSON updates are locked, atomically replaced, and mode `600` |

`locked_text_file()` uses `fcntl`, the Unix file-locking interface. A shared lock lets readers run together; an exclusive lock makes changes one at a time. `AuthStore` locks a stable sibling lock file because the JSON data file itself is replaced atomically.

Every one-entry-per-line store uses `locked_line_file()`, which yields a `LockedLineFile`. It provides two shared rules: read stripped, non-blank lines (optionally skipping `#` comments), and append through `append_line()`. `append_line()` adds a missing newline when a hand-edited file does not end with one. `AuthStore` stays on `locked_text_file()` because JSON documents and empty lock files are not line-per-entry. Buffered writes are flushed before the lock is released. Initial queue creation takes the same exclusive lock as appends, so it cannot overwrite a URL added at the same time.

## Part 2: Code Reference

- `file_locks.py`: `locked_text_file()`, `LockedLineFile`, and `locked_line_file()`.
- `queue_store.py`: queue creation, reads, normalized append, and removal.
- `archive_store.py`: archive reads, append/remove, and long transactions.
- `bypass_store.py`: one-shot age-bypass state.
- `activity_store.py`: activity path derivation, timestamped writes, locked tail
  reads, and diagnostic-log empty messages.
- `auth_store.py`: remembered sessions, login failures, expiry filtering,
  interprocess transactions, and atomic JSON replacement.

## Part 3: Journal

- 2026-07-26: Authentication persistence joined the state layer; obsolete
  state-function adapters, aliases, and dead mutation paths were removed after
  callers adopted stores directly.
- 2026-08-03: Fixed a data-corruption bug in the append paths of `QueueStore`, `BypassStore`, and `ArchiveStore`. A hand-edited file whose last line lacked a trailing newline had the next URL spliced onto that line, losing both entries. Each append now repairs the missing separator first (`tests/test_append_newline_safety.py`).
- 2026-08-08: Moved separator repair from the three stores into shared `LockedLineFile`. The per-store version had missed `ActivityLogStore.write_event`, which could still merge events onto a hand-edited final line. `BypassStore.add` also stopped treating commented-out URLs as duplicates, matching `BypassStore.load`.
- 2026-08-10: `read_tail` stopped loading the whole file. It now reads only the final 256 KB through `os.pread` and drops the partial first line. The browser polls `download.log` every 15 seconds, and the file can reach several megabytes between rotations.
- 2026-08-10: Authentication JSON became owner-only, first-time queue creation
  joined queue locking, and buffered state writes began flushing before unlock.
