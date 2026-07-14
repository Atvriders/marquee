from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace


@dataclass
class Config:
    tmdb_token: str
    sources: list[str] = field(default_factory=lambda: ["upcoming", "now_playing"])
    count: int = 50
    region: str = "US"
    language: str = "en-US"
    container: str = "mkv"
    max_height: int = 1080
    refresh_cron: str = "0 3 * * *"
    reaper_cron: str = "0 4 * * *"
    grace_days: int = 0
    tz: str = "UTC"
    library_dir: str = "/library"
    config_dir: str = "/config"
    max_size_gb: float = 0.0
    jellyfin_url: str | None = None
    jellyfin_api_key: str | None = None
    jellyfin_user: str | None = None
    jellyfin_pass: str | None = None
    ytdlp_cookies: str | None = None
    ytdlp_cookies_text: str | None = None  # raw cookies.txt content (materialized to a file)
    ytdlp_proxy: str | None = None
    trailer_extra: bool = True
    jellyfin_library_name: str | None = None
    watchdog_cron: str = "0 * * * *"
    watchdog_stale_play_days: int = 7
    trailer_max_candidates: int = 5


def _truthy(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


def load_config(env: Mapping[str, str], overrides: dict | None = None) -> Config:
    merged: dict[str, str] = {}
    merged.update(env)
    if overrides:
        merged.update({k: str(v) for k, v in overrides.items()})

    def get(key: str, default: str | None = None) -> str | None:
        value = merged.get(key)
        if value is None or value == "":
            return default
        return value

    sources_raw = get("SOURCES", "upcoming,now_playing") or ""
    sources = [s.strip() for s in sources_raw.split(",") if s.strip()]

    return Config(
        tmdb_token=get("TMDB_TOKEN", "") or "",
        sources=sources,
        count=int(get("COUNT", "50")),
        region=get("REGION", "US"),
        language=get("LANGUAGE", "en-US"),
        container=get("CONTAINER", "mkv"),
        max_height=int(get("MAX_HEIGHT", "1080")),
        refresh_cron=get("REFRESH_CRON", "0 3 * * *"),
        reaper_cron=get("REAPER_CRON", "0 4 * * *"),
        grace_days=int(get("GRACE_DAYS", "0")),
        tz=get("TZ", "UTC"),
        library_dir=get("LIBRARY_DIR", "/library"),
        config_dir=get("CONFIG_DIR", "/config"),
        max_size_gb=float(get("MAX_SIZE_GB", "0")),
        jellyfin_url=get("JELLYFIN_URL"),
        jellyfin_api_key=get("JELLYFIN_API_KEY"),
        jellyfin_user=get("JELLYFIN_USER"),
        jellyfin_pass=get("JELLYFIN_PASS"),
        ytdlp_cookies=get("YTDLP_COOKIES"),
        ytdlp_cookies_text=get("YTDLP_COOKIES_TEXT"),
        ytdlp_proxy=get("YTDLP_PROXY"),
        trailer_extra=_truthy(get("TRAILER_EXTRA", "true") or "true"),
        jellyfin_library_name=get("JELLYFIN_LIBRARY_NAME"),
        watchdog_cron=get("WATCHDOG_CRON", "0 * * * *"),
        watchdog_stale_play_days=int(get("WATCHDOG_STALE_PLAY_DAYS", "7")),
        trailer_max_candidates=int(get("TRAILER_MAX_CANDIDATES", "5")),
    )


def apply_setting_overrides(config: Config, rows: Mapping[str, str]) -> Config:
    """Apply DB settings rows (keyed by lowercase Config field name) onto `config`,
    coercing each string to the field's current type. Unknown/uncoercible keys are
    ignored. Returns a new Config (input unchanged)."""
    current = config.__dict__
    updates: dict[str, object] = {}
    for key, raw in rows.items():
        field_name = key.lower()
        if field_name not in current:
            continue
        cur = current[field_name]
        try:
            if isinstance(cur, bool):
                coerced: object = str(raw).strip().lower() in ("1", "true", "yes", "on")
            elif isinstance(cur, int):  # note: bool handled above
                coerced = int(raw)
            elif isinstance(cur, float):
                coerced = float(raw)
            elif isinstance(cur, list):
                coerced = [s.strip() for s in str(raw).split(",") if s.strip()]
            else:  # str or None-typed field
                coerced = raw
        except (TypeError, ValueError):
            continue  # leave the existing value in place
        updates[field_name] = coerced
    return replace(config, **updates)
