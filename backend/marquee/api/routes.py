from __future__ import annotations

import asyncio
import json
import queue
import subprocess
import sys
from dataclasses import asdict

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import StreamingResponse

from marquee.jellyfin import JellyfinClient
from marquee.models import Movie, Status

_SECRET_KEYS = {"tmdb_token", "jellyfin_api_key", "jellyfin_pass", "ytdlp_cookies_text"}
# System/path fields that must never be overridden via the Settings API — they're
# fixed by the deployment (env vars / volume mounts), not user-editable preferences.
_SYSTEM_KEYS = {"library_dir", "config_dir", "ytdlp_cookies", "ytdlp_cookies_text"}


_IMG_BASE = "https://image.tmdb.org/t/p"


def serialize_movie(m: Movie, progress: dict[int, float] | None = None) -> dict:
    d = asdict(m)
    d["status"] = m.status.value
    for k in ("digital_date", "added_at", "expires_at", "last_checked"):
        v = getattr(m, k)
        d[k] = v.isoformat() if v else None
    # API-added fields (see contract "API JSON & SSE Contract")
    d["poster_url"] = f"{_IMG_BASE}/w500{m.poster_path}" if m.poster_path else None
    d["backdrop_url"] = f"{_IMG_BASE}/w1280{m.backdrop_path}" if m.backdrop_path else None
    d["download_pct"] = (progress or {}).get(m.tmdb_id)
    return d


def _config_public(config) -> dict:
    d = asdict(config)
    for k in _SECRET_KEYS:
        if d.get(k):
            d[k] = "***"
    return d


