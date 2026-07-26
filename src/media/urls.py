"""Validate generic web media URLs accepted by the downloader."""

from __future__ import annotations

from urllib.parse import urlparse


def normalized_hostname(url: str) -> str:
    """Return a lower-case hostname with any port removed.

    Parameters
    ----------
    url:
        Candidate web URL.

    Returns
    -------
    str
        Parsed host name, or an empty string when parsing fails.
    """
    try:
        parsed_url = urlparse(url)
    except ValueError:
        return ""
    return (parsed_url.hostname or "").lower()


def is_supported_media_url(url: str) -> bool:
    """Return whether ``yt-dlp`` may attempt a direct web URL.

    Parameters
    ----------
    url:
        Candidate URL supplied by a user or queue file.

    Returns
    -------
    bool
        ``True`` only for absolute HTTP or HTTPS URLs.
    """
    try:
        parsed_url = urlparse(url.strip())
    except ValueError:
        return False

    # Keep provider-independent validation deliberately narrow. Provider
    # modules apply any additional classification or normalization policy.
    return parsed_url.scheme in {"http", "https"} and bool(parsed_url.netloc)
