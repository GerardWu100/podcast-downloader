"""JSON endpoints for programs, authenticated by a bearer token.

The companion browser extension uses these routes to push a URL into the queue
from any page. They are deliberately separate from the HTML form routes in
``routes.py``:

* Authentication is a bearer token in the ``Authorization`` header, not a
  session cookie. See ``api_token.py`` for why a cookie cannot work here.
* There is no CSRF token. CSRF protection exists because browsers attach
  cookies to requests automatically, so a hostile page can make your browser
  act as you. A token that a client has to read from its own settings and put
  in a header is never attached automatically, so there is nothing to forge.
  Adding a CSRF check here would guard against nothing and break every client.
* Requests and responses are JSON, so a caller reads one ``outcome`` field
  instead of following a redirect and parsing HTML.

No CORS headers are sent, and none are needed: a Manifest V3 browser extension
that declares host permissions for this server is exempt from CORS on its own
requests. A normal web page on another origin still cannot call these routes.
"""

from __future__ import annotations

import logging
import secrets
from typing import TypeVar, cast

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..state.archive_store import ArchiveStore
from ..state.bypass_store import BypassStore
from ..state.queue_store import QueueStore
from ..trigger import DownloadTrigger
from .queue_actions import AddUrlOutcome, add_url_to_queue

_logger = logging.getLogger("web.token_api")
_Dependency = TypeVar("_Dependency")

router = APIRouter(prefix="/api")

# Longest URL the API accepts. Real media URLs are a few hundred characters at
# most; the limit stops a client from writing an enormous line into urls.txt.
MAX_URL_LENGTH = 2048

TOKEN_NOT_CONFIGURED_DETAIL = (
    "The token API is disabled. Set PODCAST_API_TOKEN in .env to a random "
    "string of at least 32 characters and restart."
)

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


def _configured_token(request: Request) -> str:
    """Return the bearer token this deployment accepts, or an empty string."""
    return str(getattr(request.app.state, "api_token", "") or "")


def _require_api_token(request: Request) -> None:
    """Reject the request unless it carries the configured bearer token.

    Parameters
    ----------
    request:
        Current request, read for its ``Authorization`` header.

    Raises
    ------
    HTTPException
        503 when no token is configured, 401 when the header is missing,
        malformed, or wrong.
    """
    expected_token = _configured_token(request)
    if not expected_token:
        raise HTTPException(status_code=503, detail=TOKEN_NOT_CONFIGURED_DETAIL)

    scheme, _, presented_token = request.headers.get(
        "authorization", ""
    ).partition(" ")
    # compare_digest keeps the comparison time independent of how many leading
    # characters matched, so a caller cannot learn the token one byte at a time.
    if scheme.lower() != "bearer" or not secrets.compare_digest(
        presented_token.strip(), expected_token
    ):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid API token.",
        )


@router.get("/ping")
def ping(request: Request) -> JSONResponse:
    """Confirm the server is reachable and the caller's token is accepted.

    The extension's settings page calls this behind its "Test connection"
    button, so a wrong address or a stale token is reported once, at setup,
    instead of silently failing later on a real submission.
    """
    _require_api_token(request)
    return JSONResponse({"ok": True, "app": "podcast-downloader"})


@router.post("/add-url")
def add_url(request: Request, payload: AddUrlRequest) -> JSONResponse:
    """Add one URL to the download queue.

    Parameters
    ----------
    request:
        Current request, used for the token check and the shared stores.
    payload:
        Parsed JSON body holding the URL and the immediate-processing flag.

    Returns
    -------
    JSONResponse
        ``{"outcome", "message", "url", "immediate"}``. Status 200 for a URL
        that was accepted, was already queued, or was already downloaded; 400
        when the URL is not a supported media link.
    """
    _require_api_token(request)

    state = request.app.state
    result = add_url_to_queue(
        payload.url,
        skip_age_check=payload.skip_age_check,
        queue_store=_dependency(state, "queue_store", QueueStore),
        archive_store=_dependency(state, "archive_store", ArchiveStore),
        bypass_store=_dependency(state, "bypass_store", BypassStore),
        download_trigger=_dependency(state, "download_trigger", DownloadTrigger),
    )

    _logger.info("token API add-url: %s -> %s", payload.url, result.outcome)

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
