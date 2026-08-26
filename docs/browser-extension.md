# Browser extension

The extension in `extension/` adds a URL to the download queue from the page
you are viewing. Click its toolbar icon, right-click a link, or press
`Alt+Shift+D`. There is no separate window and nothing to copy and paste.

You sign in with the same username and password you already use on the web
page. There is nothing to configure on the server.

## 1. Install the extension

1. Open `chrome://extensions`.
2. Turn on **Developer mode**.
3. Select **Load unpacked** and choose the repository's `extension/` folder.

It works in Chrome, Edge, Brave, and other Chromium browsers. Firefox is not
supported because its background-worker setup is different.

This extension is meant for a server you control. Do not publish it to the
Chrome Web Store.

## 2. Connect it to your server

Right-click the extension's icon and choose **Options**. Enter:

| Field | Value |
|---|---|
| Server address | The address you open the web page at, such as `https://podcast.example.com` |
| Username and password | The same ones you type on the web page |
| Download immediately | Start direct-video downloads without waiting for SponsorBlock data |

Select **Save**. Chrome asks for permission to contact only the address you
entered. Then select **Test connection**, which calls `GET /api/ping` and
reports what came back.

If you enter a hostname with no scheme, the extension assumes `https`. Type
`http://` explicitly for a local server without a certificate, but know that
plain HTTP lets anyone on the network in between read your password.

## 3. Use it

| Action | URL added |
|---|---|
| Click the toolbar icon | The current page |
| Press `Alt+Shift+D` | The current page |
| Right-click the page, then choose the podcast item | The current page |
| Right-click a link, then choose the podcast item | The link |

The toolbar badge shows `OK` for a new item, `=` for an item already queued or
downloaded, and `!` for an error. Errors also raise a desktop notification.

Channel and playlist URLs work. A channel always waits for the next scheduled
pass, even when immediate downloads are enabled, so one click cannot start a
whole back catalogue.

## Why it does not just reuse your browser login

You are already signed in on the web page, so it looks like the extension
should inherit that. It cannot:

- The session cookie is `HttpOnly`, so extension code cannot read it.
- The cookie is `SameSite=lax`, so the browser does not attach it to a request
  that starts on another site.
- The hidden form token that every page submission carries exists only inside
  the queue page's HTML.

So the extension sends your name and password in an `Authorization` header
instead. The server checks them against the same accounts, using the same
constant-time comparison and the same ban after repeated failures.

The API does not use the web form's Cross-Site Request Forgery (CSRF) check.
That protection exists because browsers attach cookies automatically, which
lets a hostile page act as you. Credentials the client reads from its own
settings are never attached automatically, and a page that already knew your
password would not need to forge anything.

## What the extension can see

It reads a page's address only when you invoke it. Chrome's `activeTab`
permission grants access to that tab for that action, so the extension cannot
watch your browsing and never touches cookies.

Your password is stored in `chrome.storage.local`, not `chrome.storage.sync`,
so it is not copied to other machines signed in to the same Google account. It
is still a real password sitting on disk in your Chrome profile: anyone with
that profile can read it, and changing it means changing your web password.

## Privacy and safety

Failed sign-ins count toward the same ban as the login page: five failures from
one address within ten minutes blocks it for fifteen minutes. A saved password
that has gone stale will therefore lock you out for a few minutes rather than
letting the extension retry forever.

The server never sends a `WWW-Authenticate` header, so opening one of these
URLs in a browser tab shows a plain refusal instead of the browser's own
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
one URL, so submitting both gives `duplicate` rather than a second queue entry.

## Troubleshooting

| Message | Check |
|---|---|
| `Sign-in rejected` | The username or password does not match your `.env` accounts. |
| `Too many failed attempts` | Five failures within ten minutes. Wait fifteen minutes, then fix the password in Options. |
| `Server has no accounts` | `UI_USERNAME` and `UI_PASSWORD` are unset on the server. |
| `Could not reach the server` | Check the address and server status, then select **Save** again in Options to grant permission. |
| `Not a supported media URL` | The page is not a media URL, such as a settings or `chrome://` page. |
