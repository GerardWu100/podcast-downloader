"""Browser sign-in helpers and request-security policy."""

from __future__ import annotations

import json

from fastapi import Request


def security_headers(script_nonce: str | None = None) -> dict[str, str]:
    """Return restrictive headers for browser-facing responses."""
    content_security_policy = [
        "default-src 'none'",
        "style-src 'unsafe-inline'",
        "img-src 'self' data:",
        "connect-src 'self'",
        "form-action 'self'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
        # Both directives fall back to "default-src 'none'" when absent, which
        # silently blocks installing the site as a phone app: the browser
        # refuses the web manifest and refuses to register the service worker
        # even though both are served correctly.
        "manifest-src 'self'",
        "worker-src 'self'",
    ]
    if script_nonce is not None:
        content_security_policy.append(f"script-src 'nonce-{script_nonce}'")

    return {
        "Cache-Control": "no-store",
        "Pragma": "no-cache",
        "Referrer-Policy": "same-origin",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Content-Security-Policy": "; ".join(content_security_policy),
    }


def client_ip(request: Request, trust_forwarded_headers: bool) -> str:
    """Return the client address used for login-failure limits.

    Behind a trusted proxy the address is the last ``X-Forwarded-For`` entry:
    the one the proxy nearest the app added for the peer it saw. Earlier
    entries come from the client and can be anything, so trusting the first
    one would let an attacker pick a new address for every guess and never be
    banned. Cloudflare Tunnel, Caddy, nginx, and Traefik all append (or
    overwrite) the visitor's address last, so this holds for one proxy in
    front of the app.
    """
    headers = getattr(request, "headers", {})
    if trust_forwarded_headers:
        # "spoofed-by-client, real-visitor" -> "real-visitor"
        forwarded_for = headers.get("X-Forwarded-For", "")
        nearest_proxy_entry = forwarded_for.split(",")[-1].strip()
        if nearest_proxy_entry:
            return nearest_proxy_entry

    request_client = getattr(request, "client", None)
    if request_client and getattr(request_client, "host", None):
        return str(request_client.host)
    return "unknown"


def request_is_secure(
    request: Request,
    trust_forwarded_headers: bool,
) -> bool:
    """Return whether a request arrived through HTTPS or a trusted proxy."""
    if request.url.scheme == "https":
        return True
    if not trust_forwarded_headers:
        return False

    headers = getattr(request, "headers", {})
    forwarded_protocol = (
        headers.get("X-Forwarded-Proto", "").split(",")[0].strip().lower()
    )
    if forwarded_protocol == "https":
        return True

    cloudflare_visitor = headers.get("CF-Visitor", "")
    if not cloudflare_visitor:
        return False
    try:
        visitor_data = json.loads(cloudflare_visitor)
    except json.JSONDecodeError:
        return False
    return (
        isinstance(visitor_data, dict)
        and str(visitor_data.get("scheme", "")).lower() == "https"
    )
