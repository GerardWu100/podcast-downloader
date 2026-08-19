# Web Guide

## Part 1: Web Boundary

`web/` owns the browser interface:

```text
src.api:app
  -> app.create_app()
  -> routes.py
     -> auth.py request-security policy
     -> templates.py HTML and shared styles
     -> state stores for durable mutations
```

`create_app()` builds the application. Production calls it from `src/api.py`; tests can pass validated configuration, temporary stores, and a scheduler trigger. Missing values use production defaults. Route handlers read the objects from the current request, so tests use the stores they supplied. `src/api.py` contains no route, authentication, or rendering code.

Two endpoints handle Apprise error notifications. `POST /save-notifications` validates and stores the settings. `POST /test-notification` sends one message using the current form values rather than the saved ones and returns JSON with the connection result. Both require a session and a valid CSRF token because either endpoint makes the server send an outbound request.

`auth.py` interprets proxy trust and builds browser security headers. `AuthStore` in `state/` saves sessions and login failures. Route code owns the login flow and Cross-Site Request Forgery (CSRF) tokens. Each factory-created application owns its own session and token maps, so injected stores and separate application instances do not share authentication state.
Templates do not mutate queue or authentication state.

The Content Security Policy (CSP) blocks resource loading by default and allows only the page's nonce-authorized script. Forwarded client headers are trusted only when `trust_x_forwarded_for` is enabled.

The queue page polls `/logs`. An invalid session gets `401`, while page routes redirect to `/login`. The page reloads when it sees `401`; if the endpoint redirected, `fetch` would hand the script the login page's HTML, which would appear as log lines.

## Part 2: Code Reference

- `app.py`: `create_app()` and collaborator wiring.
- `routes.py`: FastAPI route handlers for login, queue, cookie upload, logs,
  help, and scheduler triggers.
- `auth.py`: `security_headers()`, `client_ip()`, `request_is_secure()`.
- `templates.py`: shared CSS plus help, login, and authenticated queue-page
  renderers. Route code passes escaped values and security headers in.
- `__init__.py`: package marker.

## Part 3: Journal

- 2026-07-26: The deployment entrypoint became a factory call, request-security
  policy and rendering gained explicit owners, and authentication JSON moved to
  `AuthStore`.
- 2026-07-26: Route handlers began resolving configuration, stores, and the
  scheduler trigger through the application factory instead of reconstructing
  production collaborators from module globals.
- 2026-08-10: `/logs` began answering `401` instead of redirecting when the
  session is invalid, and the queue page reloads on that status. The redirect
  was being followed by `fetch`, so an expired session filled the log box with
  the escaped HTML of the login page. The header also carries a one-line
  description of what the app does.
- 2026-08-10: Application instances stopped sharing session state; cookie
  uploads became bounded and atomically replaced with owner-only access.
