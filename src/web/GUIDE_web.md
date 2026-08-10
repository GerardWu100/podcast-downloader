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

`create_app()` is the construction seam. Production calls it from `src/api.py`;
tests can pass validated configuration, temporary store collaborators, and a
scheduler trigger. The factory resolves any omitted collaborators to production
defaults, then attaches the complete set to application state. Route handlers
resolve those collaborators from the current request's application state, so an
injected test store is also the store that the request actually uses.
`src/api.py` contains no route, authentication, or rendering implementation.

`auth.py` owns proxy-trust interpretation and browser security headers.
`AuthStore` in `state/` owns session and login-failure persistence. Route code
owns the login workflow and Cross-Site Request Forgery (CSRF) token lifecycle.
Templates do not mutate queue or authentication state.

The Content Security Policy (CSP) defaults to no resource loading and permits
only the page's nonce-authorized script. Forwarded client headers are trusted
only when `trust_x_forwarded_for` is enabled.

`/logs` is polled by the queue page rather than opened directly, so an invalid
session there answers `401` while every page route redirects to `/login`. The
page script reloads on that `401`. A redirect would instead be followed by
`fetch`, which would hand the script the login page's HTML to render as log
lines.

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
