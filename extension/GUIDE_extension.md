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
  requests access only to the server address the user enters.
- `background.js`: background worker for context menus, shortcuts, API calls,
  badges, and error notifications. Chrome runs it as a service worker; Firefox
  runs it as a non-persistent background page. It re-reads settings for every
  submission because the browser may stop it at any time.
  `MENU_SITE_PATTERNS` controls where the right-click items appear.
- `settings.js`: reads and writes `chrome.storage.local` and converts the
  server address into a URL and permission pattern. The worker and options page
  use the same conversion.
- `options.html`, `options.css`, and `options.js`: settings page. Saving asks
  the browser for server permission after the user clicks **Save**.
- `manifest.firefox.json`: Firefox's manifest. Firefox has no extension service
  worker, so it runs `background.js` as an event page. It also needs a stable
  add-on ID, reads `options_ui` rather than `options_page`, and declares the
  authentication and selected-URL data sent to the configured server. Firefox
  140 is the minimum because it supplies the matching consent prompt. All
  other files are shared.
- `icons/`: generated from `src/web/static/icon-512.png`.

The `--sign` option sends the Firefox build to Mozilla's `web-ext sign` on the
unlisted channel and writes a signed `.xpi`. Firefox refuses unsigned add-ons
with the message "this add-on appears to be corrupt", so releases publish the
signed file instead. Credentials come from the environment or a `chmod 600`
`.amo-credentials` file. The script passes them through the subprocess
environment rather than its arguments, because other processes can read
command arguments from `/proc`.

`scripts/build_extensions.py` assembles both builds into
`build/chrome-extension/` and `build/firefox-extension/`. With `--zip`, it also
creates the Chrome archive attached to a release. Chrome loads `extension/`
directly and needs no build step. Firefox installs the signed `.xpi`; an
unsigned Firefox archive is rejected.

`tests/test_build_extensions.py` checks that the manifests agree on version and
permissions, that each build contains the shared files and no stale files, that
Firefox produces no archive even with `--zip`, and that a build without `--zip`
leaves Chrome's archive alone. The last rule matters because `--sign` rebuilds
both folders first. The packaging script uses an explicit runtime-file
allowlist, refuses symbolic links, and removes older archives and signed
add-ons so secrets and stale versions cannot enter a release glob.

## Decisions

- Use the same account as the web page. This avoids an extra server secret, but
  the password remains in extension storage; changing the web password revokes
  it.
- Store settings in `chrome.storage.local`, not `sync`, so the password is not
  copied to every Chrome profile using the same Google account.
- Treat a bare hostname as `https`. Users must type `http://` when they accept
  the risk of sending the password without encryption.
- Keep only the current server origin permission. Saving a different server
  grants the new origin first, stores it, and then removes access to the old
  origin.
- Build the `Authorization` header from UTF-8 bytes before base64 encoding.
  `btoa` alone throws for an accented character in a password.
- Treat `duplicate` and `downloaded` as successful outcomes because the item is
  already handled.
- Limit right-click items to YouTube and Rumble. The page item uses
  `documentUrlPatterns`; the link item uses `targetUrlPatterns`, so a YouTube
  link on another site still offers the menu. The toolbar icon and shortcut
  stay available everywhere, while the server rejects unusable URLs. To add a
  site, edit `MENU_SITE_PATTERNS` and reload the extension.
- Do not send a CSRF token. Cross-Site Request Forgery (CSRF) protection is
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

- 2026-08-28: Stopped building a Firefox `.zip`. It was unsigned, so Firefox
  reported it as corrupt, and sitting next to the signed `.xpi` on a release it
  was the file people downloaded. Releases now attach one file per browser.
- 2026-08-27: Raised Firefox support to 140 and declared transmitted
  authentication, selected-page, and selected-link data so Mozilla's signing
  and install-consent flow matches actual behavior.
- 2026-08-27: Replaced broad release-file discovery with an allowlist and made
  server changes remove the extension's old origin permission.
