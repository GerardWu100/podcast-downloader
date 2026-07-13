---
title: "A Podcast Downloader That Does Not Trust Exit Code 0"
description: "How a self-hosted yt-dlp pipeline turns web videos into an Audiobookshelf library while keeping files, metadata, queues, and concurrent workers consistent."
date: 2026-07-13
image: images/cover-podcast-pipeline.png
categories: ["Computer Science", "Data Engineering"]
---

# A Podcast Downloader That Does Not Trust Exit Code 0

I wanted a small service that could watch a YouTube channel, strip sponsor segments, and place finished episodes in Audiobookshelf. The first version of that sentence sounds like a wrapper around one command. The finished project is mostly about everything that can go wrong around that command.

`yt-dlp` handles extraction. SponsorBlock supplies community-maintained time ranges for sponsor and self-promotion segments. `ffmpeg` copies the audio while updating its tags. Those tools do the media work well. The application still has to decide whether an episode really exists, whether it is safe to mark the URL as complete, and what happens when two scheduler processes see the same item.

The useful design lesson turned out to be simple: a successful subprocess is only evidence. It is not the state transition.

## From a URL to a library item

The queue accepts three kinds of input: a direct media URL, a YouTube channel, or a YouTube playlist. Channels and playlists are expanded into concrete videos. Direct URLs stay as one-off jobs. The policy then narrows the candidates: channel uploads can be held behind a minimum-age gate, YouTube Shorts are skipped, and playlists are capped at the configured number of recent entries.

YouTube downloads add SponsorBlock removal for the `sponsor` and `selfpromo` categories. Non-YouTube URLs are deliberately more conservative: they are downloaded as a single item, without SponsorBlock flags and without playlist expansion. Cookies can be tried first or used as a fallback, but only for YouTube.

![The complete URL-to-library pipeline](images/pipeline-flow.png)

The diagram separates three concerns that are easy to blur together. Source policy decides *what* to attempt. Local proof decides whether the attempt produced a usable artifact. Durable state changes only after that proof and publication succeed.

The scratch directory and the finished library are also separate. `yt-dlp` writes partial files, thumbnails, and converted audio into a per-source work folder. Only a stamped MP3 is moved into the Audiobookshelf-facing directory. A failed attempt cleans its scratch files, except for one narrow recovery case where an existing MP3 may be kept for a later metadata retry.

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

Here, $s_A(p)$ is the state of path $p$ after the attempt and $s_B(p)$ is its state before the attempt. The ordinary success path requires both a zero return code and at least one path in $C$. Checking modification time and size catches a new file as well as an existing file whose bytes were overwritten.

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

There is one conservative recovery rule. If the before and after snapshots are identical, the command returned zero, and exactly one MP3 already exists in the target directory, the service may retry the metadata step on that file. This covers a prior run that downloaded the audio but failed while writing tags. With several possible MP3s, it refuses to guess.

## Metadata is part of the transaction

Audiobookshelf needs more than audio bytes. After extraction, the service writes three useful pieces of provenance into the MP3:

- the local completion timestamp in the `date` tag;
- the normalized source URL in the `comment` tag;
- the resolved channel name in the `artist` and `album` tags when one is available.

That local completion timestamp is also the retention clock. It avoids confusing the video’s publication date with the date the file entered the local library.

The rewrite has a subtle constraint. `ffmpeg` needs a temporary output, but replacing the final path with that temporary file can change the file’s inode. An inode is the filesystem identity behind a path, and media-library watchers may interpret a replacement as one item disappearing and another appearing. The writer instead creates a hidden non-MP3 temporary file, copies the rewritten bytes back into the original MP3, and removes the temporary file. The original path and inode survive.

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

Holding a lock during a network download is normally something I would question. Here it protects a narrow per-archive invariant, and concurrent duplicate work is more costly than waiting. The test suite starts two downloader objects against the same expanded URL and verifies that `yt-dlp` is called once.

The queue, archive, one-shot age-bypass list, and browser activity feed all remain ordinary text files. Shared locks protect reads; exclusive locks protect read-modify-write operations. This keeps deployment easy to inspect and back up without pretending that uncoordinated text-file writes are safe.

## What the test suite establishes

I ran the offline regression suite on July 13, 2026. All 184 tests passed in 9.32 seconds. These are behavioral tests with temporary directories and patched subprocesses, not a throughput benchmark.

| Verified boundary | Evidence in the suite |
|---|---|
| Artifact detection | New and overwritten MP3 files count; return code zero without an MP3 does not |
| Safe publication | Finished MP3 moves from scratch space; temporary artifacts are removed |
| Metadata | Date and source URL are written; the final MP3 inode is preserved |
| Concurrency | Locked archive readers and writers serialize; two workers download one expanded URL once |
| Retention | Only eligible channel files are removed; missing metadata keeps files in place |
| Source policy | SponsorBlock is YouTube-only; direct URLs, channels, playlists, Shorts, age gates, and cookies follow distinct rules |
| Web control plane | Passwords, sessions, Cross-Site Request Forgery tokens, proxy trust, cookie upload, and queue mutation have regression coverage |

Cross-Site Request Forgery (CSRF) is an attack in which a browser is tricked into submitting an authenticated action. The web interface uses one-time login tokens and per-session tokens for state-changing forms, alongside a hashed password and restrictive browser headers. That is reasonable protection for a personal admin surface, but it does not turn the service into a general multi-user platform.

The repository also contains a root-level live SponsorBlock smoke script. It imports the separately installed `yt-dlp` package and contacts external services. I did not count it as part of the 184-test offline result; collecting the whole repository without that optional package stops at import time. A real deployment should run that smoke check separately when `yt-dlp`, `ffmpeg`, cookies, and network access are available.

## Where this design stops

This project is built for a personal Audiobookshelf workflow. Its file-backed state is attractive because the operating scale is small and the files are transparent. It would become the wrong storage model if many workers, several users, or a remote shared filesystem entered the picture. At that point, a database-backed job queue with leases and explicit state transitions would be easier to reason about.

External behavior remains the largest uncontrolled variable. YouTube changes extraction requirements, browser cookies expire, SponsorBlock coverage varies by video, and `yt-dlp` evolves quickly enough that this project installs a current release outside its lockfile. The Docker image includes Deno for current YouTube JavaScript challenges, but no packaging choice can make an external extractor permanently stable.

Still, the local boundary is solid: do not mutate durable state because a command sounded confident. Observe the artifact, stamp its provenance, publish it, and only then mark the work complete.
