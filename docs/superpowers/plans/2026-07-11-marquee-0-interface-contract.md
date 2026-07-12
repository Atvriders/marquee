# Marquee — Locked Interface Contract (shared by all plans)

> This file is the single source of truth for module layout, type/function signatures, the data model, global constraints, and test conventions. **Plans 1–3 must use these names and types verbatim.** If a plan needs a new shared symbol, it is added here first.

Spec: [`../specs/2026-07-11-marquee-design.md`](../specs/2026-07-11-marquee-design.md)

---

## Global Constraints (apply to every task)

- **Python 3.13**, `pyproject.toml` (PEP 621), package name `marquee`, src under `backend/`.
- **yt-dlp** installed as `yt-dlp[default]` (latest; nightly acceptable). **ffmpeg** required at runtime, found on PATH.
- **Download format string (exact):** `bv*[height<=1080]+ba/b[height<=1080]/b` with `merge_output_format` = configured container (`mkv` default). Merge is **stream-copy (no re-encode)**.
- **Real output path** comes from `info["requested_downloads"][0]["filepath"]`, never `prepare_filename`.
- **Library layout:** one folder per movie `"<SanitizedTitle> (<year>) [tmdbid-<id>]"`; the video filename **begins character-for-character with the folder name**; illegal chars `< > : " / \ | ? *` stripped/replaced.
- **NFO** fields exactly per spec §5 (`plot`→overview, `runtime` in minutes, `uniqueid type="tmdb" default="true"`, `thumb aspect="poster"`, `fanart/thumb`). No reliance on `<lockdata>`.
- **TMDB auth:** v4 **Bearer** read token (`Authorization: Bearer <token>`). Base `https://api.themoviedb.org/3`. Concurrency ≤5; on HTTP 429 respect `Retry-After`. Cache `/configuration`.
- **TMDB release types:** 1 Premiere, 2 Theatrical-ltd, 3 Theatrical, **4 Digital**, 5 Physical, 6 TV. Digital-date fallback chain: region type-4 → US type-4 → earliest type-4 anywhere → type-5 → type-6 → None(keep).
- **Images:** poster `w500`, backdrop `w1280`, via `secure_base_url` from `/configuration`.
- **Jellyfin:** `DELETE /Items/{id}` requires an **admin user token** from `POST /Users/AuthenticateByName`; scans use the API key. Auth header `X-Emby-Token: <key>` (or `?api_key=`).
- **Container:** non-root `appuser` UID 1000; volumes `/library` (rw, shared with Jellyfin) and `/config` (rw). GHCR package **public**. Multi-arch amd64+arm64.
- **Not in scope:** `.strm` mode, Radarr/Sonarr, TV shows, transcoding, weighted blending.
- **Time:** store timestamps UTC-aware; compare expiry end-of-day in configured `TZ`.
- **Web port: 3022** (user-chosen). `marquee serve` binds `0.0.0.0:$PORT` (default 3022); Dockerfile `EXPOSE 3022`; healthcheck `localhost:3022/api/health`; compose maps `3022:3022`; Vite dev proxy `/api` → `http://localhost:3022`; README/docs use 3022. Do NOT use 8000.
- **Pinned web stack (supply-chain):** `fastapi>=0.115,<0.116`, `starlette>=0.40,<0.42`, `httpx>=0.27,<1.0`, `uvicorn[standard]>=0.30,<1.0`. **NEVER add `httpx2`** — it is a typosquat (author=None, no homepage, copies httpx's tagline). Starlette 1.3.x (2026) emits a TestClient deprecation steering toward httpx2; the fix is the pin above (which uses plain httpx), NOT installing httpx2.

---

## Data model — `backend/marquee/models.py`

```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

class Status(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    READY = "ready"
    FAILED = "failed"
    EXPIRED = "expired"

class ErrorKind(str, Enum):
    BOT_CHECK = "bot_check"
    AGE_GATED = "age_gated"
    REGION_BLOCKED = "region_blocked"
    UNAVAILABLE = "unavailable"
    NO_FORMAT = "no_format"
    NO_TRAILER = "no_trailer"
    ERROR = "error"

@dataclass
class MovieCandidate:
    tmdb_id: int
    title: str
    year: int | None
    overview: str
    popularity: float
    poster_path: str | None
    backdrop_path: str | None
    source: str            # which list surfaced it: "upcoming" | "now_playing" | ...
    release_date: str | None  # TMDB list release_date (may be "")

@dataclass
class TrailerVideo:
    key: str               # YouTube video id
    site: str              # "YouTube"
    type: str              # "Trailer" | "Teaser" | ...
    official: bool
    size: int              # 360|480|720|1080
    iso_639_1: str
    published_at: str
    @property
    def youtube_url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.key}"

@dataclass
class EnrichedMovie:
    tmdb_id: int
    title: str
    year: int | None
    overview: str
    popularity: float
    source: str
    poster_path: str | None
    backdrop_path: str | None
    runtime: int | None            # minutes
    genres: list[str] = field(default_factory=list)
    studios: list[str] = field(default_factory=list)
    certification: str | None = None
    premiere_date: str | None = None      # ISO date str
    digital_date: datetime | None = None  # tz-aware UTC, or None if unknown
    digital_date_source: str = "none"     # "region"|"us"|"global"|"physical"|"tv"|"none"
    youtube_key: str | None = None
    trailer: TrailerVideo | None = None

@dataclass
class Movie:                # persisted row (store.py). Mirrors spec §9.
    tmdb_id: int
    title: str
    year: int | None
    overview: str
    runtime: int | None
    genres: list[str]
    studios: list[str]
    certification: str | None
    premiere_date: str | None
    digital_date: datetime | None
    digital_date_source: str
    region: str
    popularity: float
    poster_path: str | None
    backdrop_path: str | None
    youtube_key: str | None
    status: Status
    file_path: str | None
    folder: str | None
    jellyfin_item_id: str | None
    pinned: bool
    added_at: datetime
    expires_at: datetime | None
    last_checked: datetime | None
    error_kind: str | None
    error_msg: str | None
```

---

## Module map & signatures

### `backend/marquee/config.py`
```python
@dataclass
class Config:
    tmdb_token: str
    sources: list[str]            # default ["upcoming","now_playing"]
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
    ytdlp_proxy: str | None = None

def load_config(env: Mapping[str,str], overrides: dict|None=None) -> Config: ...

def apply_setting_overrides(config: Config, rows: dict[str,str]) -> Config:
    """Return a copy of `config` with `settings` rows applied.
    Rows are keyed by LOWERCASE Config field name; values are strings coerced to
    the field's current type (int/float/bool/list[str] via comma-split/str).
    Unknown keys are ignored. Used by startup wiring AND the /settings route."""
    ...
```
Effective config = env defaults overlaid by `settings` rows (from store). `SOURCES` parsed from comma list. **Settings rows are keyed by lowercase Config field names** (e.g. `count`, `sources`, `jellyfin_url`) — the same names the frontend `Config` type uses — so `store.all_settings()` feeds directly into `apply_setting_overrides`.

### `backend/marquee/store.py`
```python
class Store:
    def __init__(self, db_path: str): ...     # creates schema if absent
    # movies
    def upsert_movie(self, m: Movie) -> None: ...
    def get_movie(self, tmdb_id: int) -> Movie | None: ...
    def list_movies(self, statuses: list[Status]|None=None) -> list[Movie]: ...
    def set_status(self, tmdb_id:int, status:Status, **fields) -> None: ...
    def set_pinned(self, tmdb_id:int, pinned:bool) -> None: ...
    def delete_movie(self, tmdb_id:int) -> None: ...
    # activity
    def log(self, level:str, event:str, message:str, tmdb_id:int|None=None) -> None: ...
    def recent_activity(self, limit:int=200) -> list[dict]: ...
    # settings
    def get_setting(self, key:str) -> str | None: ...
    def set_setting(self, key:str, value:str) -> None: ...
    def all_settings(self) -> dict[str,str]: ...
```

### `backend/marquee/tmdb/client.py`
```python
class TMDBClient:
    def __init__(self, token: str, session: httpx.Client | None = None,
                 base_url: str = "https://api.themoviedb.org/3"): ...
    def list_movies(self, source: str, region: str, language: str, pages: int = 3) -> list[dict]: ...
    def movie_details(self, tmdb_id: int, language: str,
                      append: tuple[str,...] = ("videos","release_dates","images")) -> dict: ...
    def image_base_url(self) -> str: ...                 # cached /configuration secure_base_url
    def build_image_url(self, path: str, size: str) -> str: ...
```
`source` ∈ `{"upcoming","now_playing","popular","trending_day","trending_week"}` (maps to endpoints).

### `backend/marquee/tmdb/curator.py` (pure/deterministic where possible)
```python
def discover(client: TMDBClient, sources: list[str], region: str, language: str,
             count: int, pages: int = 3) -> list[MovieCandidate]: ...
def pick_best_trailer(videos: list[dict], language: str) -> TrailerVideo | None: ...
def extract_digital_date(release_dates_results: list[dict], region: str) -> tuple[datetime | None, str]: ...
def enrich(client: TMDBClient, cand: MovieCandidate, region: str, language: str) -> EnrichedMovie: ...
```

### `backend/marquee/downloader.py`
```python
@dataclass
class ProbeResult:
    ok: bool; duration: int | None; title: str | None; has_maxheight: bool; availability: str | None

@dataclass
class DownloadResult:
    path: str; title: str | None; duration: int | None; ext: str; video_id: str

class DownloadFailed(Exception):
    def __init__(self, kind: ErrorKind, message: str): ...

class TrailerDownloader:
    def __init__(self, config: Config, on_progress=None): ...     # on_progress(tmdb_id, pct, speed, eta)
    def probe(self, url: str) -> ProbeResult: ...
    def download(self, url: str, dest_dir: str, tmdb_id: int) -> DownloadResult: ...   # raises DownloadFailed
```

### `backend/marquee/library/writer.py`
```python
@dataclass
class WrittenMovie:
    folder: str; video_path: str; nfo_path: str; poster_path: str | None; backdrop_path: str | None

class LibraryWriter:
    def __init__(self, library_dir: str, client: TMDBClient): ...
    @staticmethod
    def sanitize(name: str) -> str: ...
    def folder_name(self, title: str, year: int | None, tmdb_id: int) -> str: ...
    def render_nfo(self, m: EnrichedMovie) -> str: ...            # returns XML text
    def write_movie(self, m: EnrichedMovie, source_video: str) -> WrittenMovie: ...
    def delete_movie(self, folder: str) -> None: ...
```

### `backend/marquee/library/reaper.py`
```python
class Reaper:
    def __init__(self, store: Store, writer: LibraryWriter, jellyfin: "JellyfinClient | None",
                 now_fn=..., grace_days: int = 0, tz: str = "UTC", count: int = 50): ...
    def find_expired(self, movies: list[Movie]) -> list[Movie]: ...   # digital_date+grace passed, not pinned
    def expire(self, m: Movie) -> None: ...                            # delete folder + JF item + mark EXPIRED
```

### `backend/marquee/jellyfin.py`
```python
class JellyfinClient:
    def __init__(self, url: str, api_key: str, username: str | None = None,
                 password: str | None = None, session: httpx.Client | None = None): ...
    def test(self) -> bool: ...                       # GET /System/Info with key
    def refresh_library(self) -> None: ...            # POST /Library/Refresh
    def authenticate(self) -> str: ...                # POST /Users/AuthenticateByName -> admin token (cached)
    def find_item_by_tmdb(self, tmdb_id: int) -> str | None: ...   # GET /Items?...anyProviderIdEquals=tmdb.<id>
    def delete_item(self, item_id: str) -> None: ...  # DELETE /Items/{id} with admin token
```

### `backend/marquee/pipeline.py`
```python
@dataclass
class RunSummary:
    discovered:int; downloaded:int; skipped:int; failed:int; expired:int

class RefreshPipeline:
    def __init__(self, client: TMDBClient, downloader: TrailerDownloader, writer: LibraryWriter,
                 reaper: Reaper, jellyfin: "JellyfinClient | None", store: Store,
                 config: Config, broadcaster: "Broadcaster"): ...
    def run(self) -> RunSummary: ...      # discover→enrich→download→write→scan (idempotent)
```

### `backend/marquee/scheduler.py`
```python
class Scheduler:
    def __init__(self, pipeline: RefreshPipeline, reaper: Reaper, store: Store, config: Config): ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def trigger_refresh(self) -> None: ...    # single-flight (no overlap)
    def trigger_reap(self) -> None: ...
    def status(self) -> dict: ...             # next_refresh, next_reap, running
```

### `backend/marquee/api/` — FastAPI (`app.py` factory, `routes.py`, `sse.py`)
Routes (all `/api`): `GET /movies`, `GET /movies/{id}`, `POST /movies/{id}/download`, `DELETE /movies/{id}`, `POST /movies/{id}/pin`, `GET /settings`, `PUT /settings`, `POST /run`, `POST /reap`, `GET /activity` (SSE), `GET /status`, `GET /health`, `POST /ytdlp/update`, `POST /jellyfin/test`. SPA served from `static/` via `StaticFiles(html=True)` + catch-all → `index.html`; `/api` never shadowed. `Broadcaster` (`sse.py`) fans progress/log events to SSE subscribers via an asyncio queue.

### `backend/marquee/__main__.py`
CLI: `python -m marquee discover` (dry-run print top-N), `run` (one pipeline pass), `reap`, `serve` (uvicorn).

---

## Frontend contract — `frontend/`

Vite + React + TypeScript. `src/types.ts` mirrors the API JSON (Movie, Status, Config, Activity, Status summary). `src/api.ts` typed fetch client. Pages: `DashboardPage`, `SettingsPage`, `ActivityPage`. Components: `MovieCard` (poster, title, status pill, streaming-countdown badge, pin, menu), `StatusPill`, `CountdownBadge`, `ActivityLog`, `StatusBar`, `SettingsForm`. Tests: Vitest + React Testing Library. Design applied via **frontend-design** skill. API base same-origin `/api`.

---

## API JSON & SSE Contract (authoritative — resolves Plan 2 ↔ Plan 3 boundary)

These shapes are the source of truth for the producer (Plan 2 routes) **and** the consumer (Plan 3 typed client). Where a plan's draft differed, **this section wins**.

- **`serialize_movie(m) -> dict`**: all `Movie` fields (datetimes as ISO strings, `status` as its value) **plus** three API-added fields:
  - `poster_url: str | None` — `https://image.tmdb.org/t/p/w500{poster_path}` or `None`.
  - `backdrop_url: str | None` — `https://image.tmdb.org/t/p/w1280{backdrop_path}` or `None`.
  - `download_pct: float | None` — `None` at rest; live progress is delivered via the SSE `progress` event and merged client-side.
- **`GET /api/movies` / `GET /api/movies/{id}`** → `serialize_movie` (list / single). 404 if absent.
- **`POST /api/movies/{id}/pin`** → the updated movie via `serialize_movie` (not `{pinned}`).
- **`POST /api/movies/{id}/download`** → `{"status": "queued"}`. **`DELETE /api/movies/{id}`** → `{"status": "expired"}`.
- **`GET /api/settings`** → a **flat public `Config`** dict (secrets `tmdb_token`/`jellyfin_api_key`/`jellyfin_pass` masked as `"***"` when set). **`PUT /api/settings`** (body = partial `{key: value}`) applies to `settings` rows and returns the **flat effective public `Config`**.
- **`GET /api/status`** → flat **`StatusSummary`**: `{ "next_refresh": str|null, "next_reap": str|null, "running": bool, "counts": {"ready","queued","downloading","failed","expired": int}, "disk": {"used_gb","free_gb","total_gb": float}, "ytdlp_version": str }` (disk via `shutil.disk_usage(library_dir)`).
- **`POST /api/ytdlp/update`** → `{"version": str}` (reports current yt-dlp version; the real self-update runs in the container entrypoint `yt-dlp -U` on restart). **`POST /api/jellyfin/test`** → `{"ok": bool, "error"?: str}`. **`GET /api/health`** → `{"status": "ok"}`.
- **`GET /api/activity`** (SSE, `text/event-stream`): each `data:` line is one JSON object, a tagged union:
  - `{"type": "log", "entry": {ts, level, event, tmdb_id, message}}` — for backlog rows and new log events.
  - `{"type": "progress", "tmdb_id": int, "pct": float, "speed": float|null, "eta": int|null}` — download progress.
  - The `Broadcaster.publish(event: dict)` is **synchronous** (`Queue.put_nowait`) so a worker-thread pipeline can emit; the async SSE endpoint drains the thread-safe queue. Log-row backlog is wrapped as `{"type":"log","entry":row}` before yielding.
- **SPA mount is owned by Plan 2** `create_app(context)` via `AppContext.static_dir` + the `/{full_path:path}` catch-all (never shadows `/api`, falls back to `index.html`). **Plan 3 does NOT add a separate `mount_spa()`** — it sets Vite `outDir` to `backend/marquee/api/static` and passes that dir as `static_dir`.
- **Deferred (documented, not silent):** `MAX_SIZE_GB` LRU overflow eviction (spec §4.8/§10/§15) is **not** implemented in Plans 1–3 (spec-optional, default `0`=off); tracked for a post-v1 iteration.

---

## Test conventions

- **pytest**; HTTP mocked with `respx` (httpx) — no real network in unit tests. One `e2e` test may hit real TMDB read-only (skipped without `TMDB_TOKEN`).
- **Injected clock:** pass `now_fn` (default `lambda: datetime.now(tz=UTC)`) so expiry/date tests use a frozen clock.
- **Golden files:** `tests/golden/movie.nfo` for NFO rendering.
- **yt-dlp mocked:** patch `yt_dlp.YoutubeDL` in downloader tests; assert options dict (format string, merge_output_format, outtmpl, paths) and simulate `requested_downloads`.
- **Frontend:** Vitest + RTL; mock `fetch`/api client; test rendering + interactions, not visuals.
- **Commits:** conventional (`feat:`, `test:`, `chore:`), one per completed task per the skill; final single integration commit follows the user's commit-workflow preference at execution time.
