# Web guide

## What this folder does

`web/` contains the browser interface. It handles login, page rendering, form
submissions, log updates, and browser security. It uses the application factory
to receive configuration, persistent state stores, and the scheduler trigger.
This keeps production setup and tests on the same path while letting tests
provide temporary dependencies.

The signed-in interface has two pages:

- `/` is the queue: add a source, see monitored sources, and read activity logs.
- `/settings` handles YouTube cookies and Apprise notifications.

Both forms return to `/settings`. The queue is the site root, with no separate
landing page. A browser without a valid session goes to `/login`; a browser
with a valid session that opens `/login` goes back to `/`.

The title in the top-left corner of both signed-in pages links to `/`.

The queue displays two times: the last successful download and the latest
activity-log change. It finds the download time from the newest `Downloaded:`
event in recent `activity.log` lines. A failed run therefore does not look like
a completed download.

The queue polls `/logs`. An expired session gets `401 Unauthorized`, and the
page reloads. Page requests redirect to `/login`. Keeping the log request as a
`401` response matters: otherwise the browser would receive the login page's
HTML and show it as log text.

The app uses a Content Security Policy (CSP), which limits where the browser
can load resources from. Forwarded client IP headers are trusted only when
`trust_x_forwarded_for` is enabled.

## Code reference

- `app.py`: `create_app()` builds the application and its dependencies. Each
  application instance has its own session and Cross-Site Request Forgery
  (CSRF) token maps.
- `routes.py`: FastAPI handlers for login, the queue, cookie upload, logs, help,
  notifications, and scheduler triggers. It owns the login flow and CSRF tokens.
- `auth.py`: `security_headers()`, `client_ip()`, and `request_is_secure()`
  enforce browser security and proxy rules.
- `templates.py`: shared styles and renderers for the help, login, queue, and
  settings pages. Route code supplies escaped values and security headers.
- `__init__.py`: package marker.

The notification endpoints are:

- `POST /save-notifications` validates and stores the settings.
- `POST /test-notification` sends one message using the current form values,
  not the saved values, and returns JSON with the result.

Both endpoints require a signed-in session and a valid CSRF token because they
can send a request to an external notification service. `AuthStore` in
`state/` stores sessions and login failures. Templates only render pages; they
do not change queue or authentication state.

`APP_LAYOUT_STYLES` and `THEME_SCRIPT` in `templates.py` are shared by both
pages. `SETTINGS_FORM_STYLES` is used only by `/settings`. These are ordinary
strings, not f-string fragments, so their braces must not be doubled. Shared
header controls, including navigation links, belong in `APP_LAYOUT_STYLES` so
both pages stay consistent.

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
- 2026-08-26: The signed-in pages and the help page stopped capping their
  content at a pixel width. Zooming out with Ctrl+minus grew the window but
  left the column at the same 900 CSS pixels, so the page shrank into the
  middle of an increasingly empty screen. The cap is gone; the side margin is
  now `clamp(0.75rem, 4vw, 3.2rem)`, which grows with the window.
