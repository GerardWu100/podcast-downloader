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

**The easy way:** download `podcast-downloader-firefox-<version>.xpi` from the
[latest release](https://github.com/GerardWu100/podcast-downloader/releases/latest) and open it with Firefox. It is signed, so it
installs in one click and stays installed. Firefox 140 or newer. Everything
below is the unsigned route, which you need only when developing.

> The Firefox `.zip` is unsigned. Opening it with Firefox, or using **Install
> Add-on From File**, fails with *"This add-on could not be installed because
> it appears to be corrupt."* The file is fine; that is simply how Firefox
> reports an add-on Mozilla has not signed.

Build the Firefox copy first, or unzip the archive from the release:

```bash
uv run python scripts/build_extensions.py
```

1. Open `about:debugging#/runtime/this-firefox`.
2. Select **Load Temporary Add-on**.
3. Choose `build/firefox-extension/manifest.json`.

Firefox 140 or newer is required. That version supports Mozilla's built-in
data-transmission consent, which the extension uses to disclose that it sends
the selected URL and web-account credentials to the server you configure.

**A temporary add-on disappears when Firefox restarts.** Firefox permanently
installs only signed add-ons. Build the archive to get a signed copy:

```bash
uv run python scripts/build_extensions.py --zip
```

#### Make it install like a normal extension

Loading through `about:debugging` is the developer route, and Firefox forgets it
on restart. Signing turns the build into an ordinary `.xpi` you install with one
click, permanently. It stays private: an **unlisted** add-on is signed but never
published, so nobody can search for or install it.

Once, get an API key from
[addons.mozilla.org](https://addons.mozilla.org/developers/addon/api/key/) and
save it where the script will find it:

```bash
cat > .amo-credentials <<'KEYS'
AMO_API_KEY=<your key>
AMO_API_SECRET=<your secret>
KEYS
chmod 600 .amo-credentials
```

That file is ignored by git and by the Docker build, and the script refuses to
use it if anyone else on the machine can read it. Exporting the two variables
instead works the same way.

Then, whenever you want a signed build:

```bash
uv run python scripts/build_extensions.py --sign
```

It writes `build/podcast-downloader-firefox-<version>.xpi`. Open that file with Firefox
and it installs and stays installed. Signing needs Node, for `npx`, and takes
about a minute.

If you would rather do it by hand, upload
`build/podcast-downloader-firefox-<version>.zip` to
[addons.mozilla.org](https://addons.mozilla.org/developers/) as an **unlisted**
add-on and install the `.xpi` it returns.

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
If you later change the address, saving removes access to the old server.

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

Firefox's installation prompt declares authentication information, browsing
activity, and website content because the extension sends the saved account
and the page or link you explicitly choose. It sends nothing to Mozilla or the
project author; the only destination is the server address you save.

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

Installation problems in Firefox:

| Message | Cause |
|---|---|
| "appears to be corrupt" | The archive is unsigned and you used the normal install path. Nothing is wrong with the file. Load it through `about:debugging` instead, or have Mozilla sign it. |
| "not verified for use in Firefox" | Same cause, different Firefox version. |
| The add-on vanished after a restart | Expected for a temporary add-on. Signing is the only way to keep it. |
| about:debugging reports a manifest error | A real problem. `npx web-ext lint --source-dir build/firefox-extension` names it. |

`npx web-ext lint` is Mozilla's own validator and the quickest way to tell a
real fault from a signing complaint. A clean run means the build is fine and
the trouble is elsewhere.
