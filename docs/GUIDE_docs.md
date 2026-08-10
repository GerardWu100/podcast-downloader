# Docs Guide

## Part 1: Documentation Purpose

`docs/` contains material for users and operators. Developer navigation lives
in the `GUIDE_*` files beside the code.

The reading order is:

1. `intro.md` for the purpose and project map.
2. `architecture.md` for the pipeline, code boundaries, saved state, and trust.
3. `cli-and-config.md` for commands and settings.
4. `web-ui-security.md` for sign-in and browser protections.
5. `operations.md` for local and Docker operation.
6. `review-and-safety.md` for review findings and remaining risks.

`superpowers/plans/` stores implementation plans as historical engineering
artifacts. A completed plan may describe modules that existed before its
refactor; current architecture is documented in `architecture.md`.

## Part 2: Code Reference

- `architecture.md`: corresponds to `src/web/`, `src/media/`, `src/downloads/`,
  and `src/state/`.
- `cli-and-config.md`: corresponds to `src/cli.py` and `src/config.py`.
- `web-ui-security.md`: corresponds to `src/web/auth.py`,
  `src/web/routes.py`, and `src/state/auth_store.py`.
- `operations.md`: corresponds to `start.py`, `docker-entrypoint.sh`, and the
  container files.

## Part 3: Journal

- 2026-07-26: Consolidated stale root overview files into the canonical
  architecture page and updated docs for the extracted module boundaries.
