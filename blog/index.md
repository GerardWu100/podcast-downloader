---
title: "A Podcast Downloader That Does Not Trust Exit Code 0"
description: "How a self-hosted yt-dlp pipeline turns web videos into an Audiobookshelf library while keeping files, metadata, queues, and concurrent workers consistent."
date: 2026-07-13
image: images/cover-podcast-pipeline.png
categories: ["Computer Science", "Data Engineering"]
---

# A Podcast Downloader That Does Not Trust Exit Code 0

I wanted a small service that could watch a YouTube channel, strip sponsor segments, and place finished episodes in Audiobookshelf. The first version of that sentence sounds like a wrapper around one command. The finished project is mostly about everything that can go wrong around that command.

`yt-dlp` handles extraction. SponsorBlock supplies community-maintained time ranges for sponsor and self-promotion segments. `ffmpeg` copies the audio while updating its tags. Those tools handle the media work. The application still has to decide whether an episode really exists, whether it is safe to mark the URL as complete, and what happens when two scheduler processes see the same item.

The useful design lesson turned out to be simple: a successful subprocess is only evidence. It is not the state transition.

## From a URL to a library item

The queue accepts three kinds of input: a direct media URL, a YouTube channel, or a YouTube playlist. Channels and playlists are expanded into concrete videos. Direct URLs stay as one-off jobs. The policy then narrows the candidates: channel uploads can be held behind a minimum-age gate, YouTube Shorts are skipped, and playlists are capped at the configured number of recent entries.

