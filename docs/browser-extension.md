# Browser extension

The extension in `extension/` adds a URL to the download queue from the page
you are viewing. Click its toolbar icon, right-click a link, or press
`Alt+Shift+D`. There is no separate window and nothing to copy and paste.

It uses the same server as the web interface through a small JSON API. Any
other program that can send an HTTP request can use the API too.

## Why it uses a separate token

The web interface signs in with a username, password, session cookie, and
hidden form token. An extension cannot reuse that login safely:

- The session cookie is `HttpOnly`, so extension code cannot read it.
- The cookie is `SameSite=lax`, so the browser does not send it with a
  cross-site `POST` request.
- The form token exists only in the queue page's HTML.

The extension therefore uses one long, random token in an `Authorization`
header. You paste this token into the extension once.

The API does not use the web form's Cross-Site Request Forgery (CSRF) check.
CSRF protection is needed when a browser attaches cookies automatically. This
token is stored in the extension and added deliberately, so another site
cannot forge the request.

## 1. Enable the API

Generate a token and add it to `.env` beside the web-interface accounts:

```bash
uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
```

```text
PODCAST_API_TOKEN=<the generated string>
```

Restart the server. Until this setting exists, every `/api` route returns
`503`. Tokens shorter than 32 characters are rejected and logged because a
short token could be guessed.

In Docker, the token is read from the mounted `/data/.env`; no Compose change
is needed. Run `./update.sh --force` after editing `.env`.

## 2. Install the extension

1. Open `chrome://extensions`.
2. Turn on **Developer mode**.
3. Select **Load unpacked** and choose the repository's `extension/` folder.

It works in Chrome, Edge, Brave, and other Chromium browsers. Firefox is not
supported because its background-worker setup is different.

This extension is intended for a server you control. Do not publish it to the
Chrome Web Store.

## 3. Connect it to the server

Open the extension's options by right-clicking its icon and choosing
**Options**. Enter:

| Field | Value |
|---|---|
| Server address | The address of the web interface, such as `https://podcast.example.com` |
| API token | The value of `PODCAST_API_TOKEN` |
| Download immediately | Start direct-video downloads without waiting for SponsorBlock data |

Select **Save**, then **Test connection**. The test calls `GET /api/ping`.
Chrome asks for permission to contact only the address you entered.

If you enter a hostname without a scheme, the extension assumes `https`. Type
`http://` explicitly for a local server without a certificate. Plain HTTP lets
others on the network read the token.

## Use it

| Action | URL added |
|---|---|
| Click the toolbar icon | The current page |
| Press `Alt+Shift+D` | The current page |
| Right-click the page, then choose the podcast item | The current page |
| Right-click a link, then choose the podcast item | The link |

The toolbar badge shows `OK` for a new item, `=` for an item already queued or
downloaded, and `!` for an error. Errors also create a desktop notification.

Channel and playlist URLs work. A channel always waits for the next scheduled
pass, even when immediate downloads are enabled. One click therefore cannot
start a whole back catalogue.

## Privacy

The extension reads a page address only when you invoke it. Chrome's `activeTab`
permission grants access to that tab for that action; the extension cannot
watch your browsing and never reads cookies.

The API token is stored in `chrome.storage.local`, not `chrome.storage.sync`.
It is not copied to other machines using the same Google account.

## API reference

These routes can also be called by a phone shortcut, `curl`, or a scheduled
job:

```bash
TOKEN=<your token>
BASE=https://podcast.example.com

curl -H "Authorization: Bearer $TOKEN" "$BASE/api/ping"

curl -X POST "$BASE/api/add-url" \
  -H "Authorization: Bearer $TOKEN" \
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
for `invalid`; `401` for a bad token; and `503` when the API is disabled.

Equivalent YouTube links such as `youtu.be/...` and `watch?v=...` are
normalized to one URL, so submitting both produces `duplicate` rather than a
second queue entry.

## Troubleshooting

| Message | Check |
|---|---|
| `API disabled on the server` | `PODCAST_API_TOKEN` is missing or shorter than 32 characters. Check the server log. |
| `Token rejected` | The extension token does not match `.env`. |
| `Could not reach the server` | Check the address, server status, and permission. Select **Save** again in Options. |
| `Not a supported media URL` | The page is not a media URL, such as a settings or `chrome://` page. |
