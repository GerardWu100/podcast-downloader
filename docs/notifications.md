# Error notifications

The downloader can send each failed download to an Apprise instance. Apprise
then forwards the message to Telegram, email, Discord, or another configured
service. The downloader does not connect to those services directly.

## Set it up

1. Sign in to the web UI and open **Settings**.
2. Find **Error notifications** and select **Send failed downloads to Apprise**.
3. Enter the **Apprise notify URL**, such as `http://apprise:8000/notify/podcasts`.
4. Select **Send test notification** and check the result shown below the buttons.
5. Select **Save** after the test succeeds.

The test uses the values currently in the form, not the saved values. You can
test an endpoint before saving it.

## Choose an Apprise mode

The mode depends on whether **Destination URLs** contains a value.

| Mode | Notify URL | Destination URLs | Where Telegram is configured |
|---|---|---|---|
| Persistent | `http://apprise:8000/notify/<key>` | leave blank | in your Apprise instance, under `<key>` |
| Stateless | `http://apprise:8000/notify` | `tgram://bottoken/chatid` | here, in this app |

Persistent mode is usually the better choice. The bot token stays in Apprise,
so this app only needs the notify URL.

**Tag** is optional. It tells Apprise to use only destinations with that tag
under the selected key.

## What the downloader sends

The downloader sends one notification for each failed download:

```
Title: Podcast download failed
Body:  https://www.youtube.com/watch?v=...

       ERROR: unable to download video data: HTTP Error 403: Forbidden
```

The message uses Apprise's `failure` severity, which most services show in red.
The reason is the same one-line cause written to `activity.log`. The full
`yt-dlp` command and output remain in `download.log`.

Successful downloads send nothing.

## Understand a failed test

| Message | What it means |
|---|---|
| `Apprise accepted the notification (HTTP 200).` | Working. |
| `Could not reach Apprise: ... Connection refused` | Nothing is listening at that address. Check the host, port, and container network. |
| `Could not reach Apprise: ... Name or service not known` | The host name cannot be found. In Docker, use the container name, not `localhost`. |
| `Apprise returned HTTP 424 ...` | Apprise was reached but could not deliver the notification. Check the destination URLs or configuration key. |
| `Apprise returned HTTP 404. The server returned an HTML error page ...` | The endpoint may be wrong. Check that it contains `/notify/`, for example `http://apprise-api:8000/notify/<key>`. |
| `Apprise returned HTTP 404 ...` | The path is correct, but the configuration key does not exist on that instance. |
| `Apprise returned HTTP 5xx. The server returned an HTML error page ...` | The server or reverse proxy is failing. Check its status and authentication rather than changing a known-good path. |
| `The URL must start with http:// or https://` | The notify URL is invalid. |

## Common mistakes

**Missing `/notify/`.** The key alone is not the endpoint. If the Apprise web
interface gives you `<key>`, use `http://host:8000/notify/<key>`. Without
`/notify/`, the request goes to the Apprise web page and returns a 404 with
HTML.

**Leaving the placeholder in Destination URLs.** `tgram://bottoken/chatid` is
greyed-out example text, not a setting. If you enter it, the app treats it as a
real destination and ignores the destinations stored under the key. If your
Apprise instance already knows where to send notifications, leave this field
empty.

## Notes

- Settings are stored in `notifications.json` in the data directory with owner-only permissions because the endpoint usually contains a key. This is the same protection used for `cookies.txt` and `.env`.
- Settings are not stored in `config.ini`. The web UI writes them, and saving a form over a commented configuration file would remove its comments.
- A notification failure does not fail the download. It is logged, and the run continues.
- Each request has a 10-second timeout. A stalled Apprise instance can delay a run by up to 10 seconds for each failure.
- Inside Docker, `localhost` means the downloader's own container. Use the Apprise container name, and put both containers on the same network.
