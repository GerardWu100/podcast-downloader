# Extension guide

## Purpose

This folder contains the browser client for adding pages and links to the
download queue. It runs in Chrome and Firefox and is separate from the server.
The Docker image excludes it, and the server does not import it.

User setup is in [`docs/browser-extension.md`](../docs/browser-extension.md).

## Request flow

```text
toolbar click / Alt+Shift+D / context menu
  -> background.js reads settings and calls /api/add-url
  -> src/web/api_routes.py checks the username and password (account_auth.py)
  -> src/web/queue_actions.py applies the normal queue rules
  -> urls.txt is updated; immediate direct downloads wake the scheduler
  -> the result updates the badge and, on failure, a notification
```

The web form uses the same queue actions. Both entry points therefore share URL
validation, normalization, duplicate handling, and immediate-download rules.

## Files

- `manifest.json`: Manifest V3 declaration and narrow permissions. `activeTab`
  reveals a tab URL only when the user invokes the extension. The options page
  requests access only to the server origin entered by the user.
- `background.js`: service worker for context menus, shortcuts, API calls,
  badges, and error notifications. It re-reads settings for every submission
  because Chrome may stop the worker at any time. `MENU_SITE_PATTERNS` controls
  where the right-click items appear.
- `settings.js`: reads and writes `chrome.storage.local` and converts the
  server address into a URL and permission pattern. The worker and options
  page use the same conversion.
- `options.html`, `options.css`, and `options.js`: settings page. Saving asks
  the browser for server permission after the user clicks **Save**.
- `manifest.firefox.json`: the Firefox manifest. Firefox has no extension
  service worker, so it runs `background.js` as an event page; it also needs a
  stable add-on id and reads `options_ui` rather than `options_page`. Every
  other file is shared, so the Firefox-specific differences stay in this
  manifest instead of a second folder.
- `icons/`: generated from `src/web/static/icon-512.png`.

`scripts/build_firefox_extension.py` assembles the Firefox build into
`build/firefox-extension/` and, with `--zip`, the archive that
addons.mozilla.org signs. Chrome loads `extension/` directly and needs no
build step. `tests/test_build_firefox_extension.py` checks that the two
manifests agree on the version and permissions, and that the build contains
every shared file and no stale files.

## Decisions

- Use the same account as the web page, so the server needs no extra secret.
  The trade-off is that the password sits in extension storage, and revoking
  it means changing the web password.
- Store settings in `chrome.storage.local`, not `sync`, so the password is not
  copied to every Chrome profile using the same Google account.
- Treat a bare hostname as `https`. Users must type `http://` when they accept
  the risk of sending the password without encryption.
- Build the `Authorization` header from UTF-8 bytes before base64 encoding.
  `btoa` alone throws for an accented character in a password.
- Treat `duplicate` and `downloaded` as successful outcomes because the item
  is already handled.
- Limit the right-click items to YouTube and Rumble so they do not appear in
  every menu. The page item uses `documentUrlPatterns`; the link item uses
  `targetUrlPatterns`, so a YouTube link found on another site still offers the
  menu. The toolbar icon and shortcut stay unfiltered because they are explicit
  actions, and the server rejects unusable URLs. To add a site, edit
  `MENU_SITE_PATTERNS` and reload the extension.
- Do not send a CSRF token. Cross-Site Request Forgery (CSRF) protection is
  needed because browsers attach cookies automatically; a header the client
  fills from its own settings is never automatic.
- Accept that a badge can remain briefly if Chrome stops the worker before its
  clear timer runs. The next submission replaces it.

## Testing

There are no automated extension tests. The server API is covered by
`tests/test_api_routes.py`. For a manual check, load the folder unpacked, use
**Test connection**, submit a real video, and confirm that the entry appears in
`urls.txt`.
