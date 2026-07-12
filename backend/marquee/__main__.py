from __future__ import annotations

import argparse
import os
from dataclasses import dataclass

from marquee.config import Config, load_config
from marquee.store import Store
from marquee.tmdb.client import TMDBClient
from marquee.tmdb.curator import discover, enrich
from marquee.downloader import TrailerDownloader
from marquee.library.writer import LibraryWriter
from marquee.library.reaper import Reaper
from marquee.jellyfin import JellyfinClient
from marquee.pipeline import RefreshPipeline
from marquee.scheduler import Scheduler
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


def build_components(config: Config) -> Components:
    store = Store(os.path.join(config.config_dir, "state.db"))
    broadcaster = Broadcaster()
    client = TMDBClient(config.tmdb_token)
    downloader = TrailerDownloader(
        config,
        on_progress=lambda tmdb_id, pct, speed, eta: broadcaster.publish(
            {"type": "progress", "tmdb_id": tmdb_id, "pct": pct, "speed": speed, "eta": eta}
        ),
    )
    writer = LibraryWriter(config.library_dir, client)
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
    scheduler = Scheduler(pipeline, reaper, store, config)
    return Components(
        store=store, client=client, downloader=downloader, writer=writer,
        jellyfin=jellyfin, reaper=reaper, pipeline=pipeline, scheduler=scheduler,
        broadcaster=broadcaster, config=config,
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
