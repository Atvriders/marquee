from __future__ import annotations

import argparse
import os
from dataclasses import dataclass

from marquee.config import Config, load_config
from marquee.store import Store
from marquee.tmdb.client import TMDBClient
from marquee.tmdb.curator import discover, enrich
from marquee.downloader import TrailerDownloader, normalize_cookies_text
from marquee.library.writer import LibraryWriter
from marquee.library.reaper import Reaper
from marquee.jellyfin import JellyfinClient
from marquee.pipeline import RefreshPipeline
from marquee.scheduler import Scheduler
from marquee.watchdog import Watchdog
from marquee.api.sse import Broadcaster
from marquee.api.app import AppContext, create_app
from marquee.models import Status

DEFAULT_PORT = 3022


@dataclass
class Components:
    store: object
    client: object
    downloader: object
    writer: object
    jellyfin: object
    reaper: object
    pipeline: object
    scheduler: object
    broadcaster: object
    config: object
    watchdog: object


def _ensure_writable_dir(path: str) -> None:
    """Create `path` if it doesn't exist yet, then verify the current process
    can actually write into it. A uid/gid mismatch between the container and
    a host bind-mount (the verified live-deployment failure: /config/tmp not
    writable) is otherwise invisible until it resurfaces much later as a
    cryptic per-download yt-dlp "Errno 13" deep inside the pipeline. Fail
    loudly here instead."""
    uid, gid = os.getuid(), os.getgid()
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, f".marquee-write-check-{os.getpid()}")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
    except OSError as e:
        message = (
            f"Directory {path!r} is not writable by this process "
            f"(running as uid={uid} gid={gid}): {e}. Marquee cannot start. "
            "Hint: containers commonly run as uid=99 gid=100 (Unraid's "
            "'nobody:users') — chown the HOST directory to match, or set "
            "PUID/PGID to the directory's actual owner."
        )
        print(f"FATAL: {message}")
        raise RuntimeError(message) from e


def _check_data_dirs_writable(config: Config) -> None:
    """Verify every directory Marquee writes to (state db, library, and the
    yt-dlp temp dir) is actually writable before anything else touches disk."""
    _ensure_writable_dir(config.config_dir)
    _ensure_writable_dir(config.library_dir)
    _ensure_writable_dir(os.path.join(config.config_dir, "tmp"))


def build_components(config: Config) -> Components:
    _check_data_dirs_writable(config)

    # Cookies pasted inline via YTDLP_COOKIES_TEXT are written to a file in /config
    # (normalized) and the downloader is pointed at it — no separate cookies file
    # to mount. An explicit YTDLP_COOKIES path still takes precedence.
    if not config.ytdlp_cookies and config.ytdlp_cookies_text and config.ytdlp_cookies_text.strip():
        cookies_path = os.path.join(config.config_dir, "cookies.txt")
        try:
            os.makedirs(config.config_dir, exist_ok=True)
            with open(cookies_path, "w", encoding="utf-8") as fh:
                fh.write(normalize_cookies_text(config.ytdlp_cookies_text))
            config.ytdlp_cookies = cookies_path
        except OSError:
            pass

    store = Store(os.path.join(config.config_dir, "state.db"))
    broadcaster = Broadcaster()
    client = TMDBClient(config.tmdb_token)
    downloader = TrailerDownloader(
        config,
        on_progress=lambda tmdb_id, pct, speed, eta: broadcaster.publish(
            {"type": "progress", "tmdb_id": tmdb_id, "pct": pct, "speed": speed, "eta": eta}
        ),
    )
    writer = LibraryWriter(config.library_dir, client, trailer_extra=config.trailer_extra)
    jellyfin = None
    if config.jellyfin_url and config.jellyfin_api_key:
        jellyfin = JellyfinClient(
            config.jellyfin_url,
            config.jellyfin_api_key,
            config.jellyfin_user,
            config.jellyfin_pass,
        )
    reaper = Reaper(
        store, writer, jellyfin,
        grace_days=config.grace_days, tz=config.tz, count=config.count,
    )
    pipeline = RefreshPipeline(
        client, downloader, writer, reaper, jellyfin, store, config, broadcaster
    )
    watchdog = Watchdog(store, jellyfin, config)
    scheduler = Scheduler(pipeline, reaper, store, config, watchdog)
    return Components(
        store=store, client=client, downloader=downloader, writer=writer,
        jellyfin=jellyfin, reaper=reaper, pipeline=pipeline, scheduler=scheduler,
        broadcaster=broadcaster, config=config, watchdog=watchdog,
    )


def cmd_run(config: Config) -> None:
    comps = build_components(config)
    summary = comps.pipeline.run()
    print(f"run complete: {summary}")


def cmd_reap(config: Config) -> None:
    comps = build_components(config)
    movies = comps.store.list_movies([Status.READY])
    expired = comps.reaper.find_expired(movies)
    for movie in expired:
        comps.reaper.expire(movie)
    print(f"reap complete: expired {len(expired)}")


def cmd_discover(config: Config, client=None) -> str:
    """Render the ranked, enriched top-N table. `client` is injectable for tests."""
    client = client or TMDBClient(config.tmdb_token)
    candidates = discover(
        client, config.sources, config.region, config.language, config.count
    )
    lines = [f"{'#':>3}  {'TMDB':>8}  {'POP':>8}  {'DIGITAL':<12}  {'SRC':<9}  TITLE"]
    for index, cand in enumerate(candidates, start=1):
        enriched = enrich(client, cand, config.region, config.language)
        digital = (
            enriched.digital_date.date().isoformat() if enriched.digital_date else "-"
        )
        lines.append(
            f"{index:>3}  {enriched.tmdb_id:>8}  {enriched.popularity:>8.1f}  "
            f"{digital:<12}  {enriched.digital_date_source:<9}  {enriched.title}"
        )
    return "\n".join(lines)


def cmd_serve(config: Config) -> None:
    import uvicorn

    comps = build_components(config)
    comps.scheduler.start()
    static_dir = os.path.join(os.path.dirname(__file__), "api", "static")
    context = AppContext(
        store=comps.store,
        scheduler=comps.scheduler,
        reaper=comps.reaper,
        config=config,
        broadcaster=comps.broadcaster,
        static_dir=static_dir if os.path.isdir(static_dir) else None,
        watchdog=comps.watchdog,
    )
    app = create_app(context)
    port = int(os.environ.get("PORT", str(DEFAULT_PORT)))
    try:
        uvicorn.run(app, host="0.0.0.0", port=port)
    finally:
        comps.scheduler.stop()
        comps.store.close()
        comps.client.close()
        if comps.jellyfin is not None:
            comps.jellyfin.close()


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="marquee")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("discover", "run", "reap", "serve"):
        sub.add_parser(name)
    args = parser.parse_args(argv)

    config = load_config(os.environ)
    if args.cmd == "discover":
        print(cmd_discover(config))
        return
    {
        "run": cmd_run,
        "reap": cmd_reap,
        "serve": cmd_serve,
    }[args.cmd](config)


if __name__ == "__main__":
    main()
