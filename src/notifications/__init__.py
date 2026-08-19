"""Send error notifications to an Apprise instance."""

from .apprise_client import (
    AppriseNotifier,
    AppriseSendResult,
    AppriseSettings,
)

__all__ = [
    "AppriseNotifier",
    "AppriseSendResult",
    "AppriseSettings",
]
