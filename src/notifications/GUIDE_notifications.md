# Notifications Guide

## Part 1: Purpose

`notifications/` sends one HTTP request to Apprise. Apprise forwards it to Telegram, email, or any other configured service. This package does not know about individual services.

```text
download fails
  -> PodcastDownloadService._record_failure writes activity.log
  -> _notify_failure calls AppriseNotifier
  -> POST JSON to the configured Apprise notify URL
  -> Apprise delivers to its own destinations
```

## Part 2: Design rules

**Failures never stop a run.** `AppriseNotifier.send` catches every error and returns an `AppriseSendResult`. A notification problem must not turn a recoverable download failure into a crashed run.

**The result carries a readable reason.** `detail` is written for a person. The log and the web UI's test button display it. An HTTP rejection includes Apprise's response body, which usually explains which destination refused the message.

**Two server modes, one code path.** Filling in `notification_urls` adds a `urls` field to the request and switches Apprise from persistent mode to stateless mode. Nothing else changes.

**Only `http` and `https`.** `validate_server_url` rejects other schemes before sending a request, so a saved setting cannot make the server open a `file://` path.

## Part 3: Where the settings live

The settings are not in `config.ini`. The web UI writes them, and rewriting a commented configuration file from a form would remove its comments. They live in `notifications.json` in the data directory, which `src/state/notification_store.py` owns. The file is owner-only because the endpoint usually contains a key.

The web server and downloader are separate processes, so this file is their shared boundary. The web server writes it; the next download run reads it.

## Part 4: Web entry points

- `POST /save-notifications` validates and stores the settings.
- `POST /test-notification` sends one `info` message using the values currently in the form, not the saved ones. It returns JSON so the UI can show the exact reason a connection failed.
