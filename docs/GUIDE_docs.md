# Docs Guide

## Purpose and Problem Statement

[`docs/`](/Users/gwh/projects/one-time-projects/podcast-downloader/docs) contains end-user and operator-facing Markdown documentation written to be easy to import into Docusaurus later. The folder exists separately from the root `GUIDE_*` files because it serves a different audience and a different goal:

- The `GUIDE_*` files are navigation aids for future coding sessions.
- The `docs/` files are publishable project documentation for a documentation site.

The guiding principle is simple: a new user should be able to understand what the project does, how to run it, how the web UI is secured, and what risks remain without reading the source code.

## Documentation Structure

The folder is organized by topic rather than by source file:

1. `intro.md` gives the high-level description and reading order.
2. `architecture.md` explains the pipeline, trust boundaries, the queue mutation model, and the archive-locking behavior.
3. `cli-and-config.md` documents command-line usage, the one-shot age-gate bypass flag, and configuration.
4. `web-ui-security.md` explains login, sessions, CSRF, headers, and proxy trust.
5. `operations.md` explains local usage, Docker behavior, the scheduler, and operational files.
6. `review-and-safety.md` captures the findings and fixes from the latest project review.
7. `superpowers/plans/` holds agent-executable architecture and implementation plans that are not publishable user documentation.

These pages are plain Markdown with light frontmatter so they can be adopted by Docusaurus later with minimal cleanup.

## Folder Tree

```text
docs/
├── GUIDE_docs.md
├── architecture.md
├── cli-and-config.md
├── intro.md
├── operations.md
├── review-and-safety.md
├── superpowers/
│   └── plans/
│       └── 2026-05-05-architecture-hardening.md
└── web-ui-security.md
```

- `intro.md`: project entry page and recommended reading order.
- `architecture.md`: end-to-end flow, design decisions, and trust boundaries.
- `cli-and-config.md`: CLI usage plus `config.ini` and environment variables.
- `web-ui-security.md`: authentication, CSRF, session, CSP, and proxy guidance.
- `operations.md`: setup, Docker bootstrap, scheduler, and runtime files.
- `review-and-safety.md`: summary of the safety review and remaining risks.
- `superpowers/plans/2026-05-05-architecture-hardening.md`: architecture critique, likely bug list, and staged refactor plan for future implementation.

## Code Reference

- The `docs/` folder documents behavior implemented mostly in [`src/api.py`](/Users/gwh/projects/one-time-projects/podcast-downloader/src/api.py), [`src/downloader.py`](/Users/gwh/projects/one-time-projects/podcast-downloader/src/downloader.py), [`src/url_utils.py`](/Users/gwh/projects/one-time-projects/podcast-downloader/src/url_utils.py), and [`start.py`](/Users/gwh/projects/one-time-projects/podcast-downloader/start.py).
- Use these docs when preparing a Docusaurus site, onboarding a new maintainer, or reviewing the project’s security posture without reading the source.