YouTube downloads add SponsorBlock removal for the `sponsor` and `selfpromo` categories. Those category names follow the [SponsorBlock segment taxonomy](https://wiki.sponsor.ajay.app/w/Segment_Categories), and `yt-dlp` exposes them through its [`--sponsorblock-remove` option](https://github.com/yt-dlp/yt-dlp#sponsorblock-options). Non-YouTube URLs are downloaded as a single item, without SponsorBlock flags and without playlist expansion. Cookies can be tried first or used as a fallback, but only for YouTube.

![The complete URL-to-library pipeline](images/pipeline-flow.png)

The diagram separates three concerns that are easy to blur together. Source policy decides *what* to attempt. Local proof decides whether the attempt produced a usable artifact. Durable state changes only after that proof and publication succeed.

The scratch directory and the finished library are also separate. `yt-dlp` writes partial files, thumbnails, and converted audio into a per-source work folder. Only a stamped MP3 is moved into the Audiobookshelf-facing directory. A failed attempt cleans its scratch files, except for one narrow recovery case where an existing MP3 may be kept for a later metadata retry.

The output template is `%(channel,uploader)s - %(title)s [%(id)s].%(ext)s`. The first field prefers the channel name and falls back to the uploader; `id` is the extractor's media identifier. Including that identifier is not cosmetic. Two episodes from one channel may share a title, so channel plus title is not a unique key. The identifier keeps those files distinct while leaving the title readable.

## Define success from the filesystem

A return code of zero does not prove that a new MP3 appeared. An extractor can decide that an item is already present, reuse an existing path, or complete without producing the artifact the application expects. The downloader therefore snapshots every MP3 below the work directory before and after each attempt.

For an MP3 path $p$, let $m(p)$ be its filesystem modification time in nanoseconds and let $z(p)$ be its size in bytes. The recorded state is the ordered pair

$$
s(p) = \bigl(m(p), z(p)\bigr).
$$

Let $B$ be the set of MP3 paths in the snapshot taken before the command, and let $A$ be the corresponding set afterward. The changed-file set $C$ is

$$
C = \left\{p \in A : p \notin B \;\lor\; s_A(p) \ne s_B(p)\right\}.
$$

Here, $s_A(p)$ is the state of path $p$ after the attempt and $s_B(p)$ is its state before the attempt. Both snapshots are restricted to the active source work folder. That boundary is part of the proof: an MP3 created by another source cannot satisfy the current attempt. Checking modification time and size catches a new file as well as an existing file whose bytes were overwritten.

For a normalized URL $u$, let $r_u$ be the `yt-dlp` return code, let $C_u$ be the changed-file set in that source folder, and let $R_u$ be the conservative recovery set described below. Local artifact verification is

$$
V(u) = [r_u = 0] \land [|C_u| > 0 \lor |R_u| = 1].
$$

Let $M(u)$ mean that the metadata pass succeeded and let $P(u)$ mean that the stamped MP3 reached the final library folder. Durable success is

$$
S(u) = V(u) \land M(u) \land P(u).
$$

The queue or archive changes only when $S(u)$ is true. This is the actual state machine behind the prose: queued, attempted, verified, stamped, published, then recorded.

The implementation is intentionally plain:

```python
def _detect_changed_audio_files(
    self,
    before_snapshot: AudioSnapshot,
    after_snapshot: AudioSnapshot,
) -> list[Path]:
    """Return MP3 files created or changed during one command."""
    changed_files: list[Path] = []
    for file_path, updated_state in after_snapshot.files.items():
        previous_state = before_snapshot.files.get(file_path)
        if previous_state is None or updated_state != previous_state:
            changed_files.append(file_path)

    return sorted(changed_files)
```

There is one conservative recovery rule. If the before and after snapshots are identical, the command returned zero, and exactly one MP3 already exists in the active source work folder, the service may retry the metadata step on that file. This covers a prior run that downloaded the audio but failed while writing tags. With several possible MP3s, it refuses to guess. Scoping this lookup matters: an earlier implementation searched the entire intermediate tree and could mistake the sole MP3 from another source for the current URL's output. A regression test now fixes that boundary.

## Retry policy: alternate credentials, not blind repetition

The application makes at most two download attempts for a YouTube URL when a cookie file exists. If `always_use_cookies=true`, the first attempt uses cookies and the second is plain. If it is `false`, the order is reversed. The second attempt changes the authentication mode; repeating the identical request would add traffic without testing a different failure cause.

There is no application-level exponential backoff. `delay_seconds` spaces separate queue items, metadata lookups ask `yt-dlp` to sleep between requests, and `yt-dlp` retains its own extractor retry behavior. This distinction keeps the operational claim narrow: the service has a two-mode authentication fallback, not a general retry scheduler.

## Metadata is part of the transaction

Audiobookshelf needs more than audio bytes. After extraction, the service writes three useful pieces of provenance into the MP3:

- the local completion timestamp in the `date` tag;
- the normalized source URL in the `comment` tag;
- the resolved channel name in the `artist` and `album` tags when one is available.

That local completion timestamp is also the retention clock. It avoids confusing the video’s publication date with the date the file entered the local library.

The rewrite has a subtle constraint. `ffmpeg` needs a temporary output, but replacing the final path with that temporary file can change the file’s inode. An inode is the filesystem identity behind a path, and media-library watchers may interpret a replacement as one item disappearing and another appearing. The writer uses [FFmpeg streamcopy](https://ffmpeg.org/ffmpeg.html#Streamcopy) with `-codec copy`, creates a hidden non-MP3 temporary file, copies the rewritten bytes back into the original MP3, and removes the temporary file. The original path and inode survive; the audio stream is not re-encoded during this metadata pass.

Retention is deliberately fail-safe. It applies only to current YouTube channel folders, not playlists or one-off downloads. A file is eligible only when both its embedded completion date and source URL can be read. If either tag is missing or malformed, the service keeps the MP3 because it cannot safely update the archive after deletion.

![Reliability gates before state mutation or deletion](images/reliability-gates.png)

The asymmetry matters: download uncertainty leaves work retryable, while deletion uncertainty leaves data intact. Those are different failure modes and deserve different defaults.

## Idempotency needs a lock around the slow part

Expanded channel and playlist videos are recorded in `downloaded_urls.txt`. That archive makes repeated polling idempotent: seeing the same normalized URL again should not trigger another download.

A quick “check the file, then download, then append” sequence is still racy. Two workers can both check before either one appends. The code holds one exclusive file lock across the duplicate check, the slow download attempt, and the success append:

```python
if use_archive:
    with locked_downloaded_url_archive(self.downloaded_urls_file) as archive:
        if archive.contains(normalized_url):
            self._downloaded_urls.add(normalized_url)
            return normalized_url, True

        result_url, success = self._download_video_unlocked(
            normalized_url,
            index,
            total,
            target_final_output_dir,
            target_work_dir,
        )
        if success:
            archive.append_success(normalized_url)
            self._downloaded_urls.add(normalized_url)
        return result_url, success
```

Holding a lock during a network download is normally something I would question. Here it protects a narrow per-archive invariant, and concurrent duplicate work is more costly than waiting. The lock uses Python's [`fcntl.flock`](https://docs.python.org/3/library/fcntl.html#fcntl.flock), so this design assumes a Unix-like local filesystem with compatible advisory locking. The test suite starts two downloader objects against the same expanded URL and verifies that `yt-dlp` is called once.

The cost is serialization. The lock is per archive file, not per URL, so two different expanded videos also wait behind each other. That is acceptable for one personal scheduler; it would waste capacity in a multi-worker service. A database queue with per-job leases would be the natural replacement at larger scale.

The queue, archive, one-shot age-bypass list, and browser activity feed all remain ordinary UTF-8 text files. Shared locks protect reads; exclusive locks protect read-modify-write operations. This keeps deployment easy to inspect and back up without pretending that uncoordinated text-file writes are safe.

## Security and privacy boundaries

Every user-supplied URL appears after `--` in the subprocess command, which prevents a URL beginning with hyphens from becoming a `yt-dlp` option. Non-YouTube requests never receive the cookie path. Browser uploads accept Netscape-format cookie text, normalize line endings, and write the file with owner-only mode `600` on Unix-like systems.

That permission bit does not make exported browser cookies harmless. A browser export may contain sessions for sites other than YouTube, so the file belongs in private persistent storage and outside version control. The web interface is an administrative surface for one operator: password hashing, session expiry, Cross-Site Request Forgery protection, and restrictive response headers reduce common browser risks, but the service is not designed for public multi-user hosting.

## What the test suite establishes

I ran the full offline regression suite on July 13, 2026. All 185 tests passed in roughly nine seconds on the audit machine. These are behavioral tests with temporary directories and patched subprocesses, not a throughput benchmark.

| Verified boundary | Evidence in the suite |
|---|---|
| Artifact detection | New and overwritten MP3 files in the active work folder count; unrelated folders and return code zero without an MP3 do not |
| Safe publication | Finished MP3 moves from scratch space; temporary artifacts are removed |
| Metadata | Date and source URL are written; the final MP3 inode is preserved |
| Concurrency | Locked archive readers and writers serialize; two workers download one expanded URL once |
| Retention | Only eligible channel files are removed; missing metadata keeps files in place |
| Source policy | SponsorBlock is YouTube-only; direct URLs, channels, playlists, Shorts, age gates, cookies, and media-ID filenames follow distinct rules |
| Web control plane | Passwords, sessions, Cross-Site Request Forgery tokens, proxy trust, cookie upload, and queue mutation have regression coverage |

Cross-Site Request Forgery (CSRF) is an attack in which a browser is tricked into submitting an authenticated action. The web interface uses one-time login tokens and per-session tokens for state-changing forms, alongside a hashed password and restrictive browser headers. That is reasonable protection for a personal admin surface, but it does not turn the service into a general multi-user platform.

The repository also contains a root-level live SponsorBlock smoke script. It imports the separately installed `yt-dlp` package only inside its entrypoint and contacts external services when run directly. The lazy import lets the full offline suite collect the repository without that optional package. I did not run the live download in this audit; a deployment should run it separately when `yt-dlp`, `ffmpeg`, cookies, and network access are available.

## Where this design stops

This project is built for a personal Audiobookshelf workflow. Its file-backed state is attractive because the operating scale is small and the files are transparent. It would become the wrong storage model if many workers, several users, or a remote shared filesystem entered the picture. At that point, a database-backed job queue with leases and explicit state transitions would be easier to reason about.

External behavior remains the largest uncontrolled variable. YouTube changes extraction requirements, browser cookies expire, SponsorBlock coverage varies by video, and `yt-dlp` evolves quickly enough that this project installs a current release outside its lockfile. The Docker image includes Deno for current YouTube JavaScript challenges, but no packaging choice can make an external extractor permanently stable.

Still, the local boundary is solid: do not mutate durable state because a command sounded confident. Observe the artifact, stamp its provenance, publish it, and only then mark the work complete.

## References

- [`yt-dlp` README: output templates, paths, retries, and SponsorBlock options](https://github.com/yt-dlp/yt-dlp)
- [SponsorBlock segment categories](https://wiki.sponsor.ajay.app/w/Segment_Categories)
- [FFmpeg documentation: streamcopy and metadata options](https://ffmpeg.org/ffmpeg.html)
- [Python documentation: `fcntl.flock`](https://docs.python.org/3/library/fcntl.html#fcntl.flock)
- [Audiobookshelf documentation](https://www.audiobookshelf.org/docs/)
