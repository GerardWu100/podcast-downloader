# Docs guide

## Purpose

`docs/` contains the project's user and operator documentation. Read the guides
when you need to see how those documents map to the codebase. The guides are
for developers and future agents.

Read these in order:

1. `intro.md` — purpose and project map
2. `architecture.md` — pipeline, boundaries, saved state, and trust
3. `cli-and-config.md` — commands and settings
4. `notifications.md` — Apprise error notifications
5. `web-ui-security.md` — sign-in and browser protections
6. `browser-extension.md` — the browser extension and `/api` routes
7. `operations.md` — local and Docker operation

## Code reference

The documents map to code as follows:

- `architecture.md`: `src/web/`, `src/media/`, `src/downloads/`, and `src/state/`.
- `cli-and-config.md`: `src/cli.py` and `src/config.py`.
- `notifications.md`: `src/notifications/` and `src/state/notification_store.py`.
- `web-ui-security.md`: `src/web/auth.py`, `src/web/routes.py`, and `src/state/auth_store.py`.
- `browser-extension.md`: `extension/`, `scripts/build_extensions.py`, `src/web/api_routes.py`, and `src/web/account_auth.py`.
- `operations.md`: `start.py`, `docker-entrypoint.sh`, and the container files.

## Journal

- 2026-07-26: Consolidated stale root overviews into the architecture page and updated the module boundaries.
- 2026-08-18: Added `notifications.md` when Apprise notifications and their settings card were introduced.
- 2026-08-10: Removed point-in-time engineering records that described code no longer in the project.
- 2026-08-26: Added `browser-extension.md` with setup, API details, and the reason it cannot reuse the web login.
