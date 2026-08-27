FROM python:3.13-slim

COPY --from=denoland/deno:bin-2.7.14 /deno /usr/local/bin/deno

# ffmpeg is required by yt-dlp for audio extraction
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg gosu \
    && rm -rf /var/lib/apt/lists/*

# Copy just the uv binary from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Put .venv/bin on PATH so subprocess calls to yt-dlp and python work without full paths
ENV PATH="/app/.venv/bin:$PATH"

# Install Python deps (cached layer unless pyproject.toml/uv.lock change)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev \
    && uv pip install --prerelease allow "yt-dlp[default,curl-cffi]"

# Unbuffered output so all logs appear immediately in docker logs
ENV PYTHONUNBUFFERED=1

# Copy only the runtime application. Explicit sources keep ignored files and
# local secrets out even if `.dockerignore` is changed incorrectly later.
COPY main.py start.py config.ini .env.example ./
COPY src ./src

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python", "start.py"]
