# Media Guide

## Part 1: URL Policy

`media/` interprets URLs without mutating application state.

- `urls.py` accepts absolute `http` and `https` URLs that `yt-dlp` may attempt.
- `youtube.py` recognizes YouTube hosts, normalizes equivalent video URLs,
  classifies channels/playlists/Shorts, resolves display and folder names,
  checks upload age, and expands channels or playlists through metadata calls.

Generic validation stays separate so a future non-YouTube provider does not
inherit YouTube-specific rules. A provider interface should be added only when
a second provider needs its own expansion or metadata policy.

Every `yt-dlp` metadata command places `--` immediately before the
user-controlled URL, preventing it from being parsed as an option.

## Part 2: Code Reference

- `urls.py`: `normalized_hostname()` and `is_supported_media_url()`.
- `youtube.py`: URL normalization/classification, metadata lookup, age policy,
  channel/playlist expansion, and YouTube cookie retry order.
- `__init__.py`: package marker.

## Part 3: Journal

- 2026-07-26: Split generic URL validation from YouTube policy and removed all
  queue/archive/bypass adapters from the media layer.
