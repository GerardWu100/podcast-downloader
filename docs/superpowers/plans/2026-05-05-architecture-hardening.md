# Conservative Refactoring Plan

## Purpose

This plan improves structure and extensibility without rewriting the application or
changing its user-visible behavior. The project remains one Python application with:

- a command-line interface (CLI);
- a FastAPI web interface;
- `yt-dlp` and `ffmpeg` subprocesses;
- plain files for queue, archive, activity, and authentication state; and
- one Docker container running one web worker and one scheduler thread.

The refactor should make it easier to add another media source, web page, state file,
or download policy without editing one very large module.

## Current Baseline

The repository already completed much of its original architecture-hardening work:

- Queue, archive, bypass, and activity state are owned by classes in `src/state/`.
- Queue and archive mutations use file locks.
- Configuration values are validated by `src/config.py`.
- Download metadata recovery and archive-backed concurrency have regression tests.
- Audio metadata writing lives in `src/downloads/audio_metadata.py`.
- The scheduler invokes `python -m src.cli` from a resolved project root.
- The complete offline suite currently has 187 passing tests.

The remaining structural pressure is concentrated in three modules:

| Module | Approximate size | Mixed responsibilities |
|---|---:|---|
| `src/api.py` | 1,535 lines | app creation, authentication, state, routes, HTML, CSS, and JavaScript |
| `src/downloads/service.py` | 1,287 lines | orchestration, subprocess execution, file publication, recovery, and retention |
| `src/url_utils.py` | 887 lines | generic URLs, YouTube policy, metadata subprocesses, expansion, and state adapters |

Line count is not itself a defect. These files should be split because they contain
independent responsibilities that change for different reasons.

## Constraints

Every phase must follow these rules:

1. Preserve observable CLI, web, scheduler, download, and file-format behavior.
2. Keep the application deployable after every commit.
3. Move one responsibility at a time; do not reorganize the entire tree at once.
4. Add or adjust contract tests before removing an old boundary.
5. Use explicit constructor or function parameters for collaborators instead of
   adding new module-level mutable state.
6. Remove an obsolete adapter once all project callers use the new interface. The
   project does not promise backward compatibility for internal Python imports.
7. Keep plain-file state. Do not introduce a database as part of this refactor.
8. Keep subprocess isolation between the scheduler and CLI.

## Explicitly Out Of Scope

The following changes may be useful one day, but would add risk without helping the
current refactor:

- renaming the importable `src` package to `podcast_downloader`;
- introducing SQLite, PostgreSQL, Redis, or a message broker;
- splitting the application into multiple services or containers;
- adopting a template framework or a JavaScript build system;
- changing CLI options, configuration keys, state-file formats, or URL semantics;
- redesigning the web interface;
- making immediate scheduler requests durable across container restarts; and
- broad performance optimization without a measured problem.

## Target Structure

This is a direction, not a requirement to create every file immediately:

```text
src/
├── api.py                     # small Uvicorn entrypoint exporting app
├── cli.py                     # CLI parsing and dispatch
├── config.py                  # validated configuration
├── passwords.py               # password hashing and verification
├── trigger.py                 # in-process immediate-run requests
├── web/
│   ├── app.py                 # create_app() and dependency wiring
│   ├── auth.py                # authentication and request-security policy
│   ├── routes.py              # FastAPI route handlers
│   └── templates.py           # HTML, CSS, and JavaScript rendering
├── media/
│   ├── urls.py                # generic URL validation
│   └── youtube.py             # YouTube normalization, metadata, and expansion
├── downloads/
│   ├── service.py             # use-case orchestration
│   ├── ytdlp_client.py        # yt-dlp commands and subprocess execution
│   └── audio_metadata.py      # ffmpeg metadata reading and writing
└── state/
    ├── file_locks.py
    ├── queue_store.py
    ├── archive_store.py
    ├── bypass_store.py
    ├── activity_store.py
    └── auth_store.py          # login and session JSON persistence
```

The service layer may remain relatively large. Its job is to describe the download
workflow. Low-level command construction, persistence, and rendering should not live
there.

## Phase 1: Establish Stable Construction Seams

**Goal:** Make dependencies explicit before moving substantial behavior.

### Work

- Add `create_app(config, ...) -> FastAPI` in `src/web/app.py`.
- Keep `src/api.py` as the Uvicorn entrypoint that loads configuration and calls
  `create_app()`.
- Pass queue, archive, activity, trigger, and authentication collaborators into the
  app factory, with production defaults constructed in one place.
- Add a small test fixture that creates an application using temporary paths without
  patching `src.api` globals.
- Leave existing routes and rendered pages unchanged during this phase.

### Why first

An application factory is a function that builds and configures the FastAPI
application. It gives tests and future entrypoints a clean place to supply their own
configuration and state objects. Without it, later file movement would merely spread
the existing globals across more modules.

