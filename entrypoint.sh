#!/bin/sh
set -e

# Keep the YouTube extractor fresh so a server-side extractor break doesn't require
# an image rebuild. Best-effort only — never block startup if it's offline. The
# container runs as non-root appuser (see Dockerfile), so `yt-dlp -U` (which needs
# to rewrite the package it was launched from) and a system-wide pip install both
# fail; install to the user site-packages instead, which takes precedence on
# PYTHONPATH. appuser has HOME set via `useradd -m`, and Debian slim ships `timeout`.
timeout 120 pip install --user -U --quiet "yt-dlp[default]" >/dev/null 2>&1 || true

exec python -m marquee serve
