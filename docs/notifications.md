# Error notifications

The downloader can send every failed download to an Apprise instance. Apprise receives one HTTP request and forwards it to Telegram, email, Discord, or any other configured service. The downloader does not connect to those services directly.

## Setting it up

1. Sign in to the web UI and open the **Error notifications** card.
2. Tick **Send failed downloads to Apprise**.
3. Enter the **Apprise notify URL**, for example `http://apprise:8000/notify/podcasts`.
4. Press **Send test notification**. The result appears under the buttons.
5. Press **Save** once the test succeeds.

The test uses the values currently in the form, not the saved values. You can therefore test an endpoint before saving it.

## The two Apprise modes

The mode depends on whether **Destination URLs** is filled in.

| Mode | Notify URL | Destination URLs | Where Telegram is configured |
|---|---|---|---|
| Persistent | `http://apprise:8000/notify/<key>` | leave blank | in your Apprise instance, under `<key>` |
| Stateless | `http://apprise:8000/notify` | `tgram://bottoken/chatid` | here, in this app |

Persistent mode is usually the better choice: the bot token stays in Apprise, and this app only knows the notify URL.

**Tag** is optional. It uses Apprise's tag filter to select some of the destinations configured under that key.

## What gets sent

The downloader sends one notification for each failed download:

```
Title: Podcast download failed
Body:  https://www.youtube.com/watch?v=...

       ERROR: unable to download video data: HTTP Error 403: Forbidden
```

The message uses Apprise's `failure` severity, which most services show in red. Its reason is the same one-line cause written to `activity.log`. The full `yt-dlp` command and output remain in `download.log`.

Successful downloads send nothing.

## Reading a failed test

| Message | What it means |
|---|---|
| `Apprise accepted the notification (HTTP 200).` | Working. |
| `Could not reach Apprise: ... Connection refused` | Nothing is listening. Check the host, port, and container network. |
| `Could not reach Apprise: ... Name or service not known` | The host name does not resolve. In Docker, use the container name, not `localhost`. |
| `Apprise returned HTTP 424 ...` | Apprise was reached but could not deliver. Check the destination URLs or configuration key. |
| `Apprise returned HTTP 404 ...` | The endpoint path is wrong, often because the configuration key does not exist. |
| `The URL must start with http:// or https://` | The notify URL is invalid. |

## Notes

- Settings are stored in `notifications.json` in the data directory with owner-only permissions because the endpoint usually contains a key. This matches the protection used for `cookies.txt` and `.env`.
- They are not stored in `config.ini`: the web UI writes them, and rewriting a commented configuration file from a form would remove its comments.
- A notification failure never fails a download. It is logged and the run
  continues.
- Each request has a 10-second timeout. A hung Apprise instance can delay a run by that much for each failure.
- Inside Docker, `localhost` means the downloader's own container. Use the Apprise container name and put both containers on the same network.
