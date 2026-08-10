---
title: Web UI and Security
sidebar_position: 4
---

# Web UI and Security

The short `/help` page is public and contains only usage guidance and a link to
the official `yt-dlp` cookie instructions. The queue, logs, cookie uploads, and
all controls that change data require a signed-in session.

## Login model

The web UI is intentionally simple:

- The operator sets `UI_USERNAME` and `UI_PASSWORD` in `.env` in the data directory (copy `.env.example` to start).
- Up to three accounts are allowed. The second and third use `UI_USERNAME_2` with `UI_PASSWORD_2` and `UI_USERNAME_3` with `UI_PASSWORD_3`. Every account reaches the same pages, so the accounts separate people, not permissions.
- On every startup the app hashes each `UI_PASSWORD` with PBKDF2-HMAC-SHA256, checks each hash against its password, and stores the account names plus their hashes in `.ui_credentials.json`. Login reads only the hash file.
- The login form asks for both the username and the password.
- Failed attempts are recorded in `.login_state.json`.
- After too many failures from the same IP, the client is temporarily banned.
- Successful login creates a persistent session cookie stored in `.ui_sessions.json`.
- Both JSON files use process-safe locks and owner-only (`600`) temporary files, then replace the old file in one step.

## Credential setup

1. Copy `.env.example` to `.env`.
2. Set `UI_USERNAME` and `UI_PASSWORD`, and optionally the numbered slots for a second and third account.
3. Start the app (or restart the container). Startup hashes each password, self-tests the hashes, and logs the result.

Rules startup applies to the account slots:

- A slot with both values set becomes an account; a blank slot is skipped, and slots need not be filled in order.
- A slot with only one of the two values set is ignored and logged as a warning, because half an account cannot log in.
- Two slots may not share an account name; the later one is ignored and logged, because it could never be reached.
- A wrong account name costs the same time as a wrong password, because one password hash is always checked.

To change a password later, edit `.env` and restart. The hash is regenerated and re-verified automatically. There is no manual hashing command.
Changing, adding, or removing any account revokes remembered sessions. If `.env` is removed or
becomes invalid, startup removes stale hashed credentials and sessions so the
old password cannot remain active.

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

## Protection against unwanted form submissions

The app uses two Cross-Site Request Forgery (CSRF) protections. CSRF is when a
different site tricks a signed-in browser into submitting a form.

- The login form gets a one-time token that expires after 10 minutes.
- Authenticated state-changing forms, including queue edits, logout, and cookie upload, get a per-session CSRF token.

Both checks use `secrets.compare_digest` to avoid leaking timing information.

## Browser hardening

HTML responses include:

- `Cache-Control: no-store`
- `Pragma: no-cache`
- `Referrer-Policy: same-origin`
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- A strict Content Security Policy

The queue UI uses a new script nonce for each response instead of inline event
handlers. The activity viewer therefore works without allowing arbitrary inline
JavaScript.

Failed login attempts redirect back to the HTML login form with an inline error message such as `Invalid username or password.` instead of returning a raw JSON error response. Wrong usernames and wrong passwords produce the same message and take the same time to check, so responses do not reveal which half was wrong.

## Proxy trust

The checked-in `config.ini` sets:

```ini
trust_x_forwarded_for = true
```

This is safe only when the app is behind a reverse proxy you control, such as
Cloudflare Tunnel, and that proxy rewrites client IP headers correctly.

When that setting is on, the app also honors `X-Forwarded-Proto` and Cloudflare's `CF-Visitor` scheme hint so the session cookie can be marked `Secure` behind HTTPS.

If you expose the app directly, set it to `false`. Otherwise clients can spoof `X-Forwarded-For` and interfere with ban logic.

## Residual limits

- This is still a personal-use admin surface, not a full internet-facing multi-user application.
- Sessions are persisted across restarts, but they still expire after 30 days and remain single-user in scope.
- Authentication is a single account with a username and password, no second factor.
- The plain password lives in `.env` on disk. This is a deliberate convenience trade-off; file permissions (600) and a private data directory are the protection.
- The queue UI trusts any logged-in user with full queue and cookie-file update access.
