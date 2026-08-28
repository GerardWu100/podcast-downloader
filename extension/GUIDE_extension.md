# Extension guide

## Purpose

This folder contains the browser client for adding pages and links to the
download queue. It runs in Chrome and Firefox, separately from the server. The
Docker image does not include it, and the server does not import it.

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

The web form uses the same queue actions, so both entry points share URL
validation, normalization, duplicate handling, and immediate-download rules.

## Files

- `manifest.json`: Manifest V3 declaration and limited permissions. `activeTab`
  reveals a tab URL only when the user invokes the extension. The options page
  requests access only to the server address entered by the user.
- `background.js`: background worker for context menus, shortcuts, API calls,
  badges, and error notifications. Chrome runs it as a service worker; Firefox
  runs it as a non-persistent background page. It re-reads settings for every
  submission because the browser may stop it at any time.
  `MENU_SITE_PATTERNS` controls where right-click items appear.
- `settings.js`: reads and writes `chrome.storage.local` and converts the
  server address into a URL and permission pattern. The worker and options page
  use the same conversion.
- `options.html`, `options.css`, and `options.js`: settings page for the server
  address, username, and password. Saving asks the browser for server
  permission after the user selects **Save**.
- `manifest.firefox.json`: Firefox's manifest. Firefox has no extension
  service worker, so it runs `background.js` as an event page. It also needs a
  stable add-on ID, reads `options_ui` rather than `options_page`, and declares
  the authentication and selected-URL data sent to the configured server.
  Firefox 140 is the minimum because it supplies the matching consent prompt.
  All other files are shared.
- `icons/`: generated from `src/web/static/icon-512.png`.

The `--sign` option sends the Firefox build to Mozilla's `web-ext sign` on the
unlisted channel and writes a signed `.xpi`. Firefox refuses unsigned add-ons
with the message "this add-on appears to be corrupt", so releases publish the
signed file instead. Credentials come from the environment or a `chmod 600`
`.amo-credentials` file. The script passes them through the subprocess
environment because other processes can read command arguments from `/proc`.

`scripts/build_extensions.py` assembles both builds into
`build/chrome-extension/` and `build/firefox-extension/`. With `--zip`, it also
creates the Chrome archive attached to a release. Chrome loads `extension/`
directly and needs no build step. Firefox installs the signed `.xpi`; an
unsigned Firefox archive is rejected.

`tests/test_build_extensions.py` checks manifest versions and permissions,
shared files, stale files, and archive behavior. A build without `--zip` must
leave Chrome's existing archive alone because `--sign` rebuilds both folders
first. The packaging script uses an explicit runtime-file allowlist, refuses
symbolic links, and removes older archives and signed add-ons so secrets and
stale versions cannot enter a release glob.

## Decisions

- Open the settings page when nothing is configured. A first click on a fresh
  install has nothing to submit, and the settings page can explain what to do.
  `chrome.runtime.openOptionsPage()` handles the first step; the page shows a
  prompt when its stored values are empty.
- Send only the URL. `POST /api/add-url` accepts `skip_age_check`, but the
  extension no longer sends it. Direct videos already wake the scheduler; the
  flag would instead create a one-use age-bypass entry and force a full-playlist
  run. Those are server-side queue decisions.
- Use the web account. This avoids another server secret, and changing the web
  password revokes the password stored in the extension.
- Store settings in `chrome.storage.local`, not `sync`, so the password is not
  copied to every Chrome profile using the same Google account.
- Treat a bare hostname as `https`. Users must type `http://` when they accept
  the risk of sending the password without encryption.
- Keep only the current server origin permission. Saving a different server
  grants the new origin first, stores it, then removes access to the old one.
- Build the `Authorization` header from UTF-8 bytes before base64 encoding.
  `btoa` alone throws for accented characters in a password.
- Treat `duplicate` and `downloaded` as successful outcomes because the item
  is already handled.
- Limit right-click items to YouTube and Rumble. The page item uses
  `documentUrlPatterns`; the link item uses `targetUrlPatterns`, so a YouTube
  link on another site still offers the menu. The toolbar icon and shortcut
  stay available everywhere, while the server rejects unusable URLs. To add a
  site, edit `MENU_SITE_PATTERNS` and reload the extension.
- Do not send a Cross-Site Request Forgery (CSRF) token. CSRF protection is
  needed when browsers attach cookies automatically; a header filled from the
  client's own settings is not automatic.
- Accept that a badge can remain briefly if Chrome stops the worker before its
  clear timer runs. The next submission replaces it.

## Testing

Packaging and manifest rules are covered by `tests/test_build_extensions.py`;
the server API is covered by `tests/test_api_routes.py`. Mozilla's `web-ext
lint` validates the assembled Firefox manifest. For a manual behavior check,
load the folder unpacked, use **Test connection**, submit a real video, and
confirm that the entry appears in `urls.txt`.

## Journal

- 2026-08-28: A first click on an unconfigured extension opens the settings
  page. The web help page at `/help` now covers installing and using the
  extension and links to the repository.
- 2026-08-28: Removed the "Download immediately" checkbox. It set
  `skip_age_check`, which the name did not describe, so the extension now
  submits the URL alone.
- 2026-08-28: Stopped building a Firefox `.zip`. It was unsigned, so Firefox
  reported it as corrupt, and it could be mistaken for the signed `.xpi` in a
  release. Releases now attach one file per browser.
- 2026-08-27: Raised Firefox support to 140 and declared transmitted
  authentication, selected-page, and selected-link data so Mozilla's signing
  and install-consent flow matches actual behavior.
- 2026-08-27: Replaced broad release-file discovery with an allowlist and made
  server changes remove the extension's old origin permission.
