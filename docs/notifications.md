# Error notifications

The downloader can push every failed download to an Apprise instance you run.
Apprise is a notification relay: one HTTP request to it fans out to Telegram,
email, Discord, or whatever else that instance is set up for. The downloader
never talks to Telegram directly, so no bot token has to live in this app
unless you choose stateless mode below.

## Setting it up

1. Sign in to the web UI and find the **Error notifications** card.
2. Tick **Send failed downloads to Apprise**.
3. Fill in the **Apprise notify URL**, for example
   `http://apprise:8000/notify/podcasts`.
4. Press **Send test notification**. The result appears under the buttons.
5. Press **Save** once the test succeeds.

The test button uses whatever is currently typed in the form, not the saved
values, so you can try an endpoint before committing to it.

## The two Apprise modes

Which mode you are in depends only on whether the **Destination URLs** field is
filled in.

| Mode | Notify URL | Destination URLs | Where Telegram is configured |
|---|---|---|---|
| Persistent | `http://apprise:8000/notify/<key>` | leave blank | in your Apprise instance, under `<key>` |
| Stateless | `http://apprise:8000/notify` | `tgram://bottoken/chatid` | here, in this app |

Persistent mode is the better choice: the bot token stays in Apprise, and this
app only ever knows a URL.

**Tag** is optional. It maps to Apprise's own tag filter and picks a subset of
the destinations configured under that key.

## What gets sent

One notification per failed download:

```
Title: Podcast download failed
Body:  https://www.youtube.com/watch?v=...

       ERROR: unable to download video data: HTTP Error 403: Forbidden
```

The message severity is Apprise's `failure`, which most services show in red.
The reason is the same one-line cause written to `activity.log`. The full
`yt-dlp` command and output stay in `download.log`.

Successful downloads send nothing.

## Reading a failed test

| Message | What it means |
|---|---|
| `Apprise accepted the notification (HTTP 200).` | Working. |
| `Could not reach Apprise: ... Connection refused` | Nothing is listening. Check the host, the port, and whether the container can reach it. |
| `Could not reach Apprise: ... Name or service not known` | The host name does not resolve. In Docker, use the container name, not `localhost`. |
| `Apprise returned HTTP 424 ...` | Apprise was reached but could not deliver. The destination URLs or the stored configuration key are wrong. |
| `Apprise returned HTTP 404 ...` | The endpoint path is wrong, usually a configuration key that does not exist. |
| `The URL must start with http:// or https://` | Typo in the notify URL. |

## Notes

- Settings are stored in `notifications.json` in the data directory, with
  owner-only permissions, because the endpoint usually embeds a key. This is
  the same treatment as `cookies.txt` and `.env`.
- They are not in `config.ini`. The web UI writes them, and rewriting a
  commented configuration file from a form would destroy its comments.
- A notification failure never fails a download. It is logged and the run
  continues.
- Each request gets 10 seconds. A hung Apprise instance delays a run by that
  much per failure, not longer.
- Inside Docker, `localhost` means the downloader's own container. Point the
  notify URL at the Apprise container name and put both on the same network.
