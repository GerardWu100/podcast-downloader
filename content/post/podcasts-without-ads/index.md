---
title: "A Small System for Cleaner Podcast Listening"
description: "A queue-driven YouTube audio pipeline that expands channels and playlists, removes sponsor segments with SponsorBlock, and produces MP3 files for Audiobookshelf."
date: 2025-10-12
image: ""
categories: ["Computer Science", "Random Stuff", "self-hosting"]
---

I built this because "download one episode" is easy, but "keep a personal podcast feed clean and unattended" is not.

This project watches YouTube podcast sources, expands channels and playlists into concrete episodes, downloads audio as MP3, removes sponsor segments when SponsorBlock has them, and leaves the result in a plain folder that Audiobookshelf can serve. In practice, it turns a messy stream of links into a repeatable listening pipeline.

What I like about it is that it is more than a wrapper around `yt-dlp`. It behaves like a small system:

- a browser UI can add or remove monitored sources without touching files by hand
- URL normalization keeps duplicate video links from entering the queue in different shapes
- channel and playlist polling stay idempotent through a separate download archive
- fresh uploads can be delayed so SponsorBlock data has time to catch up
- queue and archive files use file locks so the UI and scheduled downloader do not overwrite each other

The operational flow is simple:

```text
YouTube URL -> queue -> URL expansion -> SponsorBlock-aware download -> MP3 folder -> Audiobookshelf
```

One implementation detail captures the spirit of the project. A subprocess exit code is not treated as success by itself. The downloader snapshots the output folder before and after each `yt-dlp` run and only advances the queue if a real MP3 file was created or updated:

```python
audio_before = self._snapshot_downloaded_audio()
result = subprocess.run(
    cmd,
    capture_output=True,
    text=True,
    timeout=600,
    check=False,
)
audio_after = self._snapshot_downloaded_audio()
changed = self._detect_changed_audio_files(audio_before, audio_after)

if result.returncode == 0 and changed:
    self._save_downloaded_url(normalized_url)
    remove_video_url_from_file(self.urls_file, url, self.logger)
```

That is the difference between a script that usually works and a pipeline you can leave alone.

The stack is intentionally small: Python, `yt-dlp`, `ffmpeg`, SponsorBlock, and a thin FastAPI UI. The interesting part is not the tools themselves. It is the glue code that makes the workflow reliable: canonical URLs, bounded retries, age gating, locked queue mutations, and success rules based on artifacts instead of hope.

If I were describing it in one sentence to an interviewer, I would say this: it is a lightweight media-ingestion pipeline that turns YouTube podcast sources into a clean, self-hosted listening library with enough systems thinking to run unattended.
