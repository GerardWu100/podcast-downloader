# Web Guide

## Part 1: What belongs in `web/`

`web/` owns the browser interface:

```text
src.api:app
  -> app.create_app()
  -> routes.py
     -> auth.py request-security policy
     -> templates.py HTML and shared styles
     -> state stores for persistent changes
```

`create_app()` builds the application. Production calls it from `src/api.py`;
tests can provide validated configuration, temporary stores, and a scheduler
trigger. Missing values use production defaults. Route handlers read these
objects from the current request, so tests use the stores they provided.
`src/api.py` contains no route, authentication, or rendering code.

The signed-in interface has two pages:

- `/ui` is the queue. Use it to add a source, see what is monitored, and read logs.
- `/settings` contains one-time settings: YouTube cookie upload and Apprise notification settings.

Both cookie and notification forms return to `/settings`, not to the queue.

`APP_LAYOUT_STYLES`, `SETTINGS_FORM_STYLES`, and `THEME_SCRIPT` in
`templates.py` are shared by both pages. They are plain strings, not f-string
fragments, so their braces are not doubled. When inserted into an f-string,
each value is included unchanged.

Two endpoints handle Apprise error notifications:

- `POST /save-notifications` validates and stores the settings.
- `POST /test-notification` sends one message using the current form values, not the saved values, and returns JSON with the connection result.

Both endpoints require a session and a valid Cross-Site Request Forgery (CSRF)
token because they make the server send an outbound request.

`auth.py` handles proxy trust and browser security headers. `AuthStore` in
`state/` stores sessions and login failures. Route code owns the login flow and
CSRF tokens. Each application created by the factory has its own session and
token maps, so injected stores and separate application instances do not share
authentication state. Templates do not change queue or authentication state.

The Content Security Policy (CSP) blocks resource loading by default and allows
only the page's authorized script. Forwarded client headers are trusted only
when `trust_x_forwarded_for` is enabled.

The queue page polls `/logs`. An invalid session returns `401`, while page
routes redirect to `/login`. The page reloads when it sees `401`. If `/logs`
redirected, `fetch` would receive the login page's HTML and show it as log
lines.

## Part 2: Code reference

- `app.py`: `create_app()` and application dependencies.
- `routes.py`: FastAPI route handlers for login, queue, cookie upload, logs, help, and scheduler triggers.
- `auth.py`: `security_headers()`, `client_ip()`, and `request_is_secure()`.
- `templates.py`: shared CSS plus help, login, and authenticated queue-page renderers. Route code passes escaped values and security headers in.
- `__init__.py`: package marker.

## Part 3: Journal

- 2026-07-26: The deployment entrypoint became a factory call. Request-security policy, rendering, and authentication JSON each gained a clear owner.
- 2026-07-26: Route handlers began getting configuration, stores, and the scheduler trigger from the application factory instead of rebuilding production dependencies from module globals.
- 2026-08-10: `/logs` began returning `401` instead of redirecting when the session is invalid. The queue page reloads on that status, preventing expired sessions from filling the log box with escaped login-page HTML. The header also gained a one-line description of the app.
- 2026-08-10: Application instances stopped sharing session state. Cookie uploads became size-limited and are replaced atomically with owner-only access.
