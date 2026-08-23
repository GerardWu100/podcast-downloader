# Media Guide

## Part 1: URL Policy

`media/` interprets URLs without changing saved application state.

- `urls.py` accepts absolute `http` and `https` URLs that `yt-dlp` can try and identifies exact Rumble hosts for download policy.
- `youtube.py` recognizes YouTube hosts, makes equivalent video URLs match,
  identifies channels, playlists, and Shorts, resolves display and folder names,
  checks upload age, and finds videos in channels or playlists.

Generic validation stays separate so another provider would not inherit
YouTube-only rules. Add a provider interface only when a second provider needs
its own expansion or metadata rules.

Every `yt-dlp` metadata command places `--` immediately before the
user-controlled URL, preventing it from being parsed as an option.
YouTube metadata operations derive one ordered cookie-attempt sequence: plain
then authenticated in fallback mode, or authenticated then plain in always-use
mode. An empty result, placeholder-only metadata, or a timed-out attempt is not
usable and therefore advances to the alternate cookie mode.

Channel and playlist classification examines parsed path and query fields.
Channel-looking text inside an unrelated query value cannot change a direct
video into a monitored source.

## Part 2: Code Reference

- `urls.py`: `normalized_hostname()`, `is_supported_media_url()`, and `is_rumble_url()`.
- `youtube.py`: URL normalization/classification, metadata lookup, age policy,
  channel/playlist expansion, and YouTube cookie retry order.
- `__init__.py`: package marker.

## Part 3: Journal

- 2026-07-26: Split generic URL validation from YouTube policy and removed all
  queue/archive/bypass adapters from the media layer.
- 2026-08-10: Parsed-path source classification replaced whole-URL substring
  matching, and unusable metadata attempts began using cookie fallback.
- 2026-08-23: Exact Rumble hostname classification enabled provider-specific browser impersonation without applying it to unrelated sites.
