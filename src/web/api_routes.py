"""JSON endpoints for programs, signed in with the same accounts as the web page.

The companion browser extension uses these routes to push a URL into the queue
from any page. They are deliberately separate from the HTML form routes in
``routes.py``:

* Credentials arrive in an ``Authorization: Basic`` header instead of a session
  cookie. The web page's cookie cannot serve a program: it is ``HttpOnly``, so
  no extension script can read it, and ``SameSite=lax``, so the browser will
  not attach it to a request that starts on another site.
* There is no CSRF token. CSRF protection exists because browsers attach
  cookies automatically, so a hostile page can make your browser act as you. A
  name and password that the client has to read from its own settings and put
  in a header are never attached automatically, and a page that already knew
  them would not need the forgery. Adding a CSRF check here would guard against
  nothing and break every client.
* Requests and responses are JSON, so a caller reads one ``outcome`` field
  instead of following a redirect and parsing HTML.

The accounts, the constant-time comparison, and the ban after repeated failures
all come from ``account_auth.py``, shared with the login form. A wrong password
here counts toward the same ban as a wrong password on the login page.

No ``WWW-Authenticate`` header is ever sent. That header is what makes a browser
pop up its own grey sign-in box; opening one of these URLs in a tab should just
show the JSON refusal.

No CORS headers are sent, and none are needed: a Manifest V3 browser extension
that declares host permissions for this server is exempt from CORS on its own
requests. A normal web page on another origin still cannot call these routes.
"""

from __future__ import annotations

import base64
import binascii
import logging
from pathlib import Path
from typing import TypeVar, cast

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..config import PodcastConfig
from ..credentials import load_ui_accounts
from ..state.archive_store import ArchiveStore
from ..state.auth_store import AuthStore
from ..state.bypass_store import BypassStore
from ..state.queue_store import QueueStore
from ..trigger import DownloadTrigger
from .account_auth import CredentialCheck, check_credentials
from .auth import client_ip
from .queue_actions import AddUrlOutcome, add_url_to_queue

_logger = logging.getLogger("web.api_routes")
_Dependency = TypeVar("_Dependency")

router = APIRouter(prefix="/api")

# Longest URL the API accepts. Real media URLs are a few hundred characters at
# most; the limit stops a client from writing an enormous line into urls.txt.
MAX_URL_LENGTH = 2048

# What each refusal means to the caller. The messages avoid saying whether the
# account name exists, which is the same reason the login page says only
# "Invalid username or password".
REFUSAL_STATUS: dict[CredentialCheck, tuple[int, str]] = {
    CredentialCheck.NO_ACCOUNTS_CONFIGURED: (
        503,
        "No accounts are configured. Set UI_USERNAME and UI_PASSWORD in .env "
        "and restart.",
    ),
    CredentialCheck.BANNED: (
        429,
        "Too many failed attempts from this address. Try again later.",
    ),
    CredentialCheck.OVERSIZED: (400, "Credentials are too long."),
    CredentialCheck.WRONG: (401, "Invalid username or password."),
}

# Plain-language explanation of every outcome, returned so a client can show a
# message without hard-coding one per key.
OUTCOME_MESSAGES: dict[AddUrlOutcome, str] = {
    AddUrlOutcome.ADDED: "Added to the queue.",
    AddUrlOutcome.DUPLICATE: "Already in the queue.",
    AddUrlOutcome.ALREADY_DOWNLOADED: "Already downloaded.",
    AddUrlOutcome.INVALID: "Not a supported media URL.",
}


class AddUrlRequest(BaseModel):
    """Body of a ``POST /api/add-url`` call.

    Attributes
    ----------
    url:
        Direct video, YouTube channel, or YouTube playlist URL.
    skip_age_check:
        True to process the item now instead of waiting for the configured
        minimum video age. Ignored for channel URLs.
    """

    url: str = Field(min_length=1, max_length=MAX_URL_LENGTH)
    skip_age_check: bool = False


