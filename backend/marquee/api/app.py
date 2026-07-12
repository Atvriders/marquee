from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from marquee.api.routes import build_router


@dataclass
class AppContext:
    store: object
    scheduler: object
    reaper: object
    config: object
    broadcaster: object
    static_dir: str | None = None


def create_app(context: AppContext) -> FastAPI:
    app = FastAPI(title="Marquee")
    app.include_router(build_router(context), prefix="/api")

    # SPA serving is owned here (single owner — Plan 3 does NOT add a second mount).
    # Default to the packaged static dir (populated by the frontend build / Docker
    # copy into backend/marquee/api/static) unless a dir is injected (tests). The
    # catch-all is registered AFTER /api so it never shadows it; unknown /api/* still
    # 404s, and a path-traversal guard keeps serving inside the static root.
    static_dir = context.static_dir or str(Path(__file__).resolve().parent / "static")
    if os.path.isdir(static_dir):
        base = Path(static_dir).resolve()
        assets = base / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")
        index_path = base / "index.html"

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            if full_path == "api" or full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="not found")
            candidate = (base / full_path).resolve()
            if full_path and candidate.is_file() and candidate.is_relative_to(base):
                return FileResponse(str(candidate))
            return FileResponse(str(index_path))

    return app