### Acceptance checks

```bash
uv run python -m pytest tests/test_api_behavior.py tests/test_security.py -q
uv run ruff check src/api.py src/web tests/test_api_behavior.py tests/test_security.py
```

- `uvicorn src.api:app` remains the deployment command.
- Importing the web implementation does not require patching production paths.
- Existing web behavior and security headers remain unchanged.

## Phase 2: Extract Web Rendering And Authentication

**Goal:** Reduce `src/api.py` without redesigning the web interface.

### Step 2A: Rendering

- Move page-rendering functions and the existing HTML, Cascading Style Sheets (CSS),
  and JavaScript strings into `src/web/templates.py`.
- Pass already-escaped values into narrowly named rendering functions.
- Keep nonce-based Content Security Policy behavior and escaping tests.
- Do not introduce Jinja2 or another templating dependency.

Rendering is the lowest-risk extraction because it does not mutate state.

### Step 2B: Authentication state

- Add `AuthStore` in `src/state/auth_store.py`.
- Give it explicit methods for login-failure state and remembered sessions.
- Use the existing file-lock helper so read-modify-write operations are interprocess
  safe.
- Write JSON through a temporary sibling file followed by `Path.replace()` so a
  process interruption cannot leave a partially written state file.
- Keep Cross-Site Request Forgery (CSRF) token policy and cookie policy in
  `src/web/auth.py`.

CSRF is protection against another site causing a logged-in browser to submit an
unwanted request.

### Step 2C: Routes

- Move route handlers into `src/web/routes.py`.
- Register the routes from `create_app()`.
- Group authentication routes separately from queue, cookie, and log routes inside
  the module, but do not create multiple router files unless the module remains hard
  to navigate after extraction.

### Acceptance checks

```bash
uv run python -m pytest tests/test_api_behavior.py tests/test_security.py -q
uv run python -m pytest -q
uv run ruff check .
uv run ruff format --check .
```

- Login, logout, session restoration, rate limiting, queue editing, cookie upload,
  and log viewing behave exactly as before.
- `src/api.py` contains only production configuration and application construction.
- Tests no longer mutate `SESSIONS`, `CONFIG`, or state-file path globals in
  `src.api.py`.

## Phase 3: Separate Media Policy From State Adapters

**Goal:** Make support for another media source possible without growing
`src/url_utils.py`.

### Work

- Create `src/media/urls.py` for generic `http` and `https` validation.
- Create `src/media/youtube.py` for:
  - host detection;
  - video URL normalization;
  - Shorts, playlist, and channel classification;
  - channel and playlist expansion;
  - display-name and folder-name metadata; and
  - upload-age checks.
- Move YouTube metadata and expansion command construction with the YouTube policy.
- Update production callers and tests to import from `src.media`.
- Delete the queue, archive, and bypass wrapper functions from `src/url_utils.py`
  after callers use the corresponding stores directly.
- Delete `src/url_utils.py` when it no longer owns behavior.

### Design boundary

`src/media/` decides what a URL means and which concrete media URLs it represents.
`src/state/` decides how URLs are stored. `src/downloads/` decides how a concrete URL
becomes an MP3. These dependencies should flow in one direction:

```text
web / CLI
    |
    +----> state
    |
    +----> media ----> yt-dlp metadata commands
                 |
                 v
             downloads ----> state
```

### Acceptance checks

```bash
uv run python -m pytest tests/test_url_utils_behavior.py tests/test_security.py -q
uv run python -m pytest tests/test_downloader.py tests/test_cli_behavior.py -q
uv run python -m pytest -q
```

- URL normalization and expansion results are unchanged.
- Every `yt-dlp` command still places `--` before a user-provided URL.
- Queue and archive behavior is tested through store classes, not URL modules.
- No circular imports exist between `media`, `downloads`, and `state`.

## Phase 4: Complete The `yt-dlp` Client Boundary

**Goal:** Let the download service express workflow while a dedicated client owns
external command execution.

### Work

- Expand `src/downloads/ytdlp_client.py` to own:
  - audio snapshots and changed-file detection;
  - download command construction;
  - subprocess execution and timeout handling;
  - SponsorBlock flags;
  - cookie-first and cookie-fallback retry order; and
  - a typed result describing exit status, output, and changed MP3 files.
- Inject `YtDlpClient` into `PodcastDownloadService`.
- Keep queue expansion metadata calls in `src/media/youtube.py`; they are a different
  use case from downloading audio.
- Keep publication, retry recovery, and retention orchestration in
  `PodcastDownloadService` initially.
- Extract a separate publisher or retention class only if the service remains
  difficult to test after the client extraction. Do not create classes solely to
  reduce line count.

A typed result is a small data class with named fields rather than an unstructured
tuple or subprocess object.

### Acceptance checks

