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
    """Return the client address used for login-failure limits."""
    headers = getattr(request, "headers", {})
    if trust_forwarded_headers:
        # Cloudflare provides the original client address in this header.
        cloudflare_ip = headers.get("CF-Connecting-IP")
        if cloudflare_ip:
            return cloudflare_ip.strip()

        # Other proxies place the original address first in this list.
        forwarded_for = headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

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
