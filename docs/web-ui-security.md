---
title: Web UI and Security
sidebar_position: 4
---

# Web UI and Security

The short `/help` page is public. It contains usage guidance and a link to the
official `yt-dlp` cookie instructions. The queue, logs, cookie uploads, and
every control that changes data require a signed-in session.

## Login model

The web UI uses a simple login model:

- The operator sets `UI_USERNAME` and `UI_PASSWORD` in `.env` in the data directory (copy `.env.example` to start).
- Up to three accounts are allowed. The second and third use `UI_USERNAME_2` with `UI_PASSWORD_2` and `UI_USERNAME_3` with `UI_PASSWORD_3`. Every account reaches the same pages, so the accounts separate people, not permissions.
- On startup, the app hashes each `UI_PASSWORD` with PBKDF2-HMAC-SHA256 and stores the account names and hashes in `.ui_credentials.json`. Login reads only that hash file.
- The login form asks for both the username and the password.
- Failed attempts are recorded in `.login_state.json`.
- After too many failures from the same IP address, the client is temporarily banned.
- Successful login creates a persistent session cookie stored in `.ui_sessions.json`.
- Both JSON files use process-safe locks and owner-only (`600`) temporary files. The app then replaces the old file in one step.

## Credential setup

1. Copy `.env.example` to `.env`.
2. Set `UI_USERNAME` and `UI_PASSWORD`, and optionally the numbered slots for a second and third account.
3. Start the app, or restart the container. Startup hashes each password, checks the hashes, and logs the result.

At startup, the app applies these rules to the account slots:

- A slot with both values set becomes an account; a blank slot is skipped, and slots need not be filled in order.
- A slot with only one of the two values set is ignored and logged as a warning, because half an account cannot log in.
- Two slots may not share an account name; the later one is ignored and logged, because it could never be reached.
- A wrong account name takes the same time as a wrong password, because the app always checks one password hash.

To change a password, edit `.env` and restart. The app regenerates and checks
the hash automatically; no manual hashing command is needed. Changing, adding,
or removing an account revokes remembered sessions. If `.env` is missing or
invalid, startup removes stale credentials and sessions so the old password
cannot remain active.

If `.env` already exists in the repository when you build the Docker image, the
first boot copies it into the mounted data directory. The server-side flow is:

1. Create `.env` locally.
2. Copy the project, including the hidden `.env` file, to the server.
3. Run `docker compose up -d`.

Both `.env` and `.ui_credentials.json` use owner-only (`600`) permissions.
The plain password still lives in `.env`; the hash protects the login check,
but anyone who can read the data directory can read `.env`. Keep that
directory private.

## Session rules

- Sessions last 30 days.
- Sessions are restored from `.ui_sessions.json` after a FastAPI restart and remain valid until they expire.
- The session file stores only the session ID and creation timestamp; it is not tied to the login IP.
- `/` is the queue itself. Opening it without a valid session cookie redirects to `/login`; opening `/login` with one redirects back to `/`, so a signed-in reader never sees the password form again.

## Protection against unwanted form submissions

The app uses two Cross-Site Request Forgery (CSRF) protections. CSRF is an
attack in which another site tricks a signed-in browser into submitting a form.

- The login form gets a one-time token that expires after 10 minutes.
- Authenticated state-changing forms, including queue edits, logout, and cookie upload, get a per-session CSRF token.

Both checks use `secrets.compare_digest` to reduce timing leaks.

## Browser hardening

HTML responses include these protections:

- `Cache-Control: no-store`
- `Pragma: no-cache`
- `Referrer-Policy: same-origin`
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- A strict Content Security Policy

The queue UI uses a new script nonce for each response instead of inline event
handlers. The activity viewer can therefore work without allowing arbitrary
inline JavaScript.

The policy also sets `manifest-src 'self'` and `worker-src 'self'`. These allow
the web manifest and service worker needed to install the interface as a phone
app. Without them, both fall back to `default-src 'none'`: the files are
served, but the browser rejects them and installation fails without a visible
error.

Failed login attempts return to the HTML login form with a message such as
`Invalid username or password.` rather than a raw JSON error. Wrong usernames
and wrong passwords produce the same message and take the same time to check,
so the response does not reveal which part was wrong.

## Proxy trust

The checked-in `config.ini` sets:

```ini
trust_x_forwarded_for = true
```

Use this only when the app is behind a reverse proxy you control, such as
Cloudflare Tunnel, and that proxy rewrites client-IP headers correctly.

When that setting is on, the app also honors `X-Forwarded-Proto` and Cloudflare's `CF-Visitor` scheme hint so the session cookie can be marked `Secure` behind HTTPS.

If you expose the app directly, set it to `false`. Otherwise clients can fake
`X-Forwarded-For` and interfere with the ban logic.

## Residual limits

- This is a personal-use admin interface, not a full internet-facing multi-user application.
- Sessions persist across restarts, but still expire after 30 days and give every signed-in user the same access.
- Authentication uses a username and password, with no second factor.
- The plain password lives in `.env` on disk. This is a deliberate convenience trade-off; file permissions (600) and a private data directory are the protection.
- Any logged-in user has full queue and cookie-file update access.
