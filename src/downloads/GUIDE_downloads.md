# Downloads Guide

## Part 1: Download Workflow

`downloads/` turns one concrete URL into a finished MP3. Channel and playlist
expansion happens in `media/youtube.py` before this boundary.

```text
concrete URL
  -> YtDlpClient downloads into source-scoped scratch folder
  -> changed MP3 files are identified from before/after snapshots
  -> AudioMetadataWriter stamps completion date and canonical source URL
  -> PodcastDownloadService publishes MP3 into the final source folder
  -> queue/archive/bypass stores record the state transition
```

`YtDlpClient` owns audio command construction, the 300-second subprocess
timeout, SponsorBlock flags, cookie/plain retry order, recursive MP3 snapshots,
and changed-file detection. It returns `YtDlpResult`, whose named fields include
the final exit status, output, snapshots, changed files, and attempt count.

The service owns use-case decisions: age checks, expansion orchestration,
publication, metadata recovery, cleanup, retention, and archive transactions.
It accepts an injected client and consumes the client's typed result directly,
so command policy and snapshots are not reconstructed inside the service.

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
