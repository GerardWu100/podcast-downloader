"""Load the bearer token that authenticates non-browser clients.

The browser interface signs in with a username, a password, a session cookie,
and a CSRF token. None of that works for a program: the session cookie is
``HttpOnly`` so no script can read it, and it is ``SameSite=lax`` so it is not
sent on a cross-site POST anyway. Programs authenticate with a bearer token
instead -- one long random string in an ``Authorization`` header.

The token lives in ``PODCAST_API_TOKEN``, read from the process environment
first (which is how Docker passes it) and from ``<data_dir>/.env`` otherwise.
Leaving it unset disables the token API completely.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from ..credentials import ENV_FILENAME, parse_env_file

API_TOKEN_ENV_KEY = "PODCAST_API_TOKEN"
# Rejecting short tokens on purpose. A hand-typed word is guessable, and a
# guessed token lets a stranger queue downloads on your server. Anything from
# `python -c "import secrets; print(secrets.token_urlsafe(32))"` is 43
# characters, comfortably above this floor.
MINIMUM_API_TOKEN_LENGTH = 32

_logger = logging.getLogger("web.api_token")


def load_api_token(data_dir: Path) -> str:
    """Return the configured bearer token, or an empty string when unusable.

    Parameters
    ----------
    data_dir:
        Directory holding ``.env``. In Docker this is the mounted data folder;
        locally it is the project root.

    Returns
    -------
    str
        The token when one is set and long enough. An empty string when the key
        is missing, blank, or shorter than :data:`MINIMUM_API_TOKEN_LENGTH`; the
        token API then answers every request with "not configured" rather than
        accepting a weak secret.
    """
    token = os.environ.get(API_TOKEN_ENV_KEY, "").strip()
    if not token:
        # parse_env_file reads the file directly, so check first: a deployment
        # that passes the token through the environment has no .env at all.
        env_file = data_dir / ENV_FILENAME
        if env_file.is_file():
            token = parse_env_file(env_file).get(API_TOKEN_ENV_KEY, "").strip()

    if not token:
        return ""

    if len(token) < MINIMUM_API_TOKEN_LENGTH:
        _logger.warning(
            "%s is only %d characters; the token API stays disabled until it "
            "is at least %d.",
            API_TOKEN_ENV_KEY,
            len(token),
            MINIMUM_API_TOKEN_LENGTH,
        )
        return ""

    return token
