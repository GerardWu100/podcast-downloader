"""Post notifications to a self-hosted Apprise instance over HTTP.

Apprise is a notification relay: one HTTP request to it fans out to Telegram,
email, Discord, and so on, depending on how that instance is configured. This
module only speaks to the instance; it never talks to Telegram directly.

Two Apprise server modes are supported, and the difference is only in what the
request body carries:

- Persistent mode. The Apprise instance already stores the destinations under a
  configuration key, and the endpoint URL ends in that key, for example
  ``http://apprise:8000/notify/podcasts``. The body carries only the message.
- Stateless mode. The endpoint is ``http://apprise:8000/notify`` and the body
  also carries the destination URLs, for example ``tgram://token/chatid``.

Filling in ``notification_urls`` selects stateless mode; leaving it blank
selects persistent mode.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

# A notification must never hold up a download run, so the request gets a short
# budget and its failure is reported rather than raised.
APPRISE_REQUEST_TIMEOUT_SECONDS = 10
# Apprise renders this as the message severity. "failure" is the level that
# most services show in red.
APPRISE_FAILURE_TYPE = "failure"
APPRISE_INFO_TYPE = "info"
ALLOWED_URL_SCHEMES = frozenset({"http", "https"})
# Enough of the server's reply to diagnose a rejection without pasting an
# entire error page into the log or the browser.
MAX_RESPONSE_DETAIL_CHARS = 400
# The Apprise API serves its own web page at the site root, so a wrong path
# returns a full HTML page instead of an API error. Pasting that into the UI
# tells the reader nothing, so it is replaced with the actual diagnosis.
HTML_RESPONSE_MARKERS = ("<!doctype html", "<html")
# The shape of a working endpoint, quoted back when a request lands on the
# wrong path. Missing the `/notify` segment is the usual mistake, but this is
# only used in messages: a reverse proxy may legitimately serve another path,
# so it is never enforced.
EXAMPLE_NOTIFY_URL = "http://apprise-api:8000/notify/your-key"


@dataclass(frozen=True)
class AppriseSettings:
    """User-editable notification settings stored outside ``config.ini``.

    These live in a JSON file rather than ``config.ini`` because the web UI
    writes them, and rewriting a commented configuration file from a form
    would destroy its comments.

    Attributes
    ----------
    enabled:
        Whether failures trigger a notification at all.
    server_url:
        Full Apprise notify endpoint, for example
        ``http://apprise:8000/notify/podcasts``.
    notification_urls:
        Optional comma-separated Apprise destination URLs. Setting this
        switches the request to stateless mode.
    tag:
        Optional Apprise tag selecting a subset of configured destinations.
    """

    enabled: bool = False
    server_url: str = ""
    notification_urls: str = ""
    tag: str = ""

    def is_ready(self) -> bool:
        """Return whether a notification can actually be sent."""
        return self.enabled and bool(self.server_url.strip())


@dataclass(frozen=True)
class AppriseSendResult:
    """Outcome of one attempt to reach the Apprise instance.

    Attributes
    ----------
    ok:
        Whether Apprise accepted the notification.
    status_code:
        HTTP status returned, or ``None`` when the request never completed.
    detail:
        Human-readable explanation shown by the test button and written to the
        log. Empty on success with no server message.
    """

    ok: bool
    status_code: int | None
    detail: str


def validate_server_url(server_url: str) -> str:
    """Return an empty string when the URL is usable, or the reason it is not.

    Parameters
    ----------
    server_url:
        Candidate Apprise endpoint typed into the web form.

    Returns
    -------
    str
        Empty when valid. Otherwise a short message naming the problem.
    """
    stripped_url = server_url.strip()
    if not stripped_url:
        return "Enter the Apprise notify URL."
    parsed_url = urlparse(stripped_url)
    if parsed_url.scheme not in ALLOWED_URL_SCHEMES:
        return "The URL must start with http:// or https://"
    if not parsed_url.netloc:
        return "The URL is missing a host name."
    return ""


def _shorten(text: str) -> str:
    """Collapse a server reply to one bounded line."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= MAX_RESPONSE_DETAIL_CHARS:
        return collapsed
    return collapsed[: MAX_RESPONSE_DETAIL_CHARS - 1] + "…"


