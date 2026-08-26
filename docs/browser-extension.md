# Browser extension

The extension in `extension/` adds the page you are viewing—or a link on
that page—to the download queue. Click its toolbar icon, right-click a
YouTube or Rumble link, or press `Alt+Shift+D`. You do not need to open another
window or copy and paste a URL.

It uses the same username and password as the web interface. No server
changes are needed.

## 1. Install the extension

1. Open `chrome://extensions`.
2. Turn on **Developer mode**.
3. Select **Load unpacked** and choose the repository's `extension/` folder.

It works in Chrome, Edge, Brave, and other Chromium browsers. Firefox is not
supported because it uses a different background-worker setup.

This extension is meant for a server you control. Do not publish it to the
Chrome Web Store.

## 2. Connect it to your server

Right-click the extension's icon and choose **Options**. Enter:

| Field | Value |
|---|---|
| Server address | The address you open the web page at, such as `https://podcast.example.com` |
| Username and password | The same ones you type on the web page |
| Download immediately | Start direct-video downloads without waiting for SponsorBlock data |

Select **Save**. Chrome asks for permission to contact only that address. Then
select **Test connection**. The extension calls `GET /api/ping` and shows the
response.

If you enter a hostname without `http://` or `https://`, the extension assumes
`https`. For a local server without a certificate, type `http://` explicitly.
Plain HTTP lets anyone between you and the server read your password.

## 3. Use it

| Action | URL added | Shown on |
|---|---|---|
| Click the toolbar icon | The current page | Any page |
| Press `Alt+Shift+D` | The current page | Any page |
| Right-click the page, then choose the podcast item | The current page | YouTube and Rumble pages |
| Right-click a link, then choose the podcast item | The link | Links to YouTube and Rumble, wherever you find them |

The two right-click items sit next to **Copy link address** and stay hidden
elsewhere, so they do not clutter every menu on every site.

The link item filters on the link, not on the page holding it. A YouTube link
posted on a forum or a blog still offers it.

The toolbar icon and the keyboard shortcut are not filtered. They are explicit
actions, so they work anywhere; a page the downloader cannot use comes back as
"Not a supported media URL" and nothing is queued.

To offer the menu on another site, add its Chrome match pattern to
`MENU_SITE_PATTERNS` at the top of `extension/background.js` and reload the
extension. The server itself accepts any http or https link, because `yt-dlp`
handles far more sites than these two; the list only controls where the menu
appears.

The toolbar badge shows `OK` for a new item, `=` for an item already queued or
downloaded, and `!` for an error. Errors also trigger a desktop notification.

Channel and playlist URLs work. A channel always waits for the next scheduled
pass, even when immediate downloads are enabled. One click therefore cannot
start a whole back catalogue.

## Why it does not reuse your browser login

The extension cannot reuse the web session for three reasons:

- The session cookie is `HttpOnly`, so extension code cannot read it.
- The cookie is `SameSite=lax`, so the browser does not attach it to a request
  that starts on another site.
- The hidden form token that every page submission carries exists only inside
  the queue page's HTML.

Instead, it sends your username and password in an `Authorization` header.
The server checks them against the same accounts and applies the same
constant-time comparison and failed-login ban.

The API does not use the web form's Cross-Site Request Forgery (CSRF) check.
CSRF protection is needed when browsers attach cookies automatically, because
a hostile page could then act as you. Credentials read from the extension's
own settings are not attached automatically.

## What the extension can see

It reads a page's address only when you invoke it. Chrome's `activeTab`
permission grants access to that tab for that action, so the extension cannot
watch your browsing. It never touches cookies.

Your password is stored in `chrome.storage.local`, not
`chrome.storage.sync`, so it is not copied to other machines using the same
Google account. It is still stored in your Chrome profile. Anyone with access
to that profile can read it, and revoking it means changing your web password.

## Privacy and safety

Failed sign-ins count toward the same ban as the login page: five failures from
one address within ten minutes block it for fifteen minutes. If you change your
web password, update it in the extension before trying again.

The server never sends a `WWW-Authenticate` header. Opening one of these URLs
in a browser tab therefore shows a plain refusal instead of the browser's own
sign-in box.

## API reference

A phone shortcut, `curl`, or a scheduled job can call the same two routes:

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
for `invalid`; `401` for a wrong name or password; `429` while the address is
banned; and `503` when the server has no accounts configured.

Equivalent YouTube links such as `youtu.be/...` and `watch?v=...` normalize to
one URL. Submitting both therefore gives `duplicate`, not a second queue entry.

## Troubleshooting

| Message | Check |
|---|---|
| `Sign-in rejected` | The username or password does not match an account in `.env`. |
| `Too many failed attempts` | Five failures within ten minutes. Wait fifteen minutes, then fix the password in Options. |
| `Server has no accounts` | `UI_USERNAME` and `UI_PASSWORD` are unset on the server. |
| `Could not reach the server` | Check the address and server status, then select **Save** again in Options to grant permission. |
| `Not a supported media URL` | The page is not a media URL, such as a settings or `chrome://` page. |
