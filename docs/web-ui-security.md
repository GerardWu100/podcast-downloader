---
title: Web UI and Security
sidebar_position: 4
---

# Web UI and Security

## Login model

The web UI is intentionally simple:

- Password is read from `.ui_password`.
- In Docker, `.ui_password` stores a PBKDF2-HMAC-SHA256 hash instead of the clear-text password.
- The default first-boot password is `.ui_password`.
- Legacy `CHANGE_ME` files are migrated automatically and are still treated as invalid if they somehow reach the API unchanged.
- Failed attempts are recorded in `.login_state.json`.
- After too many failures from the same IP, the client is temporarily banned.
- Successful login creates a persistent session cookie stored in `.ui_sessions.json`.

## Manual password setup

To generate the stored password hash manually from the terminal and write it into `.ui_password`, run:

```bash
uv run python -c 'from src.passwords import hash_password; import getpass; print(hash_password(getpass.getpass("Password: ")))' > .ui_password
```

Workflow:

1. Run the command.
2. Type the real password at the `Password:` prompt.
3. Press Enter.
4. The command writes only the PBKDF2 hash to `.ui_password`.

That means the true password is entered interactively and the file on disk stores only the hash.

If you prefer, in Docker you can place a plain-text password in `.ui_password` and restart the container once. The entrypoint will convert it to the hashed format automatically.

If `.ui_password` already exists in the repo when you build the Docker image, first boot copies that file into the mounted data directory automatically. That means the server-side flow can be:

1. Create `.ui_password` locally.
2. Copy the project, including the hidden `.ui_password` file, to the server.
3. Run `docker compose up -d`.

No extra password-generation step is required on the server.

## Session rules

- Session lifetime is 30 days.
- Sessions are restored from `.ui_sessions.json` after a FastAPI restart and remain valid until they expire.
- The session file stores the session id and creation timestamp only; it is not tied to the login IP.
- A browser that reopens `/` or `/login` with a valid session cookie is redirected to `/ui` instead of seeing the password form again.

## CSRF protection

Two CSRF mechanisms are used:

- The login form gets a one-time anonymous CSRF token with a 10-minute time to live.
- The authenticated queue form gets a per-session CSRF token.

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

Failed login attempts now redirect back to the HTML login form with an inline error message such as `Invalid password.` instead of returning a raw JSON error response.

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
- Password authentication is single-factor.
- The queue UI trusts any logged-in user with full append access.
