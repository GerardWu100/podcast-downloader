# Web guide

## What this folder does

`web/` contains the browser interface. It handles login, page rendering, form
submissions, log updates, and browser security. The application factory
receives the configuration, persistent stores, and scheduler trigger. Tests use
the same setup as production but can provide temporary dependencies.

It also serves the JSON API at `/api` used by the browser extension in
`extension/`. Those routes use HTTP Basic credentials instead of a session
cookie and return JSON, so they live in their own module.

After signing in, the interface has two pages:

- `/` is the queue: add a source, see monitored sources, and read activity logs.
- `/settings` handles YouTube cookies and Apprise notifications.

Both forms return to `/settings`. The queue is the site root; there is no
separate landing page. A browser without a valid session goes to `/login`. A
signed-in browser that opens `/login` goes back to `/`.

The title in the top-left corner of both signed-in pages links to `/`.

The queue displays two times: the last successful download and the latest
activity-log change. It takes the download time from the newest `Downloaded:`
event in recent `activity.log` lines, so a failed run does not look complete.

The queue polls `/logs`. An expired session returns `401 Unauthorized`, and the
page reloads. Other page requests redirect to `/login`. Keeping `/logs` as a
`401` response matters: otherwise the browser would display the login page as
log text.

The app uses a Content Security Policy (CSP) to control where the browser can
load resources from. It trusts forwarded client-IP headers only when
`trust_x_forwarded_for` is enabled.

A phone can install the interface as an app from its browser menu. Three pieces
make that possible:

- `static/manifest.json` names the app, sets its colors, and lists the Android icons. `static/apple-touch-icon.png` is the icon used by iOS.
- `static/service-worker.js`, served at `/sw.js`. Browsers offer to install a site only after a service worker is registered. This one caches nothing, so the queue and activity pages stay live after a redeploy.
- `manifest-src 'self'` and `worker-src 'self'` in the CSP. Without them, both fall back to `default-src 'none'`; the browser rejects the manifest and refuses to register the worker even though the server returns both files.

The static files and `/sw.js` are public. Browsers fetch a manifest without
sending the session cookie, so requiring a login would stop signed-in users
from installing the app.

## Code reference

- `app.py`: `create_app()` builds the application and its dependencies. Each application instance has its own session and Cross-Site Request Forgery (CSRF) token maps.
- `routes.py`: FastAPI handlers for login, the queue, cookie upload, logs, help, notifications, and scheduler triggers. It owns the login flow and CSRF tokens. `POST /run-now` starts the same whole-queue pass the schedule runs; it is refused while one is already going, so two passes cannot fight over the same state files.
- `queue_actions.py`: `add_url_to_queue()`, the single place that decides what happens to a submitted URL — reject, normalize, refuse as a duplicate or as already downloaded, append, and wake the scheduler. Both `routes.add_url_form` and `api_routes.add_url` call it, so the browser form and the extension always behave the same.
- `api_routes.py`: `GET /api/ping`, `GET /api/health`, and `POST /api/add-url`. `/api/health` answers 503 once the scheduled run is more than three hours late, so an uptime monitor can alert on the status code alone. It exists because nothing inside a dead container can report that it is dead, and `/api/ping` stays cheerful while the web server answers and the scheduler behind it is gone. Clients send the same account name and password as the login form in an `Authorization: Basic` header. These routes do not check a CSRF token: CSRF protection is for credentials that browsers attach automatically, while this header comes from the client's own settings. They also omit `WWW-Authenticate`, so a browser tab shows the JSON refusal instead of its own sign-in box. No CORS headers are sent. A Manifest V3 extension with host permissions can call the routes, while an ordinary cross-origin page cannot.
- `app.py` rejects an undeclared or oversized `/api/add-url` body before
  FastAPI buffers JSON or verifies a password. The route then applies the
  smaller URL-field limit during normal validation.
- `account_auth.py`: `check_credentials()` plus the failed-attempt ban ledger, shared by the login form and the API. It owns the constant-time name comparison and decoy password hash, so an unknown name takes about as long to reject as a wrong password. Keeping one implementation ensures both entry points apply the ban.
- `auth.py`: `security_headers()`, `client_ip()`, and `request_is_secure()` enforce browser security and proxy rules.
- `templates.py`: shared styles and renderers for the help, login, queue, and settings pages. `LOG_PANEL_STYLES` and `ACTIVITY_LOG_SCRIPT` hold the activity panel's styles and browser code as ordinary strings, so their braces and regular expressions are written once rather than doubled for an f-string. Route code supplies escaped values and security headers. `HEAD_APP_TAGS` and `SERVICE_WORKER_SCRIPT` add install support to each page.
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

- 2026-09-01: Added `GET /api/health` for an external monitor.
- 2026-09-01: The activity panel was rewritten to be read rather than scrolled: entries are grouped under day headings, each run is bracketed by its start and finish line, badges name the event, URLs became links, counts sit beside the picker, and a "Problems only" filter hides what worked. The browser code moved out of the page f-string into `ACTIVITY_LOG_SCRIPT`, because escaping every brace of a regular expression twice is how the old version stayed small.
- 2026-09-01: The settings page reports the cookie file in use and when its sign-in expires. The date was always in the file; nothing surfaced it, so the first sign of an expired cookie was a run of failed downloads.
- 2026-09-01: The status line under the add-source form now answers three questions instead of one: what was downloaded last, when the queue last ran and how long ago, and when the next run is due. The next-run time comes from the calendar rule in `src/schedule.py`, so the page can show it whether or not a scheduler thread is running in this process.
- 2026-07-26: The deployment entry point became a factory call. Request-security policy, rendering, and authentication state each gained a clear owner.
- 2026-07-26: Route handlers began receiving configuration, stores, and the scheduler trigger from the application factory instead of rebuilding production dependencies from module globals.
- 2026-08-10: `/logs` began returning `401` instead of redirecting when the session is invalid. The queue reloads on that status, so an expired session cannot fill the log box with escaped login-page HTML. The header also gained a one-line app description.
- 2026-08-10: Application instances stopped sharing session state. Cookie uploads became size-limited and are replaced atomically with owner-only access.
- 2026-08-19: Queue and settings navigation styles moved into the shared signed-in layout after the new settings page rendered its links with browser defaults.
- 2026-08-26: The queue moved from `/ui` to `/`, replacing the redirecting landing route, and the header title became a link back to it.
- 2026-08-26: `/help` became the doc page. The links to it now read “Doc” rather than “How it works” or “Help”, and it gained a command reference. An agent driving this project has no browser session, so the page it is pointed at has to carry the commands or it falls back to guessing flags.
- 2026-08-26: The interface became installable as a phone app. The blocker was not the missing manifest but the CSP: `default-src 'none'` with no `manifest-src` or `worker-src` silently rejected both files, so the browser never offered to install a site that was serving everything correctly.
- 2026-08-26: The signed-in pages and the help page stopped capping their content at a pixel width. Zooming out with Ctrl-minus grew the window but left the column at the same 900 CSS pixels, so the page shrank into the middle of an increasingly empty screen. The cap is gone; the side margin is now `clamp(0.75rem, 4vw, 3.2rem)`, which grows with the window.
- 2026-08-26: Added `/api` for the Chrome extension. The form and API now share URL handling in `queue_actions.py` and account checks in `account_auth.py`. The API uses the same username and password in a header because the browser session cookie is `HttpOnly` and `SameSite=lax`.
- 2026-08-27: Bounded API bodies before JSON parsing, stopped logging submitted
  URLs, and rejected account names containing the HTTP Basic separator.
