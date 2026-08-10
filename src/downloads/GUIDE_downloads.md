# Downloads Guide

## Part 1: Download Workflow

`downloads/` turns one individual URL into a finished MP3. Channel and playlist
expansion happens in `media/youtube.py` before the URL reaches this folder.

```text
concrete URL
  -> YtDlpClient downloads into source-scoped scratch folder
  -> compare the MP3 files before and after the command
  -> AudioMetadataWriter writes the completion date and source URL
  -> PodcastDownloadService moves the MP3 into the final source folder
  -> queue/archive/bypass stores record the result
```

`YtDlpClient` builds the audio command, applies the per-attempt timeout, sets
SponsorBlock flags, chooses cookie order, records MP3 snapshots, and finds
changed files. The timeout comes from `download_timeout_seconds` in
`config.ini` and defaults to one hour so it can cover a long episode and MP3
conversion. It returns `YtDlpResult`, which includes the final status, output,
snapshots, changed files, and attempt count.

The service owns workflow decisions: age checks, expansion, publication,
metadata recovery, cleanup, retention, and archive transactions.
It accepts an injected client and consumes the client's typed result directly,
so command policy and snapshots are not reconstructed inside the service.

Expanded downloads hold a separate claim lock while external work runs, then
lock the archive only for short reads and writes. This prevents duplicates
without making web archive reads wait for a long download. Direct downloads use
their own cross-process lock because they share the `singles` scratch folder.

Download success requires at least one created or changed MP3 in the active
source work folder. If `$B$` is the before snapshot, `$A$` is the after
snapshot, and $s(p)$ is the modification-time/size state of file $p$, file $p$
changed when:

$$
p \notin B \quad \text{or} \quad s_A(p) \ne s_B(p)
$$

## Part 2: Code Reference

- `service.py`: `PodcastDownloadService`, source routing, publication, recovery,
  retention, and state coordination.
- `ytdlp_client.py`: `YtDlpClient`, `YtDlpResult`, `AudioSnapshot`, and all
  audio-download subprocess policy.
- `audio_metadata.py`: `AudioMetadataWriter`, which uses `ffmpeg` to preserve
  streams while writing project-managed tags.
- `__init__.py`: package marker.

## Part 3: Journal

- 2026-07-26: Audio subprocess execution, cookie retry policy, and snapshots
  moved into an injectable typed `YtDlpClient`; the service consumes its result
  directly.
- 2026-08-10: The per-attempt download timeout became the configurable
  `download_timeout_seconds` and its default rose from 300 seconds to one hour.
  The old five-minute budget could not finish a full-length episode, and a
  timed-out item is never archived, so the same episode failed on every run.
  `download.log` also gained rotation at 5 MB with three retained copies.
- 2026-08-10: Download claims moved off the archive file, direct scratch work
  gained a process lock, and age bypasses became consumed before their one run.
