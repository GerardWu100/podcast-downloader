# Browser extension

The extension in `extension/` adds the current page or a link on it to the
download queue. Click the toolbar icon, press `Alt+Shift+D`, or use the
right-click menu on YouTube and Rumble. You do not need to switch tabs or copy
and paste URLs.

It uses the same username and password as the web interface. No server changes
are needed.

## 1. Install it

The quickest route is the [latest release](https://github.com/GerardWu100/podcast-downloader/releases/latest), which includes a
ready-made archive for each browser. Unzip the one you want and follow the
loading steps. Everything below also works from a clone.

The files must live on the machine where you browse. If the server runs on
another computer, a clone there does not help your desktop.

The extension works in Chrome and Firefox. Both use the same code; only the
manifest differs because Firefox has no extension service worker support.

### Chrome, Edge, Brave, and other Chromium browsers

1. Open `chrome://extensions`.
2. Turn on **Developer mode**.
3. Select **Load unpacked** and choose the repository's `extension/` folder.

### Firefox

Build the Firefox copy first:

```bash
uv run python scripts/build_extensions.py
```

1. Open `about:debugging#/runtime/this-firefox`.
2. Select **Load Temporary Add-on**.
3. Choose `build/firefox-extension/manifest.json`.

Firefox 121 or newer is required because earlier versions cannot run a
background script as a module.

**A temporary add-on disappears when Firefox restarts.** Firefox permanently
installs only signed add-ons. Build the archive to get a signed copy:

```bash
uv run python scripts/build_extensions.py --zip
```

Upload `build/podcast-downloader-firefox-<version>.zip` to
[addons.mozilla.org](https://addons.mozilla.org/developers/) as an **unlisted**
add-on. Mozilla signs it and returns an `.xpi` without publishing it. Install
that file and it survives restarts.

This extension is meant for a server you control. Do not publish it as a
listed add-on or to the Chrome Web Store.

## 2. Connect it to your server

Open the extension's settings. In Chrome, right-click its icon and choose
**Options**. In Firefox, open `about:addons`, find Podcast Downloader, and
choose **Preferences**. Enter:

| Field | Value |
|---|---|
| Server address | The address you use to open the web interface, such as `https://podcast.example.com` |
| Username and password | The same credentials you use on the web page |
| Download immediately | Start direct-video downloads without waiting for SponsorBlock data |

Select **Save**. The browser asks only for permission to contact that address.
Then select **Test connection**. It calls `GET /api/ping` and shows the result.

If you enter a hostname without `http://` or `https://`, the extension assumes
`https`. For a local server without a certificate, enter `http://` explicitly.
With plain HTTP, anyone between you and the server can read your password.

## 3. Use it

| Action | URL added | Available on |
|---|---|---|
| Click the toolbar icon | The current page | Any page |
| Press `Alt+Shift+D` | The current page | Any page |
| Right-click the page and choose the podcast item | The current page | YouTube and Rumble pages |
| Right-click a link and choose the podcast item | The link | YouTube and Rumble links, wherever you find them |

The two right-click items appear next to **Copy link address** and stay hidden
on other sites.

The link item checks the link itself, not the page that contains it. A YouTube
link on a forum or blog still gets the menu item.

The toolbar icon and keyboard shortcut work anywhere because you invoke them
explicitly. If the page is not usable, the extension reports `Not a supported
media URL` and leaves the queue unchanged.

To show the menu on another site, add its match pattern to
`MENU_SITE_PATTERNS` at the top of `extension/background.js`, then reload the
extension. Run the build script again before reloading it in Firefox. The
server accepts any HTTP or HTTPS link that `yt-dlp` supports; this list only
controls where the menu appears.

The toolbar badge shows `OK` for a new item, `=` for an item already queued or
downloaded, and `!` for an error. Errors also trigger a desktop notification.

Channel and playlist URLs work. A channel always waits for the next scheduled
pass, even when immediate downloads are enabled. One click does not start an
entire back catalogue.

## Why it does not reuse your browser login

The extension cannot reuse the web session for three reasons:

- The session cookie is `HttpOnly`, so extension code cannot read it.
- The cookie is `SameSite=lax`, so the browser does not attach it to a request
  that starts on another site.
- Every queue-page submission includes a hidden form token that exists only in
  the queue page's HTML.

Instead, the extension sends your username and password in an
`Authorization` header. The server checks them against the same accounts and
applies the same constant-time comparison and failed-login ban.

The API does not use the web form's Cross-Site Request Forgery (CSRF) check.
Cross-Site Request Forgery (CSRF) protection is needed when browsers attach
cookies automatically, because a malicious page could then act as you. The
credentials from the extension's settings are not attached automatically.

## What the extension can see

The extension reads a page's address only when you invoke it. The `activeTab`
permission gives it access to that tab for that action, so it cannot watch your
browsing. It never accesses cookies.

Your password is stored in local extension storage, not synced storage, so it
is not copied to other machines signed in to the same browser account. It still
remains in your browser profile, where anyone with access to that profile can
read it. To revoke it, change your web password.

## Privacy and safety

Failed sign-ins count toward the same ban as the login page: five failures
from one address within ten minutes block it for fifteen minutes. If you
change your web password, update it in the extension before trying again.

The server never sends a `WWW-Authenticate` header. Opening an API URL in a
browser tab therefore shows a plain refusal instead of the browser's sign-in
box.

## API reference

A phone shortcut, `curl`, or scheduled job can call the same two routes:

```bash
USERNAME=<your web interface username>
PASSWORD=<your web interface password>
BASE=https://podcast.example.com

curl -u "$USERNAME:$PASSWORD" "$BASE/api/ping"

curl -X POST "$BASE/api/add-url" \
  -u "$USERNAME:$PASSWORD" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=...", "skip_age_check": false}'
```

`POST /api/add-url` returns:

| Field | Meaning |
|---|---|
| `outcome` | `added`, `duplicate`, `downloaded`, or `invalid` |
| `message` | A sentence describing the result |
| `url` | The stored URL, after YouTube normalization |
| `immediate` | Whether the downloader started immediately |

The response status is `200` for `added`, `duplicate`, and `downloaded`; `400`
for `invalid`; `401` for a wrong username or password; `429` while the address
is banned; and `503` when the server has no accounts configured.

Equivalent YouTube links such as `youtu.be/...` and `watch?v=...` are
normalized to one URL. Submitting both returns `duplicate`, not a second queue
entry.

## Troubleshooting

| Message | Check |
|---|---|
| `Sign-in rejected` | The username or password does not match an account in `.env`. |
| `Too many failed attempts` | Five failures occurred within ten minutes. Wait fifteen minutes, then fix the password in Options. |
| `Server has no accounts` | `UI_USERNAME` and `UI_PASSWORD` are unset on the server. |
| `Could not reach the server` | Check the address and server status, then select **Save** again in Options to grant permission. |
| `Not a supported media URL` | The page is not a media URL, such as a settings or `chrome://` page. |
