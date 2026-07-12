# syntax=docker/dockerfile:1

# ---- stage 1: build the React/Vite SPA ----
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# The repo's vite outDir points outside the frontend root (into the backend
# package for local dev); override it here so the build stays in this stage.
RUN npm run build -- --outDir dist --emptyOutDir

# ---- stage 2: python runtime ----
FROM python:3.13-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=3022 \
    LIBRARY_DIR=/library \
    CONFIG_DIR=/config

# ffmpeg is required by yt-dlp to remux the trailer streams; curl for healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/ /app/backend/
# Editable install: the package runs from /app/backend/marquee, so the SPA copied
# alongside (below) is what FastAPI's static mount auto-discovers. Installs the
# pinned runtime deps (fastapi 0.115.x / starlette 0.41.x / httpx<1 / yt-dlp / ...).
RUN pip install --no-cache-dir -e ./backend

# Drop the built SPA where create_app() serves it (backend/marquee/api/static).
COPY --from=web /web/dist /app/backend/marquee/api/static

# Non-root user; UID 1000 matches Jellyfin's default PUID so files written into the
# shared /library are readable by Jellyfin without permission juggling.
RUN useradd -u 1000 -m appuser \
    && mkdir -p /library /config \
    && chown -R appuser:appuser /library /config /app

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER appuser
VOLUME ["/library", "/config"]
EXPOSE 3022
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD curl -fsS "http://localhost:${PORT}/api/health" || exit 1
ENTRYPOINT ["/entrypoint.sh"]
