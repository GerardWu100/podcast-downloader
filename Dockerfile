FROM python:3.13-slim

COPY --from=denoland/deno:bin-2.7.14 /deno /usr/local/bin/deno

# ffmpeg is required by yt-dlp for audio extraction
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy just the uv binary from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Put .venv/bin on PATH so subprocess calls to yt-dlp and python work without full paths
ENV PATH="/app/.venv/bin:$PATH"

# Install Python deps (cached layer unless pyproject.toml/uv.lock change)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev \
    && uv pip install "yt-dlp[default]"

# Unbuffered output so all logs appear immediately in docker logs
ENV PYTHONUNBUFFERED=1

# Copy application files. This intentionally includes a repo-root `.ui_password`
# when present so first-boot Docker deploys can seed `/data/.ui_password`
# from a pre-generated hash without extra server-side steps.
COPY . .

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python", "start.py"]
