# Downloads Guide

## Purpose and Flow

`downloads/` owns the runtime work of turning concrete media URLs into MP3 files. It is not the output folder; it is the source-code package that builds `yt-dlp` commands, detects created or changed audio, stamps MP3 date and source URL metadata, routes files into source folders, and performs retention cleanup.

The downloader receives mixed queue entries from `urls.txt`. Channel and playlist entries are expanded before they reach this package. Each concrete video is paired with an output folder:

| Source type | Output folder |
|---|---|
| YouTube channel | direct child folder derived from the channel URL |
| YouTube playlist | direct child folder named from the playlist title, with the playlist ID as fallback |
| Direct individual video | `singles/` |

For YouTube channel sources, the URL tab decides which feed was expanded before the service receives concrete videos. `/videos` means normal uploads, `/streams` means livestream entries, and a bare channel URL defaults to `/videos`.

For YouTube playlist sources, expansion uses the same configured `channel_count` depth as channels. The downloader asks `yt-dlp` for only that many playlist entries and then slices the result defensively in memory, so a large playlist does not get fully downloaded by default.

The configured download directory contains only finished MP3 library files. `yt-dlp`, partial downloads, thumbnails, and metadata temp files stay in `intermediate_dir` until a download succeeds and the MP3 is published into the matching source folder under `output_dir`. When `intermediate_dir` is separate from `output_dir`, the completed scratch work folder is removed after publish so intermediate files do not accumulate. Failed attempts also remove scratch files; the only exception is a retryable metadata-stamp failure, where the existing MP3 is kept and non-MP3 artifacts are deleted. `yt-dlp` temp files are written inside the per-source work folder, and any legacy temp files left at the intermediate root are swept after each attempt. Queue and state files such as `urls.txt`, `downloaded_urls.txt`, and `bypass_age_check_urls.txt` stay in the data directory.

Success detection is based on recursive MP3 state in the intermediate tree. The service snapshots every `*.mp3` file under `intermediate_dir` before and after `yt-dlp` runs. A download succeeds only when at least one MP3 is created or changed, then the metadata writer stores the local download completion time in the embedded MP3 `date` tag and the source URL in the embedded MP3 `comment` tag. YouTube source URLs are already normalized at this point, so live URLs and watch URLs for the same video share the same canonical watch URL in metadata.

Configured YouTube cookies follow `always_use_cookies` in `config.ini`. When true (default), every YouTube `yt-dlp` call passes the configured Netscape-format cookie file on the first attempt and retries once without cookies on failure. When false, the order is inverted: plain first, cookies on retry. Non-YouTube downloads never use cookies.

Retention cleanup uses that same embedded download date, but only for current YouTube channel output folders. Playlist and single-video files are not eligible. A channel file older than `retention_days` is deleted only when the source URL comment tag is present too, because cleanup must remove the same concrete URL from `downloaded_urls.txt`. Files with missing or unreadable date or source URL metadata are logged and kept.

## Code Reference

- `service.py`: provides `PodcastDownloadService`, the main orchestration object for queue expansion, source-folder routing, `yt-dlp` execution, archive updates, MP3 metadata stamping, activity logging, channel-only retention cleanup, and archive cleanup for deleted channel files.
- `audio_metadata.py`: provides `AudioMetadataWriter`, the `ffmpeg` metadata rewrite helper that preserves the final MP3 inode while writing project-managed date and source URL tags.
- `ytdlp_client.py`: provides `AudioSnapshot`, the small value object used to compare MP3 state around a subprocess run.
- `__init__.py`: package marker.

Start in `service.py` when changing downloader behavior. Start in `audio_metadata.py` only when changing how MP3 date metadata is written.

## Journal

- 2026-05-19: Added configurable `intermediate_dir` / `PODCAST_INTERMEDIATE_DIR` so scratch downloads stay separate from the finished MP3 library folder.
- 2026-05-21: Docker Compose now maps `$HOME/downloads/temporary` to `/temporary` and sets `PODCAST_INTERMEDIATE_DIR` there.
- 2026-05-21: Successful downloads now remove their completed scratch work folder when `intermediate_dir` is separate from `output_dir`.
- 2026-05-21: Failed download attempts now remove scratch files too, except when one MP3 must be kept for a metadata-stamp retry; `yt-dlp` temp files now live inside each work folder and legacy root temp files are swept after every attempt.
- 2026-05-16: Channel source URLs now support upload-only `/videos` and livestream-only `/streams` modes, with bare channel URLs defaulting to `/videos`.
- 2026-05-15: MP3 output routing moved from one flat folder to direct source folders, and retention cleanup began deleting only old YouTube channel files while removing their URLs from the archive.
- 2026-05-15: YouTube cookie files are now a direct-download fallback retry instead of being used on the first `yt-dlp` attempt.
- 2026-06-07: Added `always_use_cookies` so YouTube cookie usage can stay fallback-only or switch to always-on across downloads, expansion, and metadata.
- 2026-05-31: `AudioMetadataWriter` now decodes ffmpeg stderr with `errors="replace"` so metadata stamping survives MP3s whose existing ID3 tags contain non-UTF-8 bytes.
- 2026-05-31: Opaque YouTube channel IDs in source URLs now resolve to readable folder names, yt-dlp filenames prefer `%(channel,uploader)s`, and the metadata pass writes resolved channel names into MP3 artist/album tags.
- 2026-06-02: Playlist sources now fetch only `channel_count` entries and prefer readable playlist titles for output folder names.