def _read_basic_auth_header(request: Request) -> tuple[str, str]:
    """Return the name and password from an ``Authorization: Basic`` header.

    The header carries ``base64("name:password")``. Only the first colon
    separates the two, so a password may contain colons while an account name
    may not.

    Parameters
    ----------
    request:
        Current request.

    Returns
    -------
    tuple[str, str]
        ``(username, password)``.

    Raises
    ------
    HTTPException
        401 when the header is missing, is not Basic, or cannot be decoded.
    """
    scheme, _, encoded = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "basic" or not encoded.strip():
        raise HTTPException(
            status_code=401,
            detail=(
                "Send your web interface username and password in an "
                "Authorization: Basic header."
            ),
        )

    try:
        decoded = base64.b64decode(encoded.strip(), validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise HTTPException(
            status_code=401, detail="Malformed Authorization header."
        ) from None

    username, separator, password = decoded.partition(":")
    if not separator:
        raise HTTPException(
            status_code=401, detail="Malformed Authorization header."
        )
    return username, password


def _require_account(request: Request) -> None:
    """Reject the request unless it carries a valid account name and password.

    Parameters
    ----------
    request:
        Current request, read for its ``Authorization`` header and client
        address.

    Raises
    ------
    HTTPException
        With the status and message from :data:`REFUSAL_STATUS` for whatever
        went wrong.
    """
    username, password = _read_basic_auth_header(request)

    state = request.app.state
    outcome = check_credentials(
        username,
        password,
        load_accounts=lambda: load_ui_accounts(
            _dependency(state, "credentials_file", Path)
        ),
        auth_store=_dependency(state, "auth_store", AuthStore),
        client_address=client_ip(
            request,
            _dependency(state, "config", PodcastConfig).trust_x_forwarded_for,
        ),
    )
    if outcome is CredentialCheck.ACCEPTED:
        return

    status_code, detail = REFUSAL_STATUS[outcome]
    _logger.info("API sign-in refused for %r: %s", username, outcome)
    raise HTTPException(status_code=status_code, detail=detail)


@router.get("/ping")
def ping(request: Request) -> JSONResponse:
    """Confirm the server is reachable and the caller's account is accepted.

    The extension's settings page calls this behind its "Test connection"
    button, so a wrong address or a wrong password is reported once, at setup,
    instead of silently failing later on a real submission.
    """
    _require_account(request)
    return JSONResponse({"ok": True, "app": "podcast-downloader"})


@router.post("/add-url")
def add_url(request: Request, payload: AddUrlRequest) -> JSONResponse:
    """Add one URL to the download queue.

    Parameters
    ----------
    request:
        Current request, used for the sign-in check and the shared stores.
    payload:
        Parsed JSON body holding the URL and the immediate-processing flag.

    Returns
    -------
    JSONResponse
        ``{"outcome", "message", "url", "immediate"}``. Status 200 for a URL
        that was accepted, was already queued, or was already downloaded; 400
        when the URL is not a supported media link.
    """
    _require_account(request)

    state = request.app.state
    result = add_url_to_queue(
        payload.url,
        skip_age_check=payload.skip_age_check,
        queue_store=_dependency(state, "queue_store", QueueStore),
        archive_store=_dependency(state, "archive_store", ArchiveStore),
        bypass_store=_dependency(state, "bypass_store", BypassStore),
        download_trigger=_dependency(state, "download_trigger", DownloadTrigger),
    )

    _logger.info("API add-url: %s -> %s", payload.url, result.outcome)

    status_code = 400 if result.outcome is AddUrlOutcome.INVALID else 200
    return JSONResponse(
        {
            "outcome": str(result.outcome),
            "message": OUTCOME_MESSAGES[result.outcome],
            "url": result.url,
            "immediate": result.scheduler_woken,
        },
        status_code=status_code,
    )


def _dependency(
    state: object, name: str, expected_type: type[_Dependency]
) -> _Dependency:
    """Return one collaborator that ``create_app`` attached to application state.

    Parameters
    ----------
    state:
        The FastAPI ``app.state`` object.
    name:
        Attribute name of the collaborator.
    expected_type:
        The type expected, used for the failure message.

    Returns
    -------
    _Dependency
        The stored collaborator.

    Raises
    ------
    RuntimeError
        When the attribute is missing. Unlike the HTML routes, these endpoints
        have no fallback: an application built without ``create_app`` is a
        programming error, not a bad request.
    """
    value = getattr(state, name, None)
    if value is None:
        raise RuntimeError(
            f"app.state.{name} is not set; expected a {expected_type.__name__}"
        )
    return cast(_Dependency, value)
