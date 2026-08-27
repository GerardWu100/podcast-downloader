# Extension guide

## Purpose

This folder contains the browser client for adding pages and links to the
download queue. It runs in Chrome and Firefox, separately from the server. The
Docker image excludes it, and the server does not import it.

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
  requests access only to the server address entered by the user.
- `background.js`: background worker for context menus, shortcuts, API calls,
  badges, and error notifications. Chrome runs it as a service worker; Firefox
  runs it as a non-persistent background page. It re-reads settings for every
  submission because the browser may stop it at any time.
  `MENU_SITE_PATTERNS` controls where the right-click items appear.
- `settings.js`: reads and writes `chrome.storage.local` and converts the
  server address into a URL and permission pattern. The worker and options
  page use the same conversion.
- `options.html`, `options.css`, and `options.js`: settings page. Saving asks
  the browser for server permission after the user clicks **Save**.
- `manifest.firefox.json`: Firefox's manifest. Firefox has no extension service
  worker, so it runs `background.js` as an event page. It also needs a stable
  add-on id, reads `options_ui` rather than `options_page`, and declares the
  authentication and selected-URL data sent to the configured server. Firefox
  140 is the minimum because it supplies the matching built-in consent prompt.
  Every other file is shared, so Firefox-specific settings stay here instead
  of in a second folder.
- `icons/`: generated from `src/web/static/icon-512.png`.

`--sign` hands the Firefox build to Mozilla's `web-ext sign` on the unlisted
channel and writes a signed `.xpi`. That exists because Firefox refuses any
unsigned add-on with the message "this add-on appears to be corrupt", which
reads like a broken download and is the first thing anyone hits. Credentials
come from the environment or from a `chmod 600` `.amo-credentials` file, and
are passed to the subprocess through its environment rather than its arguments,
since any process can read another's arguments from `/proc`.

`scripts/build_extensions.py` assembles both builds into
`build/chrome-extension/` and `build/firefox-extension/` and, with `--zip`, the
archives attached to a release. The Firefox archive is also what
addons.mozilla.org signs. Chrome loads `extension/` directly and needs no
build step. `tests/test_build_extensions.py` checks that the two manifests agree
on the version and permissions, and that each build contains every shared file
and no stale files. The packaging script uses an explicit runtime-file
allowlist, refuses symbolic links, and removes older archives for the browser
being built so local secrets and stale versions cannot enter a release glob.

## Decisions

- Use the same account as the web page, so the server needs no extra secret.
  The trade-off is that the password sits in extension storage; revoking it
  means changing the web password.
- Store settings in `chrome.storage.local`, not `sync`, so the password is not
  copied to every Chrome profile using the same Google account.
- Treat a bare hostname as `https`. Users must type `http://` when they accept
  the risk of sending the password without encryption.
- Keep only the current server origin permission. Saving a different server
  grants the new origin first, stores it, and then removes access to the old
  origin.
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
  needed because browsers attach cookies automatically; a header filled from
  the client's own settings is not automatic.
- Accept that a badge can remain briefly if Chrome stops the worker before its
  clear timer runs. The next submission replaces it.

## Testing

Packaging and manifest rules are covered by `tests/test_build_extensions.py`;
the server API is covered by `tests/test_api_routes.py`. Mozilla's `web-ext
lint` validates the assembled Firefox manifest. For a manual behavior check,
load the folder unpacked, use **Test connection**, submit a real video, and
confirm that the entry appears in `urls.txt`.

## Journal

- 2026-08-27: Raised Firefox support to 140 and declared transmitted
  authentication, selected-page, and selected-link data so Mozilla's signing
  and install-consent flow matches actual behavior.
- 2026-08-27: Replaced broad release-file discovery with an allowlist and made
  server changes remove the extension's old origin permission.
