# Outline proposal

## Project scan summary

- Project archetype candidate: `data-pipeline`, with an operations and reliability emphasis.
- Supporting evidence from files: `src/downloads/service.py` implements queue expansion, download attempts, file-change detection, metadata stamping, publication, and retention; `src/state/` owns locked file-backed state; `src/api.py` adds a small authenticated control plane; `tests/` contains offline behavioral tests for those boundaries.

## Blueprint selection

- Selected blueprint: adapted data-pipeline blueprint.
- Why this blueprint fits this project: the central problem is not audio encoding itself but moving an item safely from an external URL to a local media library while keeping queue and archive state consistent.
- Planned section order:
  1. The gap between “the command exited” and “the episode exists”
  2. End-to-end pipeline and source-specific policy
  3. The success invariant: an MP3 must be created or changed
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
3. Archive transaction invariant:
   - Purpose: explain why the duplicate check, download, and success append share one exclusive lock.
   - Symbols: `u` is a normalized URL; `D(u)` is the download action; `H` is the archive set.
   - Delimiter: display.

## Planned code excerpts

1. File: `src/downloads/service.py`
   - Function/block: `_detect_changed_audio_files()`.
   - Why include this excerpt: it is the smallest implementation of the project’s most important success invariant.
2. File: `src/downloads/service.py`
   - Function/block: the archive-backed branch of `_download_video()`.
   - Why include this excerpt: it shows that duplicate detection and the success append happen inside one transaction.

## Planned technical graphs

1. Graph type: left-to-right pipeline diagram.
   - Source: generated from the code-defined stages and frozen labels in `blog/data/pipeline.json`.
   - Expected takeaway: external extraction is only one stage; success is established after local verification and metadata publication.
2. Graph type: reliability-gates diagram.
   - Source: generated from test-backed invariants in `blog/data/pipeline.json`.
   - Expected takeaway: each state mutation is conditional, and ambiguous metadata causes retention to keep a file rather than delete it.

## Risks, gaps, and assumptions

- Data gaps: the repository contains no production throughput, download-duration, or SponsorBlock hit-rate dataset, so the article will not claim such measurements.
- Assumptions: the reader knows what a web video and an MP3 are; `yt-dlp`, SponsorBlock, Cross-Site Request Forgery (CSRF), and inode are defined on first use.
- Validation checks to run before final draft: run the offline `tests/` suite, run the chart generator, validate both Markdown files, confirm every referenced image exists, and confirm English/French protected code and math blocks remain identical.
- Deployment note: the canonical workspace is `podcast-downloader/blog/`. At the user’s explicit request, there is no publish bundle and no copy, build, commit, or other access to `~/projects/website` in this task. Only the project-local blog package will be committed and pushed.
