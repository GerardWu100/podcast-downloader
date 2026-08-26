# Browser extension

The extension in `extension/` adds the page you are viewing—or a link on that
page—to the download queue. Click its toolbar icon, right-click a YouTube or
Rumble link, or press `Alt+Shift+D`. You do not need to open another window or
copy and paste a URL.

It uses the same username and password as the web interface. No server changes
are required.

## 1. Install it

The extension works in Chrome and Firefox. Both use the same code; only the
manifest differs, because Firefox has no extension service workers.

### Chrome, Edge, Brave, and other Chromium browsers

1. Open `chrome://extensions`.
2. Turn on **Developer mode**.
3. Select **Load unpacked** and choose the repository's `extension/` folder.

### Firefox

Build its copy first:

```bash
uv run python scripts/build_firefox_extension.py
```

1. Open `about:debugging#/runtime/this-firefox`.
2. Select **Load Temporary Add-on**.
3. Choose `build/firefox-extension/manifest.json`.

Firefox 121 or newer is required, because earlier versions cannot run a
background script as a module.

**A temporary add-on disappears when Firefox restarts.** That is a Firefox
rule, not something the extension can change: Firefox only installs a signed
add-on permanently. To get a signed copy, build the archive:

```bash
uv run python scripts/build_firefox_extension.py --zip
```

Upload `build/podcast-downloader-firefox.zip` to
[addons.mozilla.org](https://addons.mozilla.org/developers/) as an **unlisted**
add-on. Unlisted means Mozilla signs it and hands the `.xpi` back to you
without publishing it: nobody can search for it or install it, and the review
is automated. Install that `.xpi` and it survives restarts.

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

Select **Save**. The browser asks for permission to contact that one address
and nothing else. Then select **Test connection**, which calls `GET /api/ping`
and shows what came back.

If you enter a hostname without `http://` or `https://`, the extension assumes
`https`. For a local server without a certificate, enter `http://` explicitly.
Plain HTTP allows anyone between you and the server to read your password.

## 3. Use it

| Action | URL added | Available on |
|---|---|---|
| Click the toolbar icon | The current page | Any page |
| Press `Alt+Shift+D` | The current page | Any page |
| Right-click the page and choose the podcast item | The current page | YouTube and Rumble pages |
| Right-click a link and choose the podcast item | The link | YouTube and Rumble links, wherever you find them |

The two right-click items appear next to **Copy link address**. They stay
hidden elsewhere, so they do not clutter menus on other sites.

The link item checks the link itself, not the page that contains it. A YouTube
link on a forum or blog still offers the menu item.

The toolbar icon and keyboard shortcut work anywhere because they are explicit
actions. If the downloader cannot use the page, it reports `Not a supported
media URL` and does not add anything to the queue.

To show the menu on another site, add its match pattern to
`MENU_SITE_PATTERNS` at the top of `extension/background.js`, then reload the
extension. Firefox needs the build script run again first. The server accepts any HTTP or HTTPS link because `yt-dlp` supports
many sites; this list only controls where the menu appears.

The toolbar badge shows `OK` for a new item, `=` for an item already queued or
downloaded, and `!` for an error. Errors also trigger a desktop notification.

Channel and playlist URLs work. A channel always waits for the next scheduled
pass, even when immediate downloads are enabled. One click cannot start an
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
uses the same constant-time comparison and failed-login ban.

The API does not use the web form's Cross-Site Request Forgery (CSRF) check.
CSRF protection is needed when browsers attach cookies automatically: a
malicious page could then act as you. Credentials read from the extension's
own settings are not attached automatically.

## What the extension can see

The extension reads a page's address only when you invoke it. The `activeTab`
permission, which both browsers implement, gives it access to that tab for that
action alone, so it cannot watch your browsing. It never accesses cookies.

Your password is stored in the browser's local extension storage, not the
synced kind, so it is not copied to other machines signed in to the same
browser account. It still sits in your browser profile, where anyone with
access to that profile can read it. Revoking it means changing your web
password.

## Privacy and safety

Failed sign-ins count toward the same ban as the login page: five failures
from one address within ten minutes block it for fifteen minutes. If you
change your web password, update it in the extension before trying again.

The server never sends a `WWW-Authenticate` header. Opening one of these URLs
in a browser tab therefore shows a plain refusal instead of the browser's own
sign-in box.

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
normalized to one URL. Submitting both therefore returns `duplicate`, not a
second queue entry.

## Troubleshooting

| Message | Check |
|---|---|
| `Sign-in rejected` | The username or password does not match an account in `.env`. |
| `Too many failed attempts` | Five failures occurred within ten minutes. Wait fifteen minutes, then fix the password in Options. |
| `Server has no accounts` | `UI_USERNAME` and `UI_PASSWORD` are unset on the server. |
| `Could not reach the server` | Check the address and server status, then select **Save** again in Options to grant permission. |
| `Not a supported media URL` | The page is not a media URL, such as a settings or `chrome://` page. |