```bash
uv run python -m pytest tests/test_downloader.py tests/test_archive_locking.py -q
uv run python -m pytest -q
uv run ruff check .
```

- Direct, channel, playlist, retry, recovery, and retention behavior is unchanged.
- Service tests can substitute a fake `YtDlpClient` instead of patching
  `subprocess.run` or private service methods.
- Live-network tests remain outside the normal offline suite.

## Phase 5: Simplify Tests Around Public Contracts

**Goal:** Preserve strong coverage while making implementation movement affordable.

### Work

- Replace private-method monkeypatches when the same behavior can be exercised
  through `create_app()`, `YtDlpClient`, media functions, or store classes.
- Keep focused unit tests for command construction and file-state transitions.
- Keep a small number of higher-level tests for:
  - a successful direct-video workflow;
  - an expanded channel or playlist workflow;
  - metadata-stamp recovery;
  - concurrent archive protection; and
  - authenticated queue submission.
- Split a test file only when its tests align with a new production boundary. Avoid
  mechanically creating one test file per implementation file.
- Preserve all security regression cases.

### Acceptance checks

```bash
uv run python -m pytest -q
uv run ruff check .
uv run ruff format --check .
```

- Tests describe observable results or collaborator contracts.
- Routine internal method renaming does not require widespread test changes.
- Test runtime remains suitable for frequent offline execution.

## Phase 6: Remove Transitional Clutter

**Goal:** Finish the refactor instead of leaving permanent compatibility layers.

### Work

- Remove `src/downloader.py` after CLI and tests import
  `PodcastDownloadService` directly.
- Remove `src/activity_log.py` if all callers use `ActivityLogStore`.
- Remove `src/url_utils.py` after Phase 3.
- Move `ruff` from runtime dependencies into the development dependency group.
- Consolidate duplicated root documentation:
  - keep `README.md` for users;
  - keep `GUIDE_ROOT.md` for code navigation;
  - keep `docs/architecture.md` for detailed design; and
  - merge useful unique content from `PROJECT_OVERVIEW.md` and
    `FILE_STRUCTURE.md`, then remove them.
- Replace machine-specific `/Users/gwh/...` documentation links with portable
  relative links.
- Update all `GUIDE_*` files in the same commit as the structural changes they
  describe.

### Acceptance checks

```bash
uv sync --dev
uv run python -m pytest -q
uv run python -m compileall -q src tests main.py start.py
uv run ruff check .
uv run ruff format --check .
```

- No internal compatibility module remains without a current caller.
- Documentation points to the actual final module boundaries.
- A clean environment can install and run the project using documented commands.

## Commit Strategy

Each step should be a small, reviewable commit. A reasonable sequence is:

1. `refactor: add FastAPI application factory`
2. `refactor: extract web page rendering`
3. `refactor: add locked authentication store`
4. `refactor: separate web routes and authentication`
5. `refactor: separate media URL policy`
6. `refactor: isolate yt-dlp download execution`
7. `test: use public architecture seams`
8. `chore: remove transitional modules and stale docs`

Do not combine all phases into one branch-sized commit. If a phase reveals a behavior
ambiguity, add a regression test and resolve that ambiguity before continuing.

## Stop Conditions

Pause the refactor and reassess if any of these occur:

- a phase requires changing persisted file formats;
- the same behavior must be implemented in both old and new modules for more than
  one phase;
- test runtime or flakiness materially worsens;
- the application factory requires a large dependency-injection framework;
- a proposed class has no meaningful invariant or independent test contract; or
- a file move starts changing user-visible behavior.

These are signs that the step is too broad or the proposed boundary is artificial.

## Definition Of Done

The refactor is complete when:

- `src/api.py` is a small deployment entrypoint;
- web authentication, routes, and rendering have explicit owners;
- generic and YouTube-specific URL policy no longer share a catch-all module;
- `YtDlpClient` owns audio-download subprocess execution;
- state mutations go through store classes;
- the download service coordinates policy rather than implementing every low-level
  operation;
- obsolete compatibility modules are removed;
- the complete offline suite, Ruff linting, Ruff formatting, and bytecode compilation
  pass; and
- README, architecture documentation, and `GUIDE_*` files match the code.

## Deferred Improvements

Consider these only in response to an actual requirement:

- Use SQLite if multiple web workers or richer transactional state become necessary.
- Persist immediate scheduler requests if “download now” must survive restarts.
- Adopt `src/podcast_downloader/` if the project becomes an installed library or is
  published as a package.
- Add a media-provider interface after a second non-YouTube provider needs custom
  expansion or metadata policy. Do not design that interface before a concrete
  second implementation exists.

## TL;DR

Refactor through small seams: first construct the web app explicitly, then extract
web rendering and authentication, separate media policy, isolate `yt-dlp` execution,
improve tests around those public boundaries, and finally delete transitional
clutter. Keep the current deployment model and plain-file state throughout.
