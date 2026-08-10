---
title: Web UI and Security
sidebar_position: 4
---

# Web UI and Security

The short `/help` page is public and contains only static usage guidance and a
link to the official `yt-dlp` cookie instructions. Queue contents, logs, cookie
uploads, and all state-changing controls remain behind the authenticated UI.

## Login model

The web UI is intentionally simple:

- The operator sets `UI_USERNAME` and `UI_PASSWORD` in `.env` in the data directory (copy `.env.example` to start).
- On every startup the app hashes `UI_PASSWORD` with PBKDF2-HMAC-SHA256, verifies the hash against the plain password (a self-test), and stores the account name plus the hash in `.ui_credentials.json`. The login check reads only the hash file.
- The login form asks for both the username and the password.
- Failed attempts are recorded in `.login_state.json`.
- After too many failures from the same IP, the client is temporarily banned.
- Successful login creates a persistent session cookie stored in `.ui_sessions.json`.
- Both JSON state files use interprocess locks and sibling temporary files followed by atomic replacement.

## Credential setup

1. Copy `.env.example` to `.env`.
2. Set `UI_USERNAME` and `UI_PASSWORD`.
3. Start the app (or restart the container). Startup hashes the password, self-tests the hash, and logs the result.

To change the password later, edit `.env` and restart. The hash is regenerated and re-verified automatically. There is no manual hashing command.

If `.env` already exists in the repo when you build the Docker image, first boot copies that file into the mounted data directory automatically. That means the server-side flow can be:

1. Create `.env` locally.
2. Copy the project, including the hidden `.env` file, to the server.
3. Run `docker compose up -d`.

Both `.env` and `.ui_credentials.json` are written with owner-only (600) file permissions. Note that `.env` keeps the plain password on disk; the hash in `.ui_credentials.json` protects the login check itself, but anyone who can read the data directory can read `.env`. Keep the data directory private.

## Session rules

- Session lifetime is 30 days.
- Sessions are restored from `.ui_sessions.json` after a FastAPI restart and remain valid until they expire.
- The session file stores the session id and creation timestamp only; it is not tied to the login IP.
- A browser that reopens `/` or `/login` with a valid session cookie is redirected to `/ui` instead of seeing the password form again.

## CSRF protection

Two CSRF mechanisms are used:

- The login form gets a one-time anonymous CSRF token with a 10-minute time to live.
- Authenticated state-changing forms, including queue edits, logout, and cookie upload, get a per-session CSRF token.

Both checks use `secrets.compare_digest` for constant-time comparison.

## Browser hardening

HTML responses include:

- `Cache-Control: no-store`
- `Pragma: no-cache`
- `Referrer-Policy: same-origin`
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- A strict Content Security Policy

The queue UI now uses a per-response script nonce instead of inline event handlers. This keeps the activity viewer working without weakening the Content Security Policy to allow arbitrary inline JavaScript.

Failed login attempts redirect back to the HTML login form with an inline error message such as `Invalid username or password.` instead of returning a raw JSON error response. Wrong usernames and wrong passwords produce the same message and take the same time to check, so responses do not reveal which half was wrong.

## Proxy trust

The checked-in `config.ini` sets:

```ini
trust_x_forwarded_for = true
```

That is only safe when the app is behind a reverse proxy you control, such as Cloudflare Tunnel or another proxy that rewrites client IP headers correctly.

When that setting is on, the app also honors `X-Forwarded-Proto` and Cloudflare's `CF-Visitor` scheme hint so the session cookie can be marked `Secure` behind HTTPS.

If you expose the app directly, set it to `false`. Otherwise clients can spoof `X-Forwarded-For` and interfere with ban logic.

## Residual limits

- This is still a personal-use admin surface, not a full internet-facing multi-user application.
- Sessions are persisted across restarts, but they still expire after 30 days and remain single-user in scope.
- Authentication is a single account with a username and password, no second factor.
- The plain password lives in `.env` on disk. This is a deliberate convenience trade-off; file permissions (600) and a private data directory are the protection.
- The queue UI trusts any logged-in user with full queue and cookie-file update access.
