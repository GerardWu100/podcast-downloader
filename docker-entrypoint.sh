#!/bin/sh
set -e

DATA_DIR="${PODCAST_DATA_DIR:-/app}"
DOWNLOAD_DIR="${PODCAST_DOWNLOAD_DIR:-$DATA_DIR/downloads}"
INTERMEDIATE_DIR="${PODCAST_INTERMEDIATE_DIR:-$DATA_DIR/download_work}"
AUTO_UPDATE="${YT_DLP_AUTO_UPDATE:-true}"
YTDLP_PACKAGE_SPEC="yt-dlp[default,curl-cffi]"
HOST_UID="${HOST_UID:-1000}"
HOST_GID="${HOST_GID:-1000}"
SCRIPT_DIR="$(unset CDPATH; cd -- "$(dirname -- "$0")" && pwd)"
ENV_SECRET_FILE="${PODCAST_ENV_SECRET_FILE:-/run/secrets/podcast_downloader_env}"

case "$HOST_UID:$HOST_GID" in
    *[!0-9:]*|:*|*:|*:*:*)
        echo "[startup] HOST_UID and HOST_GID must be positive integers" >&2
        exit 1
        ;;
esac
if [ "$HOST_UID" -eq 0 ] || [ "$HOST_GID" -eq 0 ]; then
    echo "[startup] HOST_UID and HOST_GID must be greater than zero" >&2
    exit 1
fi

# The mounted data directory owns .env (UI account name and password). Compose
# mounts the repository .env as a runtime secret, never as an image layer. The
# checked-in example is the fallback outside Compose.
ENV_FILE="$DATA_DIR/.env"
if [ -f "$ENV_SECRET_FILE" ]; then
    INITIAL_ENV_FILE="$ENV_SECRET_FILE"
elif [ -f /app/.env.example ]; then
    INITIAL_ENV_FILE="/app/.env.example"
else
    INITIAL_ENV_FILE="$SCRIPT_DIR/.env.example"
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

if [ ! -f "$ENV_FILE" ] && [ -f "$INITIAL_ENV_FILE" ]; then
    cp "$INITIAL_ENV_FILE" "$ENV_FILE"
    echo "[startup] Seeded $ENV_FILE from $INITIAL_ENV_FILE"
fi
if [ -f "$ENV_FILE" ]; then
    chmod 600 "$ENV_FILE"
fi

# The mounted data directory exclusively owns runtime cookies. They are never
# copied into an image layer; upload them in the UI or place them in /data.
COOKIE_FILE="$DATA_DIR/cookies.txt"
if [ -f "$COOKIE_FILE" ]; then
    chmod 600 "$COOKIE_FILE"
    echo "[startup] Using mounted cookies file: $COOKIE_FILE"
fi

# Hashing the .env password into .ui_credentials.json happens in start.py,
# so both Docker and local runs share one code path.

# Keep yt-dlp current, but do not fail container startup on transient network issues.
if [ "$AUTO_UPDATE" = "true" ]; then
    echo "[startup] Updating yt-dlp..."
    if uv pip install --upgrade --prerelease allow "$YTDLP_PACKAGE_SPEC" --quiet; then
        echo "[startup] yt-dlp $(yt-dlp --version)"
    else
        echo "[startup] Warning: yt-dlp update failed, continuing with bundled version $(yt-dlp --version)"
    fi
else
    echo "[startup] yt-dlp auto-update disabled; using bundled version $(yt-dlp --version)"
fi

# Docker starts this entrypoint as root so it can repair files created by older
# container versions. Only paths mounted for this application are changed.
# The application itself then runs with the host user's numeric identity, so
# every new MP3 and state file can be managed without sudo on the host.
if [ "$(id -u)" -eq 0 ]; then
    echo "[startup] Setting mounted files to host owner $HOST_UID:$HOST_GID"
    find "$DATA_DIR" "$DOWNLOAD_DIR" "$INTERMEDIATE_DIR" \
        \( ! -uid "$HOST_UID" -o ! -gid "$HOST_GID" \) \
        -exec chown -h "$HOST_UID:$HOST_GID" {} +
    exec gosu "$HOST_UID:$HOST_GID" env HOME="$DATA_DIR" "$@"
fi

exec "$@"
