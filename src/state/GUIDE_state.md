# State Guide

## Part 1: Plain-File State

`state/` owns every durable application state file. The project intentionally
uses plain text and JSON rather than a database because deployment uses one web
worker and one scheduler thread.

| Store | File | Important invariant |
|---|---|---|
| `QueueStore` | `urls.txt` | URLs are validated and normalized under a lock |
| `ArchiveStore` | `downloaded_urls.txt` | Check/download/append can share one exclusive transaction |
| `BypassStore` | `bypass_age_check_urls.txt` | Overrides are normalized and consumed once |
| `ActivityLogStore` | `activity.log` or `download.log` | Appends and tail reads see whole lines |
| `AuthStore` | `.ui_sessions.json`, `.login_state.json` | JSON updates are locked and atomically replaced |

`locked_text_file()` uses `fcntl`, the Unix file-locking interface. A shared
lock permits concurrent readers; an exclusive lock serializes mutation.
`AuthStore` locks a stable sibling lock file because the JSON data file itself
is replaced atomically.

## Part 2: Code Reference

- `file_locks.py`: `locked_text_file()`.
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
