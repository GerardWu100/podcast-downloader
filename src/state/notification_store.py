"""Persist web-editable Apprise notification settings as locked JSON."""

from __future__ import annotations

import fcntl
import json
from pathlib import Path

from ..notifications.apprise_client import AppriseSettings
from .file_locks import locked_text_file

NOTIFICATION_SETTINGS_FILE_NAME = "notifications.json"
# The endpoint URL usually embeds a configuration key, so the file is treated
# as a secret in the same way as cookies.txt and .env.
NOTIFICATION_FILE_PERMISSION_MODE = 0o600


def notification_settings_file_for(data_dir: Path) -> Path:
    """Return the settings path inside one data directory."""
    return data_dir / NOTIFICATION_SETTINGS_FILE_NAME


class NotificationStore:
    """Read and replace notification settings under a cross-process lock.

    The downloader and the web server are separate processes, so the file is
    the only thing they share. The web server writes it and the next download
    run reads it.

    Parameters
    ----------
    settings_file:
        JSON file holding the saved settings.
    """

    def __init__(self, settings_file: Path) -> None:
        self.settings_file = settings_file
        if settings_file.exists():
            settings_file.chmod(NOTIFICATION_FILE_PERMISSION_MODE)

    @property
    def _lock_file(self) -> Path:
        """Return the stable sibling lock path for the replaceable settings file."""
        return self.settings_file.with_name(f"{self.settings_file.name}.lock")

    def _read_unlocked(self) -> AppriseSettings:
        """Read settings, treating an absent or damaged file as defaults."""
        if not self.settings_file.exists():
            return AppriseSettings()
        try:
            raw_settings = json.loads(self.settings_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return AppriseSettings()
        if not isinstance(raw_settings, dict):
            return AppriseSettings()
        return AppriseSettings(
            enabled=bool(raw_settings.get("enabled", False)),
            server_url=str(raw_settings.get("server_url", "")),
            notification_urls=str(raw_settings.get("notification_urls", "")),
            tag=str(raw_settings.get("tag", "")),
        )

    def load(self) -> AppriseSettings:
        """Return the saved settings, or defaults when nothing is saved."""
        with locked_text_file(self._lock_file, "a+", fcntl.LOCK_SH):
            return self._read_unlocked()

    def save(self, settings: AppriseSettings) -> None:
        """Replace the saved settings atomically."""
        with locked_text_file(self._lock_file, "a+", fcntl.LOCK_EX):
            self.settings_file.parent.mkdir(parents=True, exist_ok=True)
            temporary_file = self.settings_file.with_name(
                f".{self.settings_file.name}.tmp"
            )
            temporary_file.write_text(
                json.dumps(
                    {
                        "enabled": settings.enabled,
                        "server_url": settings.server_url.strip(),
                        "notification_urls": settings.notification_urls.strip(),
                        "tag": settings.tag.strip(),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            temporary_file.chmod(NOTIFICATION_FILE_PERMISSION_MODE)
            temporary_file.replace(self.settings_file)
            self.settings_file.chmod(NOTIFICATION_FILE_PERMISSION_MODE)
