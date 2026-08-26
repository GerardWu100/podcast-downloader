# Extension guide

## Purpose

This folder contains a Chrome extension that sends the current page or a link
to the download queue. It is a client of the server, not part of the server:
`.dockerignore` leaves it out of the Docker image, and code in `src/` does not
import it.

User setup is in [`docs/browser-extension.md`](../docs/browser-extension.md).

## Request flow

```text
toolbar click / Alt+Shift+D / context menu
  -> background.js reads settings and calls /api/add-url
  -> src/web/token_api.py checks the bearer token
  -> src/web/queue_actions.py applies the normal queue rules
  -> urls.txt is updated; immediate direct downloads wake the scheduler
  -> the result updates the badge and, on failure, a notification
```

`queue_actions.py` is also used by the web form. Both entry points therefore
share URL validation, normalization, duplicate handling, and immediate-download
rules.

## Files

- `manifest.json`: Manifest V3 declaration and narrow permissions. `activeTab`
  reveals a tab URL only when the user invokes the extension. The options page
  requests access to the single server origin entered by the user.
- `background.js`: service worker for context menus, shortcuts, API calls,
  badges, and error notifications. It re-reads settings for every submission
  because Chrome may stop the worker at any time.
- `settings.js`: reads and writes `chrome.storage.local` and converts the
  server address into a URL and permission pattern. The worker and options page
  use the same conversion.
- `options.html`, `options.css`, and `options.js`: settings page. Saving asks
  Chrome for the server permission because Chrome allows that request only in
  response to a user click.
- `icons/`: generated from `src/web/static/icon-512.png`.

## Decisions

- Store the token in `chrome.storage.local`, not `sync`, so it is not copied to
  every Chrome profile using the same Google account.
- Treat a bare hostname as `https`; users must type `http://` when they accept
  the risk of sending the token without encryption.
- Treat `duplicate` and `downloaded` as successful outcomes because the item is
  already handled.
- Do not send a CSRF token. The API uses a deliberate bearer header rather than
  an automatically attached browser cookie.
- Accept that a badge can remain briefly if Chrome stops the worker before its
  clear timer runs. The next submission replaces it.

## Testing

There are no automated extension tests. The server API is covered by
`tests/test_token_api.py`. For a manual check, load the folder unpacked, use
**Test connection**, submit a real video, and confirm the entry appears in
`urls.txt`.