def summarize_error_body(error_body: str) -> str:
    """Return a useful one-line explanation of a rejected request.

    An HTML body means the request reached the Apprise web interface rather
    than an API endpoint, which is a wrong path rather than a wrong message.
    Showing the page source would bury that.

    Parameters
    ----------
    error_body:
        Raw response body from the failed request.

    Returns
    -------
    str
        A short diagnosis, or the trimmed body when it is already useful.
    """
    stripped_body = error_body.strip()
    if stripped_body[:200].lower().lstrip().startswith(HTML_RESPONSE_MARKERS):
        return (
            "The server answered with a web page, not an API response, so the "
            f"path is wrong. An Apprise endpoint looks like {EXAMPLE_NOTIFY_URL}"
        )
    return _shorten(stripped_body)


class AppriseNotifier:
    """Send one-shot notifications to a configured Apprise endpoint.

    Parameters
    ----------
    settings:
        Endpoint, destinations, and on/off switch.
    logger:
        Destination for delivery failures.
    open_url:
        ``urllib.request.urlopen``-compatible callable. Tests inject a fake so
        no network traffic happens.
    timeout_seconds:
        Per-request budget.
    """

    def __init__(
        self,
        settings: AppriseSettings,
        logger: logging.Logger,
        *,
        open_url=urllib.request.urlopen,
        timeout_seconds: int = APPRISE_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self.settings = settings
        self.logger = logger
        self.open_url = open_url
        self.timeout_seconds = timeout_seconds

    def build_payload(
        self,
        title: str,
        body: str,
        notification_type: str,
    ) -> dict[str, str]:
        """Return the JSON body for one Apprise notify request."""
        payload = {
            "title": title,
            "body": body,
            "type": notification_type,
        }
        # Present destinations mean the instance is not storing them, so they
        # travel with the message instead.
        destinations = self.settings.notification_urls.strip()
        if destinations:
            payload["urls"] = destinations
        tag = self.settings.tag.strip()
        if tag:
            payload["tag"] = tag
        return payload

    def send(
        self,
        title: str,
        body: str,
        *,
        notification_type: str = APPRISE_FAILURE_TYPE,
    ) -> AppriseSendResult:
        """Post one notification and report what happened.

        Never raises. A notification problem must not turn into a download
        problem, so every failure comes back as a result the caller can log.

        Parameters
        ----------
        title:
            Short message heading.
        body:
            Message text.
        notification_type:
            Apprise severity: ``info``, ``success``, ``warning``, or
            ``failure``.

        Returns
        -------
        AppriseSendResult
            Delivery outcome, with the reason when it failed.
        """
        if not self.settings.enabled:
            return AppriseSendResult(False, None, "Notifications are turned off.")

        url_problem = validate_server_url(self.settings.server_url)
        if url_problem:
            return AppriseSendResult(False, None, url_problem)

        payload = self.build_payload(title, body, notification_type)
        request = urllib.request.Request(
            self.settings.server_url.strip(),
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with self.open_url(request, timeout=self.timeout_seconds) as response:
                status_code = getattr(response, "status", None)
                return AppriseSendResult(
                    True,
                    status_code,
                    f"Apprise accepted the notification (HTTP {status_code}).",
                )
        except urllib.error.HTTPError as http_error:
            # Apprise explains rejected payloads in the body, so it is worth
            # reading rather than reporting the status alone.
            try:
                error_body = http_error.read().decode("utf-8", errors="replace")
            except Exception:
                error_body = ""
            detail = summarize_error_body(error_body) or http_error.reason or ""
            self.logger.error(
                "Apprise rejected the notification (HTTP %s): %s",
                http_error.code,
                detail,
            )
            return AppriseSendResult(
                False,
                http_error.code,
                f"Apprise returned HTTP {http_error.code}. {detail}".strip(),
            )
        except Exception as exc:
            # A wrong host name, a refused connection, and a timeout all land
            # here, and all of them mean the same thing to the operator: the
            # instance was not reachable.
            self.logger.error("Could not reach Apprise: %s", exc)
            return AppriseSendResult(
                False,
                None,
                f"Could not reach Apprise: {type(exc).__name__}: {exc}",
            )

    def notify_download_failure(self, video_url: str, reason: str) -> AppriseSendResult:
        """Send the standard message for one failed download."""
        return self.send(
            "Podcast download failed",
            f"{video_url}\n\n{reason}",
            notification_type=APPRISE_FAILURE_TYPE,
        )
