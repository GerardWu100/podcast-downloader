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
| `ActivityLogStore` | `activity.log` or `download.log` | Appends and tail reads see whole lines; tails read only the final 256 KB |
| `AuthStore` | `.ui_sessions.json`, `.login_state.json` | JSON updates are locked and atomically replaced |

`locked_text_file()` uses `fcntl`, the Unix file-locking interface. A shared
lock permits concurrent readers; an exclusive lock serializes mutation.
`AuthStore` locks a stable sibling lock file because the JSON data file itself
is replaced atomically.

Every line-per-entry store goes through `locked_line_file()`, which yields a
`LockedLineFile`. That class owns the two rules those files share: read entries
as stripped non-blank lines (optionally skipping `#` comments), and append only
through `append_line()`, which writes a separator first when the file does not
already end in a newline. Keeping the rule in one place is what makes it hold
for every append path rather than for whichever ones a caller remembered.
`AuthStore` deliberately stays on `locked_text_file()` because JSON documents
and zero-content lock files are not line-per-entry.

## Part 2: Code Reference

- `file_locks.py`: `locked_text_file()`, `LockedLineFile`, `locked_line_file()`.
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
- 2026-08-03: Fixed a data-corruption bug in the append paths of `QueueStore`,
  `BypassStore`, and `ArchiveStore`. A hand-edited file whose last line lacked a
  trailing newline had the next appended URL spliced onto that line, losing both
  entries. Each append now repairs the missing separator first
  (`tests/test_append_newline_safety.py`).
- 2026-08-08: Moved that separator repair out of the three stores and into the
  shared `LockedLineFile`. The per-store version had missed
  `ActivityLogStore.write_event`, which was still merging events onto a
  hand-edited final line; it is now covered too. `BypassStore.add` also stopped
  treating commented-out URLs as duplicates, matching `BypassStore.load`.
- 2026-08-10: `read_tail` stopped loading the whole file. It now reads only the
  final 256 KB through `os.pread` and drops the partial first line, because the
  browser polls `download.log` every 15 seconds and that file can reach several
  megabytes between rotations.
