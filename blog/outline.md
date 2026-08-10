# Outline proposal

## Project scan summary

- Project archetype candidate: `data-pipeline`, with an operations and reliability emphasis.
- Supporting evidence from files: `src/downloads/service.py` expands the queue, runs downloads, checks changed files, writes tags, publishes files, and cleans up old files; `src/state/` owns locked file-based state; `src/api.py` adds a small signed-in admin screen; `tests/` contains offline behavior tests for those boundaries.

## Blueprint selection

- Selected blueprint: adapted data-processing blueprint.
- Why this blueprint fits this project: the central problem is not audio encoding itself but moving an item safely from an external URL to a local media library while keeping queue and archive state consistent.
- Planned section order:
  1. The gap between “the command exited” and “the episode exists”
  2. End-to-end pipeline and source-specific policy
  3. The success rule: an MP3 must be created or changed
  4. Safe metadata rewriting and library publication
  5. File-backed idempotency under concurrent workers
  6. Evidence from the offline regression suite
  7. Operational limits and appropriate use

## Planned equations

1. MP3 state definition:
   - Purpose: formalize the snapshot used before and after a download attempt.
   - Symbols: `p` is an MP3 path; `m(p)` is modification time in nanoseconds; `z(p)` is size in bytes; `s(p)` is the pair `(m(p), z(p))`.
   - Delimiter: display.
2. Changed-file set:
   - Purpose: define success independently of a subprocess return code.
   - Symbols: `B` and `A` are the before and after path sets; `C` is the set of new or changed MP3 paths.
   - Delimiter: display.
3. Archive transaction rule:
   - Purpose: explain why the duplicate check, download, and success record share one exclusive lock.
   - Symbols: `u` is a normalized URL; `D(u)` is the download action; `H` is the archive set.
   - Delimiter: display.
4. Durable-success predicate:
   - Purpose: show that file checks, tag writing, and publication must all succeed before saved state changes.
   - Symbols: `u` is a normalized URL; `r_u` is the subprocess return code; `C_u` is the source-scoped changed-file set; `R_u` is the recovery set; `M(u)` and `P(u)` are metadata and publication success indicators.
   - Delimiter: display.

## Planned code excerpts

1. File: `src/downloads/service.py`
   - Function/block: `_detect_changed_audio_files()`.
   - Why include this excerpt: it is the smallest implementation of the project’s most important success rule.
2. File: `src/downloads/service.py`
   - Function/block: the archive-backed branch of `_download_video()`.
   - Why include this excerpt: it shows that duplicate detection and the success append happen inside one transaction.

## Planned technical graphs

1. Graph type: left-to-right pipeline diagram.
   - Source: generated from the code-defined stages and frozen labels in `blog/data/pipeline.json`.
- Expected takeaway: external extraction is only one stage; success is established after local checks and tag writing.
2. Graph type: reliability-gates diagram.
   - Source: generated from test-backed invariants in `blog/data/pipeline.json`.
- Expected takeaway: each state change is conditional, and unclear tags cause retention to keep a file rather than delete it.

## Risks, gaps, and assumptions

- Data gaps: the repository contains no production throughput, download-duration, or SponsorBlock hit-rate dataset, so the article will not claim such measurements.
- Assumptions: the reader knows what a web video and an MP3 are; `yt-dlp`, SponsorBlock, Cross-Site Request Forgery (CSRF), and inode are defined on first use.
- Validation checks to run before final draft: run the offline `tests/` suite, run the chart generator, validate both Markdown files, confirm every referenced image exists, and confirm English/French protected code and math blocks remain identical.
- Audit corrections: keep the optional live `yt-dlp` import out of pytest collection, scope recovery to the active work folder, and include the extractor media ID in output filenames.
- Deployment note: the canonical workspace is `podcast-downloader/blog/`. At the user’s explicit request, there is no publish bundle and no copy, build, commit, or other access to `~/projects/website` in this task. Only the project-local blog package will be committed and pushed.
