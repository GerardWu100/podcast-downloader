# Web guide

## What belongs in `web/`

`web/` owns the browser interface and connects these pieces:

```text
src.api:app
  -> app.create_app()
  -> routes.py
     -> auth.py request-security policy
     -> templates.py HTML and shared styles
     -> state stores for persistent changes
```

`create_app()` builds the application. Production calls it from `src/api.py`.
Tests can provide validated configuration, temporary stores, and a scheduler
trigger; missing values use the production defaults. Route handlers read these
objects from the current request, so tests use the stores they provide.
`src/api.py` contains no routes, authentication, or rendering code.

The signed-in interface has two pages:

- `/` is the queue. Add a source, see what is monitored, and read the logs.
- `/settings` contains one-time settings for YouTube cookies and Apprise notifications.

Both forms return to `/settings`, not to the queue.

The queue lives at the site root, so the address someone types or bookmarks is
the page they want. There is no separate landing page. A browser without a
valid session is sent to `/login`; `/login` sends a browser that already has a
session back to `/`.

The title in the top left of both pages is a link to `/`.

The queue shows two timestamps under the add-source form: when the last
download finished and when the activity log last changed. The download time
comes from the newest `Downloaded:` event in recent `activity.log` lines. If a
run fails, the page keeps the last real download time instead of showing a
failure time as though a download had finished.

`APP_LAYOUT_STYLES` and `THEME_SCRIPT` in `templates.py` are shared by both
pages. `SETTINGS_FORM_STYLES` is used only by `/settings`. These constants are
plain strings, not f-string fragments, so their braces must not be doubled. An
f-string inserts each value unchanged. Put shared header controls, including
navigation links, in `APP_LAYOUT_STYLES` so both pages render them the same way.

These endpoints handle Apprise error notifications:

- `POST /save-notifications` validates and stores the settings.
- `POST /test-notification` sends one message using the current form values,
  not the saved values, and returns JSON with the connection result.

Both endpoints require a session and a valid Cross-Site Request Forgery (CSRF)
token because they make the server send an external request.

`auth.py` handles proxy trust and browser security headers. `AuthStore` in
`state/` stores sessions and login failures. Route code owns the login flow and
CSRF tokens. Each application created by the factory has its own session and
token maps, so injected stores and separate application instances do not share
authentication state. Templates never change queue or authentication state.

The Content Security Policy (CSP) blocks resource loading by default and allows
only the page's authorized script. The app trusts forwarded client headers only
when `trust_x_forwarded_for` is enabled.

The queue polls `/logs`. An invalid session returns `401`; page routes redirect
to `/login`. On `401`, the page reloads. If `/logs` redirected, `fetch` would
receive the login page's HTML and display it as log lines.

## Code reference

- `app.py`: `create_app()` and application dependencies.
- `routes.py`: FastAPI handlers for login, the queue, cookie upload, logs, help, and scheduler triggers.
- `auth.py`: `security_headers()`, `client_ip()`, and `request_is_secure()`.
- `templates.py`: shared CSS and renderers for the help, login, queue, and
  settings pages. Route code passes escaped values and security headers.
- `__init__.py`: package marker.

## Journal

- 2026-07-26: The deployment entry point became a factory call. Request-security
  policy, rendering, and authentication state each gained a clear owner.
- 2026-07-26: Route handlers began receiving configuration, stores, and the
  scheduler trigger from the application factory instead of rebuilding
  production dependencies from module globals.
- 2026-08-10: `/logs` began returning `401` instead of redirecting when the
  session is invalid. The queue reloads on that status, so an expired session
  cannot fill the log box with escaped login-page HTML. The header also gained
  a one-line app description.
- 2026-08-10: Application instances stopped sharing session state. Cookie
  uploads became size-limited and are replaced atomically with owner-only access.
- 2026-08-19: Queue and settings navigation styles moved into the shared
  signed-in layout after the new settings page rendered its links with browser
  defaults.
- 2026-08-26: The queue moved from `/ui` to `/`, replacing the redirecting
  landing route, and the header title became a link back to it.
