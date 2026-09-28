"""Call the deployed podcast API using credentials from an explicit dotenv file."""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from dotenv import dotenv_values

REQUEST_TIMEOUT_SECONDS = 30
ACCOUNT_SLOTS = (1, 2, 3)


class NoRedirects(HTTPRedirectHandler):
    """Keep authentication headers from following a server redirect."""

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def build_request(
    env_file: Path,
    account: int,
    command: str,
    media_url: str | None,
    skip_age_check: bool,
) -> Request:
    """Build an authenticated request without putting secrets in process arguments.

    Parameters
    ----------
    env_file : Path
        Existing dotenv file containing PODCAST_SERVER_URL and UI account values.
    account : int
        Account slot, 1 through 3; slot 1 uses unsuffixed variable names.
    command : str
        One of ping, health, or add-url.
    media_url : str or None
        Public media URL for add-url; otherwise unused.
    skip_age_check : bool
        Whether to request a one-use YouTube age override.

    Returns
    -------
    Request
        HTTPS request (HTTP only for loopback), with Basic authentication.
        Values are read only from the selected file, without interpolation.
    """
    if not env_file.is_file():
        raise ValueError("The selected .env file does not exist.")
    values = dotenv_values(env_file, interpolate=False)
    server = (values.get("PODCAST_SERVER_URL") or "").strip().rstrip("/")
    parsed = urlsplit(server)
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or (
            parsed.scheme != "https"
            and not (
                parsed.scheme == "http"
                and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            )
        )
    ):
        raise ValueError("Set PODCAST_SERVER_URL to HTTPS (or loopback HTTP) in .env.")
    suffix = "" if account == 1 else f"_{account}"
    username = values.get(f"UI_USERNAME{suffix}") or ""
    password = values.get(f"UI_PASSWORD{suffix}") or ""
    if not username or not password or password == "changeme" or ":" in username:
        raise ValueError("Set a valid UI_USERNAME/UI_PASSWORD account pair in .env.")
    token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    body = None
    headers = {"Authorization": f"Basic {token}", "Accept": "application/json"}
    if command == "add-url":
        body = json.dumps({"url": media_url, "skip_age_check": skip_age_check}).encode()
        headers["Content-Type"] = "application/json"
    return Request(f"{server}/api/{command}", data=body, headers=headers)


def main() -> int:
    """Parse one command and print JSON; return nonzero on request failure."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--account", type=int, choices=ACCOUNT_SLOTS, default=1)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("ping", help="Check connectivity and authentication")
    commands.add_parser("health", help="Check whether scheduled runs are overdue")
    add = commands.add_parser("add-url", help="Queue media; may start a download")
    add.add_argument("url")
    add.add_argument("--skip-age-check", action="store_true")
    args = parser.parse_args()
    try:
        request = build_request(
            args.env_file,
            args.account,
            args.command,
            getattr(args, "url", None),
            getattr(args, "skip_age_check", False),
        )
        with build_opener(NoRedirects()).open(
            request, timeout=REQUEST_TIMEOUT_SECONDS
        ) as response:
            payload = json.load(response)
        print(json.dumps(payload, indent=2))
        return 0
    except HTTPError as exc:
        # Response bodies and exception strings can contain the private server URL.
        print(
            f"HTTP {exc.code}: request failed; check account or server health. "
            "Do not blindly retry an add-url request.",
            file=sys.stderr,
        )
    except (URLError, OSError, ValueError):
        print(
            "Request failed: check the .env file, connectivity, and JSON response. "
            "Connection details are withheld.",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
