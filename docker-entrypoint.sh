#!/bin/sh
set -e

DATA_DIR="${PODCAST_DATA_DIR:-/app}"
DOWNLOAD_DIR="${PODCAST_DOWNLOAD_DIR:-$DATA_DIR/downloads}"
INTERMEDIATE_DIR="${PODCAST_INTERMEDIATE_DIR:-$DATA_DIR/download_work}"
AUTO_UPDATE="${YT_DLP_AUTO_UPDATE:-true}"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PASSWORD_FILE="$DATA_DIR/.ui_password"
if [ -f /app/.ui_password ]; then
    IMAGE_PASSWORD_FILE="/app/.ui_password"
else
    IMAGE_PASSWORD_FILE="$SCRIPT_DIR/.ui_password"
fi

if [ -f /app/config.ini ]; then
    DEFAULT_CONFIG_SOURCE=/app/config.ini
else
    DEFAULT_CONFIG_SOURCE="$SCRIPT_DIR/config.ini"
fi

# Seed the mounted data directory from the repo defaults on first boot.
mkdir -p "$DATA_DIR" "$DOWNLOAD_DIR" "$INTERMEDIATE_DIR"

if [ ! -f "$DATA_DIR/config.ini" ]; then
    cp "$DEFAULT_CONFIG_SOURCE" "$DATA_DIR/config.ini"
    echo "[startup] Created $DATA_DIR/config.ini from repo default"
fi

touch "$DATA_DIR/urls.txt" \
      "$DATA_DIR/downloaded_urls.txt" \
      "$DATA_DIR/download.log"

if [ ! -f "$DATA_DIR/.login_state.json" ]; then
    printf '{}\n' > "$DATA_DIR/.login_state.json"
fi

if [ ! -f "$PASSWORD_FILE" ] && [ -f "$IMAGE_PASSWORD_FILE" ]; then
    cp "$IMAGE_PASSWORD_FILE" "$PASSWORD_FILE"
    echo "[startup] Seeded $PASSWORD_FILE from image-bundled .ui_password"
fi

python - "$PASSWORD_FILE" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

from src.passwords import (
    DEFAULT_UI_PASSWORD,
    LEGACY_PASSWORD_PLACEHOLDER,
    hash_password,
    is_password_hash,
)

password_path = Path(sys.argv[1])
status = "unchanged"
message = ""

if not password_path.exists():
    password_path.write_text(f"{hash_password(DEFAULT_UI_PASSWORD)}\n", encoding="utf-8")
    status = "created-default"
    message = f"[startup] Created {password_path} with the default UI password hash for '{DEFAULT_UI_PASSWORD}'"
else:
    stored_value = password_path.read_text(encoding="utf-8").strip()
    if not stored_value or stored_value == LEGACY_PASSWORD_PLACEHOLDER:
        password_path.write_text(f"{hash_password(DEFAULT_UI_PASSWORD)}\n", encoding="utf-8")
        status = "reset-default"
        message = f"[startup] Replaced {password_path} with the default UI password hash for '{DEFAULT_UI_PASSWORD}'"
    elif not is_password_hash(stored_value):
        password_path.write_text(f"{hash_password(stored_value)}\n", encoding="utf-8")
        status = "hashed-plaintext"
        message = f"[startup] Rewrote plain-text password in {password_path} as a hash"

if status != "unchanged":
    print(message)
PY
chmod 600 "$PASSWORD_FILE"

# Keep yt-dlp current, but do not fail container startup on transient network issues.
if [ "$AUTO_UPDATE" = "true" ]; then
    echo "[startup] Updating yt-dlp..."
    if python -m pip install --disable-pip-version-check --upgrade --upgrade-strategy only-if-needed yt-dlp --quiet; then
        echo "[startup] yt-dlp $(yt-dlp --version)"
    else
        echo "[startup] Warning: yt-dlp update failed, continuing with bundled version $(yt-dlp --version)"
    fi
else
    echo "[startup] yt-dlp auto-update disabled; using bundled version $(yt-dlp --version)"
fi

exec "$@"
