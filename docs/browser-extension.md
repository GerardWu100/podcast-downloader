# Browser extension

The extension adds the current page or a link on it to the download queue.
Click the toolbar icon, press `Alt+Shift+D`, or use the right-click menu on
YouTube and Rumble. There is no need to change tabs or copy and paste URLs.

It uses the same username and password as the web interface. No server changes
are required.

## 1. Install it

The [latest release](https://github.com/GerardWu100/podcast-downloader/releases/latest)
includes a ready-made build for each browser. Install it on the computer where
you browse. Installing it on the server does not help if you browse elsewhere.

The extension works in Chrome and Firefox. Most files are shared, but the
browser manifests differ.

### Chrome, Edge, Brave, and other Chromium browsers

1. Open `chrome://extensions`.
2. Turn on **Developer mode**.
3. Select **Load unpacked** and choose the repository's `extension/` folder or
   the unzipped Chrome release folder.

### Firefox

For normal use, download `podcast-downloader-firefox-<version>.xpi` from the
[latest release](https://github.com/GerardWu100/podcast-downloader/releases/latest)
and open it with Firefox. It is signed, installs in one click, and stays
installed. Firefox 140 or newer is required.

For development, use the unsigned build:

```bash
uv run python scripts/build_extensions.py
```

1. Open `about:debugging#/runtime/this-firefox`.
2. Select **Load Temporary Add-on**.
3. Choose `build/firefox-extension/manifest.json`.

Firefox reports an unsigned add-on as *"This add-on could not be installed
because it appears to be corrupt"*. The file is not damaged; Firefox uses
that message whenever Mozilla has not signed the add-on.

A temporary add-on disappears when Firefox restarts. To keep it installed,
create a signed, unlisted add-on.

#### Create a signed, unlisted add-on

An **unlisted** add-on is signed but not published, so people cannot search for
or install it from Mozilla's add-on site.

Once, get an API key from
[addons.mozilla.org](https://addons.mozilla.org/developers/addon/api/key/) and
save it where the script can find it:

```bash
cat > .amo-credentials <<'KEYS'
AMO_API_KEY=<your key>
AMO_API_SECRET=<your secret>
KEYS
chmod 600 .amo-credentials
```

The file is ignored by git and the Docker build. The script refuses to use it
if anyone else on the machine can read it. You can export the two variables
instead.

Whenever you want a signed build, run:

```bash
uv run python scripts/build_extensions.py --sign
```

It writes `build/podcast-downloader-firefox-<version>.xpi`. Signing needs Node
for `npx` and takes about a minute.

You can also sign the add-on manually: zip the contents of
`build/firefox-extension/` with `manifest.json` at the archive root, upload the
archive to [addons.mozilla.org](https://addons.mozilla.org/developers/) as an
**unlisted** add-on, and install the `.xpi` Mozilla returns. The build script
does not create a Firefox archive because Firefox's normal install path rejects
unsigned archives.

This extension is intended for a server you control. Do not publish it as a
listed add-on or in the Chrome Web Store.

## 2. Connect it to your server

Click the toolbar icon. On a new installation, it opens the settings page. To
open it later, right-click the icon and choose **Options** in Chrome, or open
`about:addons`, find Podcast Downloader, and choose **Preferences** in Firefox.
Enter:

| Field | Value |
|---|---|
| Server address | The address you use for the web interface, such as `https://podcast.example.com` |
| Username and password | The same credentials you use on the web page |

There is nothing else to set. The extension sends only the URL to
`/api/add-url`, so the server applies the same queue rules as the web page:

- A direct video starts right away.
- A channel waits for the next scheduled pass.
- A YouTube video newer than `min_channel_video_age_hours` waits for
  SponsorBlock data.

Select **Save**, allow the requested permission, then select **Test
connection**. The test calls `GET /api/ping`. **Connected** means setup is
complete. If you change the address later, saving removes access to the old
server.

If you enter a hostname without `http://` or `https://`, the extension assumes
`https`. For a local server without a certificate, enter `http://` explicitly.
With plain HTTP, anyone between you and the server can read your password.

## 3. Use it

| Action | URL added | Available on |
|---|---|---|
| Select the toolbar icon | The current page | Any page |
| Press `Alt+Shift+D` | The current page | Any page |
| Right-click the page and choose the podcast item | The current page | YouTube and Rumble pages |
| Right-click a link and choose the podcast item | The link | YouTube and Rumble links, wherever you find them |

The two right-click items appear next to **Copy link address** and stay hidden
on other sites. The link item checks the link itself, so a YouTube link on a
forum or blog still gets the menu item.

The toolbar icon and keyboard shortcut work anywhere. If the page is not a
supported media URL, the extension reports `Not a supported media URL` and
leaves the queue unchanged.

To show the menu on another site, add its match pattern to
`MENU_SITE_PATTERNS` at the top of `extension/background.js`, then reload the
extension. Run the build script again before reloading it in Firefox. The
server accepts any HTTP or HTTPS link that `yt-dlp` supports; this list only
controls where the menu appears.

The toolbar badge shows `OK` for a new item, `=` for an item already queued or
downloaded, and `!` for an error. Errors also trigger a desktop notification.

Channel and playlist URLs work, but a channel always waits for the next
scheduled pass. One click does not start an entire back catalogue.

## Why it does not reuse your browser login

The extension cannot reuse the web session:

- The session cookie is `HttpOnly`, so extension code cannot read it.
- The cookie is `SameSite=lax`, so the browser does not attach it to a request
  that starts on another site.
- Each queue-page submission includes a hidden form token that exists only in
  the queue page's HTML.

Instead, the extension sends your username and password in an
`Authorization` header. The server checks them against the same accounts and
applies the same constant-time comparison and failed-login ban.

The API does not use the web form's Cross-Site Request Forgery (CSRF) check.
CSRF protection is needed when browsers attach cookies automatically. The
extension's credentials come from its own settings and are not attached
automatically.

## What the extension can see

The extension reads a page's address only when you invoke it. The `activeTab`
permission gives it access to that tab for the action; it cannot watch your
browsing and never accesses cookies.

Your password is stored in local extension storage, not synced storage, so it
is not copied to other machines using the same browser account. It remains in
your browser profile, where anyone with access to that profile can read it. To
revoke it, change your web password.

Firefox's installation prompt declares authentication information, browsing
activity, and website content because the extension sends the saved account
and the page or link you explicitly choose. It sends nothing to Mozilla or the
project author; the only destination is the server address you save.

## Privacy and safety

Failed sign-ins use the same ban as the login page: five failures from one
address within ten minutes block it for fifteen minutes. If you change your web
password, update it in the extension before trying again.

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

Equivalent YouTube links such as `youtu.be/...` and `watch?v=...` are normalized
to one URL. Submitting both returns `duplicate`, not a second queue entry.

## Troubleshooting

| Message | Check |
|---|---|
| `Sign-in rejected` | The username or password does not match an account in `.env`. |
| `Too many failed attempts` | Five failures occurred within ten minutes. Wait fifteen minutes, then fix the password in Options. |
| `Server has no accounts` | `UI_USERNAME` and `UI_PASSWORD` are unset on the server. |
| `Could not reach the server` | Check the address and server status, then select **Save** again in Options to grant permission. |
| `Not a supported media URL` | The page is not a media URL, such as a settings or `chrome://` page. |

Firefox installation problems:

| Message | Cause |
|---|---|
| "appears to be corrupt" | The archive is unsigned and you used the normal install path. Load it through `about:debugging` instead, or have Mozilla sign it. |
| "not verified for use in Firefox" | Same cause, different Firefox version. |
| The add-on vanished after a restart | Expected for a temporary add-on. Signing is the only way to keep it. |
| `about:debugging` reports a manifest error | A real problem. `npx web-ext lint --source-dir build/firefox-extension` names it. |

`npx web-ext lint` is Mozilla's validator and a quick way to separate a real
build fault from a signing problem. A clean run means the build is valid and
the problem is elsewhere.
