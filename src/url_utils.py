"""Transitional import alias for the extracted YouTube media policy.

This module remains only while tests and compatibility callers move to
``src.media`` and the file-backed stores.
"""

from __future__ import annotations

import sys

from .media import youtube

# Preserve monkeypatch behavior during the short migration: importing
# ``src.url_utils`` returns the actual provider module, not copied attributes.
sys.modules[__name__] = youtube
