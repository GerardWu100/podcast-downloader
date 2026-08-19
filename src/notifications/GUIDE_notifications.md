# Notifications Guide

## Part 1: Purpose

`notifications/` sends one HTTP request to an Apprise instance. That instance
does the fan-out to Telegram, email, or anything else it is configured for, so
nothing here knows about any specific service.

```text
download fails
  -> PodcastDownloadService._record_failure writes activity.log
  -> _notify_failure calls AppriseNotifier
  -> POST JSON to the configured Apprise notify URL
  -> Apprise delivers to its own destinations
```

## Part 2: Design rules

**Failures never propagate.** `AppriseNotifier.send` catches everything and
returns an `AppriseSendResult`. A notification problem must not turn a
recoverable download into a crashed run.

**The result carries a readable reason.** `detail` is written for a person: it
is what the log shows and what the web UI's test button prints. An HTTP
rejection includes Apprise's own response body, because that is where Apprise
explains which destination refused.

**Two server modes, one code path.** Filling in `notification_urls` adds a
`urls` field to the request body and switches an Apprise server from persistent
mode to stateless mode. Nothing else changes.

**Only `http` and `https`.** `validate_server_url` rejects other schemes before
any request is attempted, so a saved setting cannot make the server open a
`file://` path.

## Part 3: Where the settings live

Not in `config.ini`. The web UI writes them, and rewriting a commented
configuration file from a form would destroy its comments. They live in
`notifications.json` in the data directory, owned by
`src/state/notification_store.py`, with owner-only permissions because the
endpoint usually embeds a key.

The web server and the downloader are separate processes, so that file is the
only thing they share. The web server writes it; the next download run reads it.

## Part 4: Web entry points

- `POST /save-notifications` validates and stores the settings.
- `POST /test-notification` sends one `info` message using the values currently
  in the form, not the saved ones, so an endpoint can be tried before it is
  saved. It returns JSON rather than redirecting, because the point is to show
  the exact reason a connection failed.
