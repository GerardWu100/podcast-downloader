# Downloads guide

## Download workflow

`downloads/` turns one individual URL into a finished MP3. YouTube channel and playlist expansion happens in `media/youtube.py` before a URL reaches this package.

```text
concrete URL
  -> YtDlpClient downloads into a source-specific scratch folder
  -> compare MP3 files before and after the command
  -> AudioMetadataWriter adds the date and source URL
  -> PodcastDownloadService moves the MP3 to its final folder
  -> queue, archive, and bypass stores record the result
```

`YtDlpClient` owns the external download command. It sets the timeout, SponsorBlock flags, YouTube player client, and cookie order. It also records MP3 snapshots and identifies changed files. The timeout comes from `download_timeout_seconds` in `config.ini` and defaults to one hour, enough for a long episode and MP3 conversion.

The client returns a `YtDlpResult` containing the final status, command output, before/after snapshots, changed files, and attempt count.

Two command details are easy to break:

- Keep `--output` as a bare filename template. `yt-dlp` ignores `--paths` and warns about absolute output templates. Put the destination in `--paths home:` and the scratch folder in `--paths temp:`.
- YouTube downloads pass `--extractor-args youtube:player_client=<youtube_player_client>`. Most player clients now return stream URLs that require a GVS PO Token (a proof-of-origin token from YouTube’s web player), causing `HTTP Error 403: Forbidden` after metadata succeeds. The default `web_embedded` client still provides usable URLs.

`PodcastDownloadService` owns workflow decisions: age checks, expansion, publication, metadata recovery, cleanup, retention, and archive updates. It receives an injected client and uses the client’s typed result directly, so it does not rebuild command policy or file snapshots.

Expanded downloads use a claim lock while external work runs, then lock the archive only for short reads and writes. This prevents duplicate downloads without making web archive reads wait for a long download. Direct downloads use a separate cross-process lock because they share the `singles` scratch folder.

A download succeeds only when at least one MP3 is created or changed in the active source work folder. If `$B$` is the before snapshot, `$A$` is the after snapshot, and $s(p)$ is the modification-time/size state of file $p$, then file $p$ changed when:

$$
p \notin B \quad \text{or} \quad s_A(p) \ne s_B(p)
$$

## Code reference

- `service.py`: `PodcastDownloadService`, source routing, publication, recovery, retention, and state coordination.
- `ytdlp_client.py`: `YtDlpClient`, `YtDlpResult`, `AudioSnapshot`, and external download policy.
- `audio_metadata.py`: `AudioMetadataWriter`, which uses `ffmpeg` to preserve streams while writing project-managed tags.
- `__init__.py`: package marker.

## Journal

- 2026-07-26: Audio subprocess execution, cookie retries, and snapshots moved into the injectable, typed `YtDlpClient`; the service now consumes its result directly.
- 2026-08-10: The per-attempt timeout became the configurable `download_timeout_seconds`, with a default of one hour. The old five-minute limit could not finish a full-length episode, and timed-out items were never archived. `download.log` also gained 5 MB rotation with three retained copies.
- 2026-08-10: Download claims moved off the archive file, direct scratch work gained a process lock, and age bypasses became one-use values consumed before their run.