def build_router(context) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    def health():
        return {"status": "ok"}

    @router.get("/movies")
    def movies():
        return [serialize_movie(m) for m in context.store.list_movies()]

    @router.get("/movies/{tmdb_id}")
    def movie(tmdb_id: int):
        m = context.store.get_movie(tmdb_id)
        if not m:
            raise HTTPException(status_code=404, detail="not found")
        return serialize_movie(m)

    @router.post("/movies/{tmdb_id}/download")
    def download_now(tmdb_id: int, background: BackgroundTasks):
        m = context.store.get_movie(tmdb_id)
        if not m:
            raise HTTPException(status_code=404, detail="not found")
        context.store.set_status(tmdb_id, Status.QUEUED)
        background.add_task(context.scheduler.trigger_refresh)
        return {"status": "queued"}

    @router.delete("/movies/{tmdb_id}")
    def delete_now(tmdb_id: int):
        m = context.store.get_movie(tmdb_id)
        if not m:
            raise HTTPException(status_code=404, detail="not found")
        context.reaper.expire(m)
        return {"status": "expired"}

    @router.post("/movies/{tmdb_id}/pin")
    def pin(tmdb_id: int):
        m = context.store.get_movie(tmdb_id)
        if not m:
            raise HTTPException(status_code=404, detail="not found")
        context.store.set_pinned(tmdb_id, not m.pinned)
        return serialize_movie(context.store.get_movie(tmdb_id))

    def _effective_config() -> dict:
        # context.config overlaid by settings rows (lowercase field names, coerced),
        # returned as a flat public dict with secrets masked. See contract.
        from marquee.config import apply_setting_overrides
        cfg = apply_setting_overrides(context.config, context.store.all_settings())
        return _config_public(cfg)

    @router.get("/settings")
    def get_settings():
        return _effective_config()

    @router.put("/settings")
    def put_settings(payload: dict):
        for k, v in payload.items():
            if v is None or v == "***":
                continue  # never persist a masked/absent secret over the real value
            if k in _SYSTEM_KEYS:
                continue  # never persist path/system fields as settings-row overrides
            if isinstance(v, list):
                v = ",".join(str(x) for x in v)  # list fields (e.g. sources) stored comma-joined
            context.store.set_setting(k, str(v))
        return _effective_config()

    @router.post("/run")
    def run_now(background: BackgroundTasks):
        background.add_task(context.scheduler.trigger_refresh)
        return {"status": "started"}

    @router.post("/reap")
    def reap_now(background: BackgroundTasks):
        background.add_task(context.scheduler.trigger_reap)
        return {"status": "started"}

    @router.get("/status")
    def status():
        import shutil

        counts = {
            st.value: len(context.store.list_movies([st]))
            for st in (
                Status.READY,
                Status.QUEUED,
                Status.DOWNLOADING,
                Status.FAILED,
                Status.EXPIRED,
            )
        }
        try:
            du = shutil.disk_usage(context.config.library_dir)
            disk = {
                "used_gb": round(du.used / 1e9, 2),
                "free_gb": round(du.free / 1e9, 2),
                "total_gb": round(du.total / 1e9, 2),
            }
        except OSError:
            disk = {"used_gb": 0.0, "free_gb": 0.0, "total_gb": 0.0}
        try:
            import yt_dlp

            ytdlp_version = yt_dlp.version.__version__
        except Exception:  # noqa: BLE001
            ytdlp_version = "unknown"
        sched = context.scheduler.status()  # {next_refresh, next_reap, running}
        return {**sched, "counts": counts, "disk": disk, "ytdlp_version": ytdlp_version}

    @router.post("/ytdlp/update")
    def ytdlp_update():
        import yt_dlp

        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--user", "-U", "--quiet",
                 "yt-dlp[default]"],
                timeout=180,
                capture_output=True,
                check=False,
            )
        except Exception:  # noqa: BLE001 - best-effort; never fail the request
            pass

        # Note: the *running* process keeps whatever yt-dlp version it already
        # imported until the process restarts, even though pip may have just
        # installed a newer one on disk. Report that fresh on-disk version when
        # we can, falling back to the already-imported module's version.
        version = yt_dlp.version.__version__
        try:
            result = subprocess.run(
                [sys.executable, "-m", "yt_dlp", "--version"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            fresh = result.stdout.strip()
            if fresh:
                version = fresh
        except Exception:  # noqa: BLE001
            pass

        return {"version": version}

    @router.post("/jellyfin/test")
    def jellyfin_test():
        c = context.config
        if not c.jellyfin_url:
            return {"ok": False, "error": "not configured"}
        jc = JellyfinClient(
            c.jellyfin_url, c.jellyfin_api_key or "", c.jellyfin_user, c.jellyfin_pass
        )
        try:
            return {"ok": jc.test()}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    @router.get("/connections")
    def connections():
        # Live health of the external services Marquee depends on. Each value is
        # "ok" | "error" | "unauthorized" | "not_configured".
        c = context.config
        result: dict[str, str] = {}

        try:
            from marquee.tmdb.client import TMDBClient

            TMDBClient(c.tmdb_token).image_base_url()  # GET /configuration (needs a valid token)
            result["tmdb"] = "ok"
        except Exception as e:  # noqa: BLE001
            result["tmdb"] = "unauthorized" if "401" in str(e) else "error"

        if not c.jellyfin_url:
            result["jellyfin"] = "not_configured"
        else:
            try:
                jc = JellyfinClient(
                    c.jellyfin_url, c.jellyfin_api_key or "", c.jellyfin_user, c.jellyfin_pass
                )
                result["jellyfin"] = "ok" if jc.test() else "error"
            except Exception:  # noqa: BLE001
                result["jellyfin"] = "error"
        return result

    @router.get("/watchdog")
    def watchdog_last():
        if context.watchdog is None:
            raise HTTPException(status_code=503, detail="watchdog not configured")
        last = context.watchdog.get_last()
        if last is None:
            last = context.watchdog.run()
        return last

    @router.post("/watchdog/run")
    def watchdog_run():
        if context.watchdog is None:
            raise HTTPException(status_code=503, detail="watchdog not configured")
        return context.watchdog.run()

    @router.get("/activity")
    async def activity(request: Request):
        # A thread-safe queue.Queue (see marquee.api.sse.Broadcaster): publish()
        # is called from the pipeline's APScheduler worker thread and yt-dlp
        # progress hooks, not just this event loop, so it can't be an
        # asyncio.Queue. We therefore drain it with non-blocking get_nowait()
        # polls instead of an awaitable get().
        q = context.broadcaster.subscribe()
        poll_interval = 0.25
        keepalive_after = 15.0

        async def gen():
            try:
                # Backlog: wrap each stored row as a tagged {"type":"log","entry":...}
                for row in context.store.recent_activity(50):
                    ev = {"type": "log", "entry": row}
                    yield f"data: {json.dumps(ev, default=str)}\n\n"
                idle = 0.0
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        # Live events are already tagged by the publisher:
                        # {"type":"log","entry":...} or {"type":"progress",...}
                        ev = q.get_nowait()
                    except queue.Empty:
                        idle += poll_interval
                        if idle >= keepalive_after:
                            yield ": keepalive\n\n"
                            idle = 0.0
                        await asyncio.sleep(poll_interval)
                        continue
                    idle = 0.0
                    yield f"data: {json.dumps(ev, default=str)}\n\n"
            finally:
                context.broadcaster.unsubscribe(q)

        return StreamingResponse(gen(), media_type="text/event-stream")

    return router
