# Web guide

## What this folder does

`web/` contains the browser interface. It handles login, page rendering, form
submissions, log updates, and browser security. The application factory
receives the configuration, persistent stores, and scheduler trigger. Production
and test runs use the same setup, while tests can provide temporary
dependencies.

It also serves the JSON API at `/api` that the Chrome extension in
`extension/` uses. Those routes authenticate with a bearer token instead of a
session cookie and never render HTML, so they live in their own module.

After signing in, the interface has two pages:

- `/` is the queue: add a source, see monitored sources, and read activity logs.
- `/settings` handles YouTube cookies and Apprise notifications.

Both forms return to `/settings`. The queue is the site root; there is no
separate landing page. A browser without a valid session goes to `/login`. A
signed-in browser that opens `/login` goes back to `/`.

The title in the top-left corner of both signed-in pages links to `/`.

The queue displays two times: the last successful download and the latest
activity-log change. It finds the download time from the newest `Downloaded:`
event in recent `activity.log` lines, so a failed run does not look complete.

The queue polls `/logs`. An expired session returns `401 Unauthorized`, and the
page reloads. Other page requests redirect to `/login`. Keeping `/logs` as a
`401` response matters: otherwise the browser would display the login page as
log text.

The app uses a Content Security Policy (CSP) to control where the browser can
load resources from. It trusts forwarded client IP headers only when
`trust_x_forwarded_for` is enabled.

A phone can install the interface as an app from its browser menu. Three pieces
are required:

- `static/manifest.json` names the app, sets its colors, and lists the Android icons. `static/apple-touch-icon.png` is the icon used by iOS.
- `static/service-worker.js`, served at `/sw.js`. Browsers offer to install a site only after a service worker is registered. This one caches nothing, so the queue and activity pages stay live and a redeploy is never hidden behind a stale copy.
- `manifest-src 'self'` and `worker-src 'self'` in the CSP. Without them, both fall back to `default-src 'none'`; the browser rejects the manifest and refuses to register the worker even though the server returns both correctly.

The static files and `/sw.js` are public. Browsers fetch a manifest without
sending the session cookie, so requiring a login would stop signed-in users
from installing the app.

## Code reference

- `app.py`: `create_app()` builds the application and its dependencies. Each application instance has its own session and Cross-Site Request Forgery (CSRF) token maps.
- `routes.py`: FastAPI handlers for login, the queue, cookie upload, logs, help, notifications, and scheduler triggers. It owns the login flow and CSRF tokens.
- `queue_actions.py`: `add_url_to_queue()`, the single place that decides what happens to a submitted URL — reject, normalize, refuse as a duplicate or as already downloaded, append, and wake the scheduler. Both `routes.add_url_form` and `api_routes.add_url` call it, so the browser form and the extension always behave the same.
- `api_routes.py`: `GET /api/ping` and `POST /api/add-url`. Clients send the same account name and password as the login form, in an `Authorization: Basic` header. No CSRF token is checked and none should be: CSRF protection exists because browsers attach cookies automatically, and a header a client fills in from its own settings is never automatic. No `WWW-Authenticate` header is returned either, so opening one of these URLs in a tab shows the JSON refusal instead of the browser's own grey sign-in box. No CORS headers are sent — a Manifest V3 extension with host permissions is exempt from CORS, and a normal cross-origin page still cannot call these routes.
- `account_auth.py`: `check_credentials()` plus the failed-attempt ban ledger, shared by the login form and the API. It owns the constant-time name comparison and the decoy password hash that make a wrong name cost the same time as a wrong password. Keeping one copy is the point: a second implementation for the API would be the one that quietly forgets the ban.
- `auth.py`: `security_headers()`, `client_ip()`, and `request_is_secure()` enforce browser security and proxy rules.
- `templates.py`: shared styles and renderers for the help, login, queue, and settings pages. Route code supplies escaped values and security headers. `HEAD_APP_TAGS` and `SERVICE_WORKER_SCRIPT` add install support to every page head and script block.
- `static/`: icons, the web manifest, and the service worker. These ship with the code, not in the mounted data directory. Regenerate the icons with `uv run --group dev python scripts/generate_app_icons.py` after changing the artwork; the PNG files are committed so the container needs no image library.
- `__init__.py`: package marker.

Notification endpoints:

- `POST /save-notifications` validates and stores the settings.
- `POST /test-notification` sends one message using the current form values, not the saved values, and returns JSON with the result.

Both endpoints require a signed-in session and a valid CSRF token because they
can contact an external notification service. `AuthStore` in `state/` stores
sessions and login failures. Templates only render pages; they do not change
queue or authentication state.

`APP_LAYOUT_STYLES` and `THEME_SCRIPT` in `templates.py` are shared by both
pages. `SETTINGS_FORM_STYLES` is used only by `/settings`. These are ordinary
strings, not f-string fragments, so do not double their braces. Put shared
header controls, including navigation links, in `APP_LAYOUT_STYLES` so both
pages stay consistent.

## Journal

- 2026-07-26: The deployment entry point became a factory call. Request-security policy, rendering, and authentication state each gained a clear owner.
- 2026-07-26: Route handlers began receiving configuration, stores, and the scheduler trigger from the application factory instead of rebuilding production dependencies from module globals.
- 2026-08-10: `/logs` began returning `401` instead of redirecting when the session is invalid. The queue reloads on that status, so an expired session cannot fill the log box with escaped login-page HTML. The header also gained a one-line app description.
- 2026-08-10: Application instances stopped sharing session state. Cookie uploads became size-limited and are replaced atomically with owner-only access.
- 2026-08-19: Queue and settings navigation styles moved into the shared signed-in layout after the new settings page rendered its links with browser defaults.
- 2026-08-26: The queue moved from `/ui` to `/`, replacing the redirecting landing route, and the header title became a link back to it.
- 2026-08-26: `/help` became the doc page. The links to it now read “Doc” rather than “How it works” or “Help”, and it gained a command reference. An agent driving this project has no browser session, so the page it is pointed at has to carry the commands or it falls back to guessing flags.
- 2026-08-26: The interface became installable as a phone app. The blocker was not the missing manifest but the CSP: `default-src 'none'` with no `manifest-src` or `worker-src` silently rejected both files, so the browser never offered to install a site that was serving everything correctly.
- 2026-08-26: The signed-in pages and the help page stopped capping their content at a pixel width. Zooming out with Ctrl-minus grew the window but left the column at the same 900 CSS pixels, so the page shrank into the middle of an increasingly empty screen. The cap is gone; the side margin is now `clamp(0.75rem, 4vw, 3.2rem)`, which grows with the window.
- 2026-08-26: `/api` arrived for the Chrome extension. The add-a-URL rules moved out of `add_url_form` into `queue_actions.py`, and the account check and ban ledger moved out of `routes.py` into `account_auth.py`, so the form and the API share both. Authentication could not be the browser session: that cookie is `HttpOnly`, so no extension script can read it, and `SameSite=lax`, so the browser would not send it on a cross-site POST even if one could. It is the same username and password instead, sent in a header, which needs nothing configured on the server.
