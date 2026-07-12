# Marquee Backend Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Marquee's backend core so that `python -m marquee discover` prints a ranked, enriched top-N list of TMDB movies with digital release dates, with all unit tests green.

**Architecture:** A `marquee` Python package under `backend/` with pure/deterministic curation logic layered over a thin authenticated TMDB HTTP client. Config is loaded from env (overlaid by later-editable settings), movie/activity/settings state is persisted in SQLite, and a small argparse CLI wires the client and curator together to print a table. Everything is TDD: HTTP is mocked with `respx`, the DB uses a `tmp_path` file, and curation is tested with tiny inline JSON fixtures.

**Tech Stack:** Python 3.13, httpx, FastAPI/uvicorn/apscheduler/yt-dlp/pydantic (declared now, consumed by later plans), SQLite (stdlib `sqlite3`), pytest + respx + ruff.

## Global Constraints

- **Python 3.13**, `pyproject.toml` (PEP 621), package name `marquee`, src under `backend/`.
- **TMDB auth:** v4 **Bearer** read token (`Authorization: Bearer <token>`). Base `https://api.themoviedb.org/3`. Concurrency ≤5; on HTTP 429 respect `Retry-After`. Cache `/configuration`.
- **TMDB release types:** 1 Premiere, 2 Theatrical-ltd, 3 Theatrical, **4 Digital**, 5 Physical, 6 TV. Digital-date fallback chain: region type-4 → US type-4 → earliest type-4 anywhere → type-5 → type-6 → None(keep).
- **Images:** poster `w500`, backdrop `w1280`, via `secure_base_url` from `/configuration`.
- **Time:** store timestamps UTC-aware; compare expiry end-of-day in configured `TZ`.
- **Test conventions:** pytest; HTTP mocked with `respx` (no real network in unit tests); one `e2e` test may hit real TMDB read-only (skipped without `TMDB_TOKEN`). Conventional commits (`feat:`, `test:`, `chore:`), one per completed task.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/pyproject.toml` | PEP 621 project metadata, runtime + dev deps, pytest/ruff config, `marquee` console script. |
| `backend/marquee/__init__.py` | Package marker + `__version__`. |
| `backend/marquee/models.py` | Shared dataclasses/enums: `Status`, `ErrorKind`, `MovieCandidate`, `TrailerVideo`, `EnrichedMovie`, `Movie`. |
| `backend/marquee/config.py` | `Config` dataclass + `load_config(env, overrides)` (SOURCES comma parse, type coercion). |
| `backend/marquee/store.py` | SQLite access layer: schema creation, movies CRUD, activity log, settings. |
| `backend/marquee/tmdb/__init__.py` | `marquee.tmdb` subpackage marker. |
| `backend/marquee/tmdb/client.py` | Authed TMDB HTTP: list endpoints, detail fetch, cached `/configuration`, image URL build, 429 backoff. |
| `backend/marquee/tmdb/curator.py` | Merge/dedupe/rank/top-N discover, best-trailer selection, digital-date fallback chain, enrich. |
| `backend/marquee/__main__.py` | CLI entrypoint; `discover` subcommand prints the ranked enriched table. |
| `backend/tests/test_version.py` | Proves the pytest harness runs. |
| `backend/tests/test_models.py` | Construction + `TrailerVideo.youtube_url`. |
| `backend/tests/test_config.py` | Defaults, env override, sources parsing, overrides precedence. |
| `backend/tests/test_store.py` | Round-trip, status filter, JSON columns, pinned toggle, activity, settings. |
| `backend/tests/test_tmdb_client.py` | Bearer auth, pagination, 429 backoff, details append, cached image URL. |
| `backend/tests/test_curator.py` | Trailer ordering, full digital-date fallback chain, discover dedupe/rank, enrich. |
| `backend/tests/test_cli.py` | `cmd_discover` renders a table with title + digital date via a mocked client. |

**Commands run from `backend/`** (pytest `rootdir` = `backend/`, `pythonpath = ["."]` so `import marquee` resolves).

---

### Task 1: Project scaffold + first test

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/marquee/__init__.py`
- Test: `backend/tests/test_version.py`

**Interfaces:**
- Consumes: nothing.
- Produces: importable package `marquee` with `marquee.__version__ == "0.1.0"`; pytest configured (`pythonpath = ["."]`, `testpaths = ["tests"]`) so all later tasks run `cd backend && python -m pytest ...`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_version.py`:

```python
from marquee import __version__


def test_version():
    assert __version__ == "0.1.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_version.py -v`
Expected: FAIL — collection error `ModuleNotFoundError: No module named 'marquee'` (package + config not created yet).

- [ ] **Step 3: Write the scaffolding**

Create `backend/pyproject.toml` (complete file):

```toml
[project]
name = "marquee"
version = "0.1.0"
description = "Self-hosted Coming-Soon trailer library for Jellyfin, driven by TMDB."
requires-python = ">=3.13"
dependencies = [
  "httpx>=0.27",
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "apscheduler>=3.10",
  "yt-dlp[default]>=2024.8.6",
  "pydantic>=2.7",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "respx>=0.21",
  "ruff>=0.5",
]

[project.scripts]
marquee = "marquee.__main__:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["."]
include = ["marquee*"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
addopts = "-q"

[tool.ruff]
line-length = 100
target-version = "py313"
```

Create `backend/marquee/__init__.py` (complete file):

```python
"""Marquee — self-hosted Coming-Soon trailer library for Jellyfin."""

__version__ = "0.1.0"
```

- [ ] **Step 4: Install dev deps and run the test to verify it passes**

Run: `cd backend && python -m pip install -e ".[dev]" && python -m pytest tests/test_version.py -v`
Expected: PASS — `test_version PASSED`.

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/marquee/__init__.py backend/tests/test_version.py
git commit -m "chore: scaffold marquee backend package and pytest harness"
```

---

### Task 2: Data model (`models.py`)

**Files:**
- Create: `backend/marquee/models.py`
- Test: `backend/tests/test_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces (used by every later task, exact names/types):
  - `class Status(str, Enum)` values `QUEUED/DOWNLOADING/READY/FAILED/EXPIRED`.
  - `class ErrorKind(str, Enum)` values `BOT_CHECK/AGE_GATED/REGION_BLOCKED/UNAVAILABLE/NO_FORMAT/NO_TRAILER/ERROR`.
  - `@dataclass MovieCandidate(tmdb_id:int, title:str, year:int|None, overview:str, popularity:float, poster_path:str|None, backdrop_path:str|None, source:str, release_date:str|None)`.
  - `@dataclass TrailerVideo(key, site, type, official:bool, size:int, iso_639_1, published_at)` with `@property youtube_url -> str`.
  - `@dataclass EnrichedMovie(...)` per contract (defaults: `genres=[]`, `studios=[]`, `certification=None`, `premiere_date=None`, `digital_date=None`, `digital_date_source="none"`, `youtube_key=None`, `trailer=None`).
  - `@dataclass Movie(...)` — 26 fields per contract §9, persisted row.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_models.py`:

```python
from datetime import datetime, timezone

from marquee.models import (
    EnrichedMovie,
    ErrorKind,
    Movie,
    MovieCandidate,
    Status,
    TrailerVideo,
)


def test_status_and_errorkind_values():
    assert Status.READY.value == "ready"
    assert Status.EXPIRED.value == "expired"
    assert ErrorKind.NO_TRAILER.value == "no_trailer"
    assert ErrorKind.BOT_CHECK.value == "bot_check"


def test_trailer_youtube_url():
    tv = TrailerVideo(
        key="abc123",
        site="YouTube",
        type="Trailer",
        official=True,
        size=1080,
        iso_639_1="en",
        published_at="",
    )
    assert tv.youtube_url == "https://www.youtube.com/watch?v=abc123"


def test_candidate_construction():
    c = MovieCandidate(
        tmdb_id=1,
        title="A",
        year=2026,
        overview="ov",
        popularity=9.9,
        poster_path="/p.jpg",
        backdrop_path=None,
        source="upcoming",
        release_date="2026-01-01",
    )
    assert c.tmdb_id == 1 and c.source == "upcoming"


def test_enriched_defaults():
    em = EnrichedMovie(
        tmdb_id=1,
        title="T",
        year=2026,
        overview="",
        popularity=1.0,
        source="upcoming",
        poster_path=None,
        backdrop_path=None,
        runtime=None,
    )
    assert em.genres == []
    assert em.studios == []
    assert em.digital_date_source == "none"
    assert em.trailer is None
    assert em.youtube_key is None


def test_movie_construction():
    now = datetime.now(timezone.utc)
    m = Movie(
        tmdb_id=1,
        title="T",
        year=2026,
        overview="",
        runtime=100,
        genres=["Action"],
        studios=["Studio"],
        certification="PG-13",
        premiere_date="2026-01-01",
        digital_date=None,
        digital_date_source="none",
        region="US",
        popularity=1.0,
        poster_path=None,
        backdrop_path=None,
        youtube_key=None,
        status=Status.QUEUED,
        file_path=None,
        folder=None,
        jellyfin_item_id=None,
        pinned=False,
        added_at=now,
        expires_at=None,
        last_checked=None,
        error_kind=None,
        error_msg=None,
    )
    assert m.status is Status.QUEUED
    assert m.genres == ["Action"]
    assert m.pinned is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'marquee.models'`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/marquee/models.py` (complete file):

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
    source: str
    release_date: str | None


@dataclass
class TrailerVideo:
    key: str
    site: str
    type: str
    official: bool
    size: int
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
    runtime: int | None
    genres: list[str] = field(default_factory=list)
    studios: list[str] = field(default_factory=list)
    certification: str | None = None
    premiere_date: str | None = None
    digital_date: datetime | None = None
    digital_date_source: str = "none"
    youtube_key: str | None = None
    trailer: TrailerVideo | None = None


@dataclass
class Movie:
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

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_models.py -v`
Expected: PASS — 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/marquee/models.py backend/tests/test_models.py
git commit -m "feat: add marquee data model dataclasses and enums"
```

---

### Task 3: Config (`config.py`)

**Files:**
- Create: `backend/marquee/config.py`
- Test: `backend/tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `@dataclass Config(tmdb_token:str, sources:list[str], count:int=50, region:str="US", language:str="en-US", container:str="mkv", max_height:int=1080, refresh_cron:str="0 3 * * *", reaper_cron:str="0 4 * * *", grace_days:int=0, tz:str="UTC", library_dir:str="/library", config_dir:str="/config", max_size_gb:float=0.0, jellyfin_url:str|None=None, jellyfin_api_key:str|None=None, jellyfin_user:str|None=None, jellyfin_pass:str|None=None, ytdlp_cookies:str|None=None, ytdlp_proxy:str|None=None)`. `sources` defaults to `["upcoming","now_playing"]` via `default_factory`.
  - `load_config(env: Mapping[str,str], overrides: dict|None=None) -> Config`. Both `env` and `overrides` are keyed by the **uppercase env-var names** of spec §10 (e.g. `"SOURCES"`, `"COUNT"`); `overrides` overlay `env`. Empty-string values fall back to defaults. (`overrides` is an env-style overlay — NOT the DB settings rows; those go through `apply_setting_overrides`.)
  - `apply_setting_overrides(config: Config, rows: Mapping[str,str]) -> Config` (see contract). Applies DB `settings` rows keyed by **lowercase Config field names** (e.g. `count`, `sources`), coercing each string to the field's current type; unknown/uncoercible keys ignored. Used by the `/settings` route and startup wiring.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_config.py`:

```python
from marquee.config import Config, load_config


def test_defaults():
    c = load_config({"TMDB_TOKEN": "tok"})
    assert isinstance(c, Config)
    assert c.tmdb_token == "tok"
    assert c.sources == ["upcoming", "now_playing"]
    assert c.count == 50
    assert c.region == "US"
    assert c.language == "en-US"
    assert c.container == "mkv"
    assert c.max_height == 1080
    assert c.grace_days == 0
    assert c.tz == "UTC"
    assert c.max_size_gb == 0.0
    assert c.jellyfin_url is None


def test_env_override_with_coercion():
    c = load_config(
        {
            "TMDB_TOKEN": "tok",
            "COUNT": "25",
            "REGION": "GB",
            "GRACE_DAYS": "3",
            "MAX_HEIGHT": "720",
            "MAX_SIZE_GB": "12.5",
            "JELLYFIN_URL": "http://jf:8096",
        }
    )
    assert c.count == 25
    assert c.region == "GB"
    assert c.grace_days == 3
    assert c.max_height == 720
    assert c.max_size_gb == 12.5
    assert c.jellyfin_url == "http://jf:8096"


def test_sources_parsing_trims_and_splits():
    c = load_config({"TMDB_TOKEN": "tok", "SOURCES": "upcoming, popular ,trending_week"})
    assert c.sources == ["upcoming", "popular", "trending_week"]


def test_empty_string_falls_back_to_default():
    c = load_config({"TMDB_TOKEN": "tok", "REGION": "", "SOURCES": ""})
    assert c.region == "US"
    assert c.sources == ["upcoming", "now_playing"]


def test_overrides_win_over_env():
    c = load_config({"TMDB_TOKEN": "tok", "COUNT": "25"}, overrides={"COUNT": "99"})
    assert c.count == 99


def test_apply_setting_overrides_coerces_by_field_type():
    from marquee.config import apply_setting_overrides

    base = load_config({"TMDB_TOKEN": "tok"})
    out = apply_setting_overrides(
        base,
        {"count": "25", "max_size_gb": "5.5", "sources": "upcoming, popular", "region": "GB"},
    )
    assert out.count == 25
    assert out.max_size_gb == 5.5
    assert out.sources == ["upcoming", "popular"]
    assert out.region == "GB"
    assert out.tmdb_token == "tok"  # untouched fields preserved


def test_apply_setting_overrides_ignores_unknown_and_bad():
    from marquee.config import apply_setting_overrides

    base = load_config({"TMDB_TOKEN": "tok"})
    out = apply_setting_overrides(base, {"nope": "x", "count": "notanint"})
    assert out.count == 50  # unknown key ignored; uncoercible value leaves default
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'marquee.config'`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/marquee/config.py` (complete file):

```python
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
    ytdlp_proxy: str | None = None


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
        ytdlp_proxy=get("YTDLP_PROXY"),
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_config.py -v`
Expected: PASS — 7 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/marquee/config.py backend/tests/test_config.py
git commit -m "feat: add Config, load_config, and apply_setting_overrides"
```

---

### Task 4: SQLite store (`store.py`)

**Files:**
- Create: `backend/marquee/store.py`
- Test: `backend/tests/test_store.py`

**Interfaces:**
- Consumes: `marquee.models.Movie`, `marquee.models.Status`.
- Produces (`class Store`):
  - `__init__(self, db_path: str)` — opens `sqlite3` connection (`check_same_thread=False`, `Row` factory), creates `movies` / `activity_log` / `settings` schema if absent.
  - `upsert_movie(self, m: Movie) -> None`, `get_movie(self, tmdb_id:int) -> Movie|None`, `list_movies(self, statuses:list[Status]|None=None) -> list[Movie]` (ordered popularity desc).
  - `set_status(self, tmdb_id:int, status:Status, **fields) -> None` — updates `status` plus any movie column in `**fields`; datetimes/lists/`Status`/bools auto-serialized.
  - `set_pinned(self, tmdb_id:int, pinned:bool) -> None`, `delete_movie(self, tmdb_id:int) -> None`.
  - `log(self, level:str, event:str, message:str, tmdb_id:int|None=None) -> None`, `recent_activity(self, limit:int=200) -> list[dict]` (newest first).
  - `get_setting(self, key:str) -> str|None`, `set_setting(self, key:str, value:str) -> None`, `all_settings(self) -> dict[str,str]`.
  - Genres/studios stored as JSON text columns; datetimes stored as UTC-aware ISO strings and parsed back to aware datetimes.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_store.py`:

```python
from datetime import datetime, timezone

from marquee.models import Movie, Status
from marquee.store import Store


def _movie(tmdb_id: int = 1, status: Status = Status.QUEUED, **kw) -> Movie:
    base = dict(
        tmdb_id=tmdb_id,
        title="T",
        year=2026,
        overview="ov",
        runtime=100,
        genres=["Action", "Drama"],
        studios=["Studio"],
        certification="PG-13",
        premiere_date="2026-01-01",
        digital_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
        digital_date_source="region",
        region="US",
        popularity=9.9,
        poster_path="/p.jpg",
        backdrop_path="/b.jpg",
        youtube_key="yt",
        status=status,
        file_path=None,
        folder=None,
        jellyfin_item_id=None,
        pinned=False,
        added_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        expires_at=None,
        last_checked=None,
        error_kind=None,
        error_msg=None,
    )
    base.update(kw)
    return Movie(**base)


def test_upsert_and_get_roundtrip(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    store.upsert_movie(_movie())
    got = store.get_movie(1)
    assert got is not None
    assert got.title == "T"
    assert got.genres == ["Action", "Drama"]
    assert got.studios == ["Studio"]
    assert got.digital_date == datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert got.added_at == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert got.status is Status.QUEUED
    assert got.pinned is False


def test_upsert_replaces_existing(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    store.upsert_movie(_movie(1, popularity=1.0))
    store.upsert_movie(_movie(1, popularity=5.0))
    assert store.get_movie(1).popularity == 5.0
    assert len(store.list_movies()) == 1


def test_get_missing_returns_none(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    assert store.get_movie(999) is None


def test_list_status_filter(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    store.upsert_movie(_movie(1, status=Status.READY, popularity=2.0))
    store.upsert_movie(_movie(2, status=Status.FAILED, popularity=9.0))
    ready = store.list_movies([Status.READY])
    assert [m.tmdb_id for m in ready] == [1]
    all_movies = store.list_movies()
    assert [m.tmdb_id for m in all_movies] == [2, 1]  # popularity desc


def test_set_status_and_extra_fields(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    store.upsert_movie(_movie(1))
    store.set_status(1, Status.READY, file_path="/x.mkv", folder="/f")
    got = store.get_movie(1)
    assert got.status is Status.READY
    assert got.file_path == "/x.mkv"
    assert got.folder == "/f"


def test_set_status_serializes_datetime_field(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    store.upsert_movie(_movie(1))
    when = datetime(2026, 9, 9, tzinfo=timezone.utc)
    store.set_status(1, Status.READY, last_checked=when)
    assert store.get_movie(1).last_checked == when


def test_set_pinned_toggle(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    store.upsert_movie(_movie(1))
    store.set_pinned(1, True)
    assert store.get_movie(1).pinned is True
    store.set_pinned(1, False)
    assert store.get_movie(1).pinned is False


def test_delete_movie(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    store.upsert_movie(_movie(1))
    store.delete_movie(1)
    assert store.get_movie(1) is None


def test_activity_log_recent_newest_first(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    store.log("info", "discover", "found 5", tmdb_id=1)
    store.log("error", "download", "failed", tmdb_id=2)
    recent = store.recent_activity(limit=10)
    assert len(recent) == 2
    assert recent[0]["event"] == "download"
    assert recent[0]["tmdb_id"] == 2
    assert recent[0]["level"] == "error"


def test_settings_roundtrip(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    assert store.get_setting("count") is None
    store.set_setting("count", "25")
    assert store.get_setting("count") == "25"
    store.set_setting("count", "30")
    assert store.get_setting("count") == "30"
    store.set_setting("region", "GB")
    assert store.all_settings() == {"count": "30", "region": "GB"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'marquee.store'`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/marquee/store.py` (complete file):

```python
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from .models import Movie, Status

_COLUMNS = [
    "tmdb_id",
    "title",
    "year",
    "overview",
    "runtime",
    "genres",
    "studios",
    "certification",
    "premiere_date",
    "digital_date",
    "digital_date_source",
    "region",
    "popularity",
    "poster_path",
    "backdrop_path",
    "youtube_key",
    "status",
    "file_path",
    "folder",
    "jellyfin_item_id",
    "pinned",
    "added_at",
    "expires_at",
    "last_checked",
    "error_kind",
    "error_msg",
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS movies (
    tmdb_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    year INTEGER,
    overview TEXT,
    runtime INTEGER,
    genres TEXT,
    studios TEXT,
    certification TEXT,
    premiere_date TEXT,
    digital_date TEXT,
    digital_date_source TEXT,
    region TEXT,
    popularity REAL,
    poster_path TEXT,
    backdrop_path TEXT,
    youtube_key TEXT,
    status TEXT,
    file_path TEXT,
    folder TEXT,
    jellyfin_item_id TEXT,
    pinned INTEGER,
    added_at TEXT,
    expires_at TEXT,
    last_checked TEXT,
    error_kind TEXT,
    error_msg TEXT
);
CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    level TEXT,
    event TEXT,
    tmdb_id INTEGER,
    message TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def _dt_to_str(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat()


def _str_to_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _serialize_field(value):
    if isinstance(value, Status):
        return value.value
    if isinstance(value, datetime):
        return _dt_to_str(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    if isinstance(value, bool):
        return 1 if value else 0
    return value


class Store:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ----- movies -----
    def _movie_to_row(self, m: Movie) -> dict:
        return {
            "tmdb_id": m.tmdb_id,
            "title": m.title,
            "year": m.year,
            "overview": m.overview,
            "runtime": m.runtime,
            "genres": json.dumps(m.genres),
            "studios": json.dumps(m.studios),
            "certification": m.certification,
            "premiere_date": m.premiere_date,
            "digital_date": _dt_to_str(m.digital_date),
            "digital_date_source": m.digital_date_source,
            "region": m.region,
            "popularity": m.popularity,
            "poster_path": m.poster_path,
            "backdrop_path": m.backdrop_path,
            "youtube_key": m.youtube_key,
            "status": m.status.value,
            "file_path": m.file_path,
            "folder": m.folder,
            "jellyfin_item_id": m.jellyfin_item_id,
            "pinned": 1 if m.pinned else 0,
            "added_at": _dt_to_str(m.added_at),
            "expires_at": _dt_to_str(m.expires_at),
            "last_checked": _dt_to_str(m.last_checked),
            "error_kind": m.error_kind,
            "error_msg": m.error_msg,
        }

    def _row_to_movie(self, row: sqlite3.Row) -> Movie:
        return Movie(
            tmdb_id=row["tmdb_id"],
            title=row["title"],
            year=row["year"],
            overview=row["overview"],
            runtime=row["runtime"],
            genres=json.loads(row["genres"] or "[]"),
            studios=json.loads(row["studios"] or "[]"),
            certification=row["certification"],
            premiere_date=row["premiere_date"],
            digital_date=_str_to_dt(row["digital_date"]),
            digital_date_source=row["digital_date_source"],
            region=row["region"],
            popularity=row["popularity"],
            poster_path=row["poster_path"],
            backdrop_path=row["backdrop_path"],
            youtube_key=row["youtube_key"],
            status=Status(row["status"]),
            file_path=row["file_path"],
            folder=row["folder"],
            jellyfin_item_id=row["jellyfin_item_id"],
            pinned=bool(row["pinned"]),
            added_at=_str_to_dt(row["added_at"]),
            expires_at=_str_to_dt(row["expires_at"]),
            last_checked=_str_to_dt(row["last_checked"]),
            error_kind=row["error_kind"],
            error_msg=row["error_msg"],
        )

    def upsert_movie(self, m: Movie) -> None:
        row = self._movie_to_row(m)
        cols = ",".join(_COLUMNS)
        placeholders = ",".join("?" for _ in _COLUMNS)
        self._conn.execute(
            f"INSERT OR REPLACE INTO movies ({cols}) VALUES ({placeholders})",
            [row[c] for c in _COLUMNS],
        )
        self._conn.commit()

    def get_movie(self, tmdb_id: int) -> Movie | None:
        cur = self._conn.execute("SELECT * FROM movies WHERE tmdb_id = ?", [tmdb_id])
        row = cur.fetchone()
        return self._row_to_movie(row) if row else None

    def list_movies(self, statuses: list[Status] | None = None) -> list[Movie]:
        if statuses:
            marks = ",".join("?" for _ in statuses)
            cur = self._conn.execute(
                f"SELECT * FROM movies WHERE status IN ({marks}) ORDER BY popularity DESC",
                [s.value for s in statuses],
            )
        else:
            cur = self._conn.execute("SELECT * FROM movies ORDER BY popularity DESC")
        return [self._row_to_movie(r) for r in cur.fetchall()]

    def set_status(self, tmdb_id: int, status: Status, **fields) -> None:
        sets = ["status = ?"]
        params: list = [status.value]
        for key, value in fields.items():
            sets.append(f"{key} = ?")
            params.append(_serialize_field(value))
        params.append(tmdb_id)
        self._conn.execute(
            f"UPDATE movies SET {', '.join(sets)} WHERE tmdb_id = ?", params
        )
        self._conn.commit()

    def set_pinned(self, tmdb_id: int, pinned: bool) -> None:
        self._conn.execute(
            "UPDATE movies SET pinned = ? WHERE tmdb_id = ?",
            [1 if pinned else 0, tmdb_id],
        )
        self._conn.commit()

    def delete_movie(self, tmdb_id: int) -> None:
        self._conn.execute("DELETE FROM movies WHERE tmdb_id = ?", [tmdb_id])
        self._conn.commit()

    # ----- activity -----
    def log(self, level: str, event: str, message: str, tmdb_id: int | None = None) -> None:
        self._conn.execute(
            "INSERT INTO activity_log (ts, level, event, tmdb_id, message) VALUES (?,?,?,?,?)",
            [datetime.now(timezone.utc).isoformat(), level, event, tmdb_id, message],
        )
        self._conn.commit()

    def recent_activity(self, limit: int = 200) -> list[dict]:
        cur = self._conn.execute(
            "SELECT id, ts, level, event, tmdb_id, message FROM activity_log "
            "ORDER BY id DESC LIMIT ?",
            [limit],
        )
        return [dict(r) for r in cur.fetchall()]

    # ----- settings -----
    def get_setting(self, key: str) -> str | None:
        cur = self._conn.execute("SELECT value FROM settings WHERE key = ?", [key])
        row = cur.fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", [key, value]
        )
        self._conn.commit()

    def all_settings(self) -> dict[str, str]:
        cur = self._conn.execute("SELECT key, value FROM settings")
        return {r["key"]: r["value"] for r in cur.fetchall()}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_store.py -v`
Expected: PASS — 10 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/marquee/store.py backend/tests/test_store.py
git commit -m "feat: add SQLite Store for movies, activity log, and settings"
```

---

### Task 5: TMDB HTTP client (`tmdb/client.py`)

**Files:**
- Create: `backend/marquee/tmdb/__init__.py`
- Create: `backend/marquee/tmdb/client.py`
- Test: `backend/tests/test_tmdb_client.py`

**Interfaces:**
- Consumes: `httpx`.
- Produces (`class TMDBClient`):
  - `__init__(self, token:str, session:httpx.Client|None=None, base_url:str="https://api.themoviedb.org/3")` — sends `Authorization: Bearer <token>`.
  - `list_movies(self, source:str, region:str, language:str, pages:int=3) -> list[dict]` — `source` ∈ `{"upcoming","now_playing","popular","trending_day","trending_week"}` mapped to endpoints; loops pages 1..`pages`, stops early at `total_pages`.
  - `movie_details(self, tmdb_id:int, language:str, append:tuple[str,...]=("videos","release_dates","images")) -> dict`.
  - `image_base_url(self) -> str` — cached `/configuration` `images.secure_base_url`.
  - `build_image_url(self, path:str, size:str) -> str`.
  - Internal `_get` retries on HTTP 429 honoring `Retry-After`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_tmdb_client.py`:

```python
import httpx
import respx

from marquee.tmdb.client import TMDBClient


@respx.mock
def test_bearer_auth_header():
    captured = {}

    def handler(request):
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"page": 1, "results": [], "total_pages": 1})

    respx.get("https://api.themoviedb.org/3/movie/popular").mock(side_effect=handler)
    TMDBClient("mytoken").list_movies("popular", "US", "en-US", pages=1)
    assert captured["auth"] == "Bearer mytoken"


@respx.mock
def test_list_movies_paginates_and_stops_at_total_pages():
    respx.get("https://api.themoviedb.org/3/movie/upcoming", params={"page": "1"}).mock(
        return_value=httpx.Response(
            200, json={"page": 1, "results": [{"id": 1}], "total_pages": 2}
        )
    )
    page2 = respx.get(
        "https://api.themoviedb.org/3/movie/upcoming", params={"page": "2"}
    ).mock(
        return_value=httpx.Response(
            200, json={"page": 2, "results": [{"id": 2}], "total_pages": 2}
        )
    )
    results = TMDBClient("t").list_movies("upcoming", "US", "en-US", pages=3)
    assert [r["id"] for r in results] == [1, 2]
    assert page2.called


@respx.mock
def test_trending_week_endpoint_mapping():
    route = respx.get("https://api.themoviedb.org/3/trending/movie/week").mock(
        return_value=httpx.Response(200, json={"page": 1, "results": [{"id": 7}], "total_pages": 1})
    )
    results = TMDBClient("t").list_movies("trending_week", "US", "en-US", pages=1)
    assert route.called
    assert results[0]["id"] == 7


@respx.mock
def test_429_retry_after_backoff():
    respx.get("https://api.themoviedb.org/3/movie/now_playing").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}, json={}),
            httpx.Response(200, json={"page": 1, "results": [{"id": 9}], "total_pages": 1}),
        ]
    )
    results = TMDBClient("t").list_movies("now_playing", "US", "en-US", pages=1)
    assert [r["id"] for r in results] == [9]


@respx.mock
def test_movie_details_appends_response():
    captured = {}

    def handler(request):
        captured["append"] = request.url.params.get("append_to_response")
        captured["language"] = request.url.params.get("language")
        return httpx.Response(200, json={"id": 5, "title": "X"})

    respx.get("https://api.themoviedb.org/3/movie/5").mock(side_effect=handler)
    data = TMDBClient("t").movie_details(5, "en-US")
    assert data["title"] == "X"
    assert captured["append"] == "videos,release_dates,images"
    assert captured["language"] == "en-US"


@respx.mock
def test_build_image_url_uses_cached_configuration():
    cfg = respx.get("https://api.themoviedb.org/3/configuration").mock(
        return_value=httpx.Response(
            200, json={"images": {"secure_base_url": "https://image.tmdb.org/t/p/"}}
        )
    )
    client = TMDBClient("t")
    assert client.build_image_url("/abc.jpg", "w500") == "https://image.tmdb.org/t/p/w500/abc.jpg"
    client.build_image_url("/def.jpg", "w1280")
    assert cfg.call_count == 1  # /configuration fetched once and cached
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_tmdb_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'marquee.tmdb'`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/marquee/tmdb/__init__.py` (complete file):

```python
"""TMDB client and curation for Marquee."""
```

Create `backend/marquee/tmdb/client.py` (complete file):

```python
from __future__ import annotations

import time

import httpx

_SOURCE_ENDPOINTS = {
    "upcoming": "/movie/upcoming",
    "now_playing": "/movie/now_playing",
    "popular": "/movie/popular",
    "trending_day": "/trending/movie/day",
    "trending_week": "/trending/movie/week",
}

_MAX_RETRIES = 5


class TMDBClient:
    def __init__(
        self,
        token: str,
        session: httpx.Client | None = None,
        base_url: str = "https://api.themoviedb.org/3",
    ) -> None:
        self.token = token
        self.base_url = base_url.rstrip("/")
        self._session = session or httpx.Client(timeout=30.0)
        self._image_base: str | None = None

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "accept": "application/json"}

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        response: httpx.Response | None = None
        for _ in range(_MAX_RETRIES):
            response = self._session.get(url, headers=self._headers(), params=params)
            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", "1"))
                time.sleep(retry_after)
                continue
            response.raise_for_status()
            return response.json()
        assert response is not None
        response.raise_for_status()
        return response.json()

    def list_movies(
        self, source: str, region: str, language: str, pages: int = 3
    ) -> list[dict]:
        endpoint = _SOURCE_ENDPOINTS[source]
        results: list[dict] = []
        for page in range(1, pages + 1):
            data = self._get(
                endpoint,
                params={"language": language, "region": region, "page": page},
            )
            results.extend(data.get("results", []))
            if page >= data.get("total_pages", 1):
                break
        return results

    def movie_details(
        self,
        tmdb_id: int,
        language: str,
        append: tuple[str, ...] = ("videos", "release_dates", "images"),
    ) -> dict:
        return self._get(
            f"/movie/{tmdb_id}",
            params={"language": language, "append_to_response": ",".join(append)},
        )

    def image_base_url(self) -> str:
        if self._image_base is None:
            data = self._get("/configuration")
            self._image_base = data["images"]["secure_base_url"]
        return self._image_base

    def build_image_url(self, path: str, size: str) -> str:
        return f"{self.image_base_url()}{size}{path}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_tmdb_client.py -v`
Expected: PASS — 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/marquee/tmdb/__init__.py backend/marquee/tmdb/client.py backend/tests/test_tmdb_client.py
git commit -m "feat: add authed TMDB client with pagination, 429 backoff, cached image URLs"
```

---

### Task 6: Curator (`tmdb/curator.py`)

**Files:**
- Create: `backend/marquee/tmdb/curator.py`
- Test: `backend/tests/test_curator.py`

**Interfaces:**
- Consumes: `marquee.tmdb.client.TMDBClient` (only `list_movies` / `movie_details` are called, so tests inject a duck-typed fake); `marquee.models.MovieCandidate/TrailerVideo/EnrichedMovie`.
- Produces:
  - `discover(client, sources, region, language, count, pages=3) -> list[MovieCandidate]` — merges each source's `list_movies`, dedupes by `id` (first occurrence keeps its `source`), ranks by `popularity` desc, truncates to `count`.
  - `pick_best_trailer(videos:list[dict], language:str) -> TrailerVideo|None` — YouTube-only; ordering: `Trailer`<`Teaser`<other, official first, language match first, `size` desc, `published_at` desc.
  - `extract_digital_date(release_dates_results:list[dict], region:str) -> tuple[datetime|None, str]` — aware-UTC datetime + source ∈ `{"region","us","global","physical","tv","none"}`.
  - `enrich(client, cand:MovieCandidate, region:str, language:str) -> EnrichedMovie`. **Clarification (added to contract):** `genres` from `details["genres"][].name`, `studios` from `details["production_companies"][].name`, `certification` from the region entry's first non-empty `certification` in `release_dates`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_curator.py`:

```python
from datetime import datetime, timezone

from marquee.models import MovieCandidate
from marquee.tmdb.curator import (
    discover,
    enrich,
    extract_digital_date,
    pick_best_trailer,
)


class FakeClient:
    def __init__(self, lists=None, details=None):
        self._lists = lists or {}
        self._details = details or {}

    def list_movies(self, source, region, language, pages=3):
        return self._lists.get(source, [])

    def movie_details(self, tmdb_id, language, append=("videos", "release_dates", "images")):
        return self._details[tmdb_id]


def _video(key, vtype="Trailer", official=True, size=1080, lang="en", published="2026-01-01T00:00:00.000Z"):
    return {
        "key": key,
        "site": "YouTube",
        "type": vtype,
        "official": official,
        "size": size,
        "iso_639_1": lang,
        "published_at": published,
    }


# ---- pick_best_trailer ordering ----

def test_trailer_preferred_over_teaser():
    videos = [_video("teaser", vtype="Teaser", size=1080), _video("trailer", size=720)]
    assert pick_best_trailer(videos, "en-US").key == "trailer"


def test_official_preferred_over_unofficial():
    videos = [_video("unoff", official=False, size=1080), _video("off", official=True, size=720)]
    assert pick_best_trailer(videos, "en-US").key == "off"


def test_language_match_preferred():
    videos = [_video("fr", lang="fr", size=1080), _video("en", lang="en", size=720)]
    assert pick_best_trailer(videos, "en-US").key == "en"


def test_larger_size_preferred_then_newer():
    videos = [
        _video("small", size=720, published="2026-05-01T00:00:00.000Z"),
        _video("big", size=1080, published="2026-01-01T00:00:00.000Z"),
    ]
    assert pick_best_trailer(videos, "en-US").key == "big"


def test_newest_published_breaks_tie():
    videos = [
        _video("old", published="2026-01-01T00:00:00.000Z"),
        _video("new", published="2026-03-01T00:00:00.000Z"),
    ]
    assert pick_best_trailer(videos, "en-US").key == "new"


def test_non_youtube_filtered_out():
    vimeo = {
        "key": "v",
        "site": "Vimeo",
        "type": "Trailer",
        "official": True,
        "size": 1080,
        "iso_639_1": "en",
        "published_at": "",
    }
    assert pick_best_trailer([vimeo], "en-US") is None


def test_no_videos_returns_none():
    assert pick_best_trailer([], "en-US") is None


# ---- extract_digital_date full fallback chain ----

def _rd(country, entries):
    return {"iso_3166_1": country, "release_dates": entries}


def _entry(vtype, date, certification=None):
    e = {"type": vtype, "release_date": date}
    if certification is not None:
        e["certification"] = certification
    return e


def test_digital_region_takes_priority():
    rd = [
        _rd("US", [_entry(3, "2026-01-01T00:00:00.000Z"), _entry(4, "2026-03-15T00:00:00.000Z")]),
        _rd("GB", [_entry(4, "2026-02-01T00:00:00.000Z")]),
    ]
    dt, src = extract_digital_date(rd, "US")
    assert src == "region"
    assert dt == datetime(2026, 3, 15, tzinfo=timezone.utc)


def test_digital_falls_back_to_us():
    rd = [_rd("US", [_entry(4, "2026-05-01T00:00:00.000Z")])]
    dt, src = extract_digital_date(rd, "DE")
    assert src == "us"
    assert dt == datetime(2026, 5, 1, tzinfo=timezone.utc)


def test_digital_falls_back_to_global_earliest():
    rd = [
        _rd("FR", [_entry(4, "2026-06-10T00:00:00.000Z")]),
        _rd("JP", [_entry(4, "2026-06-01T00:00:00.000Z")]),
    ]
    dt, src = extract_digital_date(rd, "US")
    assert src == "global"
    assert dt == datetime(2026, 6, 1, tzinfo=timezone.utc)


def test_digital_falls_back_to_physical():
    rd = [_rd("US", [_entry(5, "2026-07-01T00:00:00.000Z")])]
    dt, src = extract_digital_date(rd, "US")
    assert src == "physical"
    assert dt == datetime(2026, 7, 1, tzinfo=timezone.utc)


def test_digital_falls_back_to_tv():
    rd = [_rd("US", [_entry(6, "2026-08-01T00:00:00.000Z")])]
    dt, src = extract_digital_date(rd, "US")
    assert src == "tv"
    assert dt == datetime(2026, 8, 1, tzinfo=timezone.utc)


def test_digital_none_keeps():
    rd = [_rd("US", [_entry(3, "2026-01-01T00:00:00.000Z")])]
    dt, src = extract_digital_date(rd, "US")
    assert dt is None
    assert src == "none"


# ---- discover ----

def test_discover_dedupes_and_ranks_top_n():
    lists = {
        "upcoming": [
            {"id": 1, "title": "A", "popularity": 10, "release_date": "2026-01-01", "overview": "a"},
            {"id": 2, "title": "B", "popularity": 50, "release_date": "2026-02-01", "overview": "b"},
        ],
        "now_playing": [
            {"id": 2, "title": "B", "popularity": 50, "release_date": "2026-02-01", "overview": "b"},
            {"id": 3, "title": "C", "popularity": 30, "release_date": "2026-03-01", "overview": "c"},
        ],
    }
    cands = discover(FakeClient(lists), ["upcoming", "now_playing"], "US", "en-US", count=2)
    assert [c.tmdb_id for c in cands] == [2, 3]
    assert cands[0].year == 2026
    assert cands[0].source == "upcoming"  # first source that surfaced id=2


# ---- enrich ----

def test_enrich_maps_all_fields():
    details = {
        5: {
            "id": 5,
            "title": "Movie Five",
            "overview": "ov",
            "popularity": 42.0,
            "runtime": 120,
            "release_date": "2026-04-01",
            "poster_path": "/p.jpg",
            "backdrop_path": "/b.jpg",
            "genres": [{"name": "Action"}, {"name": "Drama"}],
            "production_companies": [{"name": "Studio X"}],
            "videos": {"results": [_video("yt5")]},
            "release_dates": {
                "results": [
                    _rd("US", [_entry(4, "2026-06-01T00:00:00.000Z", certification="PG-13")])
                ]
            },
        }
    }
    cand = MovieCandidate(
        tmdb_id=5,
        title="Movie Five",
        year=2026,
        overview="ov",
        popularity=42.0,
        poster_path="/p.jpg",
        backdrop_path="/b.jpg",
        source="upcoming",
        release_date="2026-04-01",
    )
    em = enrich(FakeClient(details=details), cand, "US", "en-US")
    assert em.youtube_key == "yt5"
    assert em.trailer is not None and em.trailer.key == "yt5"
    assert em.digital_date == datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert em.digital_date_source == "region"
    assert em.genres == ["Action", "Drama"]
    assert em.studios == ["Studio X"]
    assert em.certification == "PG-13"
    assert em.runtime == 120
    assert em.premiere_date == "2026-04-01"
    assert em.source == "upcoming"


def test_enrich_no_trailer_leaves_youtube_key_none():
    details = {
        6: {
            "id": 6,
            "title": "No Trailer",
            "overview": "",
            "popularity": 1.0,
            "runtime": None,
            "release_date": "2026-04-01",
            "genres": [],
            "production_companies": [],
            "videos": {"results": []},
            "release_dates": {"results": []},
        }
    }
    cand = MovieCandidate(
        tmdb_id=6,
        title="No Trailer",
        year=2026,
        overview="",
        popularity=1.0,
        poster_path=None,
        backdrop_path=None,
        source="popular",
        release_date="2026-04-01",
    )
    em = enrich(FakeClient(details=details), cand, "US", "en-US")
    assert em.youtube_key is None
    assert em.trailer is None
    assert em.digital_date is None
    assert em.digital_date_source == "none"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_curator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'marquee.tmdb.curator'`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/marquee/tmdb/curator.py` (complete file):

```python
from __future__ import annotations

from datetime import datetime, timezone

from ..models import EnrichedMovie, MovieCandidate, TrailerVideo

_TYPE_RANK = {"Trailer": 0, "Teaser": 1}


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _published_ts(value: str) -> float:
    dt = _parse_date(value)
    return dt.timestamp() if dt else 0.0


def _year_from(date_str: str | None) -> int | None:
    if not date_str:
        return None
    try:
        return int(date_str[:4])
    except (ValueError, TypeError):
        return None


def pick_best_trailer(videos: list[dict], language: str) -> TrailerVideo | None:
    lang2 = language.split("-")[0].lower()
    youtube = [v for v in videos if v.get("site") == "YouTube" and v.get("key")]
    if not youtube:
        return None

    def sort_key(v: dict) -> tuple:
        return (
            _TYPE_RANK.get(v.get("type", ""), 2),
            0 if v.get("official") else 1,
            0 if v.get("iso_639_1", "").lower() == lang2 else 1,
            -int(v.get("size", 0)),
            -_published_ts(v.get("published_at", "")),
        )

    best = sorted(youtube, key=sort_key)[0]
    return TrailerVideo(
        key=best["key"],
        site=best.get("site", "YouTube"),
        type=best.get("type", ""),
        official=bool(best.get("official", False)),
        size=int(best.get("size", 0)),
        iso_639_1=best.get("iso_639_1", ""),
        published_at=best.get("published_at", ""),
    )


def extract_digital_date(
    release_dates_results: list[dict], region: str
) -> tuple[datetime | None, str]:
    by_country: dict[str, list[dict]] = {
        r.get("iso_3166_1"): r.get("release_dates", []) for r in release_dates_results
    }

    def earliest_of_type(entries: list[dict], type_code: int) -> datetime | None:
        dates = [
            _parse_date(e.get("release_date"))
            for e in entries
            if e.get("type") == type_code
        ]
        dates = [d for d in dates if d is not None]
        return min(dates) if dates else None

    region_hit = earliest_of_type(by_country.get(region, []), 4)
    if region_hit:
        return region_hit, "region"

    if region != "US":
        us_hit = earliest_of_type(by_country.get("US", []), 4)
        if us_hit:
            return us_hit, "us"

    all_entries = [e for entries in by_country.values() for e in entries]

    global_hit = earliest_of_type(all_entries, 4)
    if global_hit:
        return global_hit, "global"

    physical_hit = earliest_of_type(all_entries, 5)
    if physical_hit:
        return physical_hit, "physical"

    tv_hit = earliest_of_type(all_entries, 6)
    if tv_hit:
        return tv_hit, "tv"

    return None, "none"


def _certification(release_dates_results: list[dict], region: str) -> str | None:
    for r in release_dates_results:
        if r.get("iso_3166_1") == region:
            for e in r.get("release_dates", []):
                cert = e.get("certification")
                if cert:
                    return cert
    return None


def discover(
    client,
    sources: list[str],
    region: str,
    language: str,
    count: int,
    pages: int = 3,
) -> list[MovieCandidate]:
    seen: dict[int, MovieCandidate] = {}
    for source in sources:
        for raw in client.list_movies(source, region, language, pages):
            tmdb_id = raw.get("id")
            if tmdb_id is None or tmdb_id in seen:
                continue
            seen[tmdb_id] = MovieCandidate(
                tmdb_id=tmdb_id,
                title=raw.get("title") or raw.get("name") or "",
                year=_year_from(raw.get("release_date")),
                overview=raw.get("overview", ""),
                popularity=float(raw.get("popularity", 0.0)),
                poster_path=raw.get("poster_path"),
                backdrop_path=raw.get("backdrop_path"),
                source=source,
                release_date=raw.get("release_date"),
            )
    ranked = sorted(seen.values(), key=lambda c: c.popularity, reverse=True)
    return ranked[:count]


def enrich(client, cand: MovieCandidate, region: str, language: str) -> EnrichedMovie:
    details = client.movie_details(cand.tmdb_id, language)
    videos = details.get("videos", {}).get("results", [])
    trailer = pick_best_trailer(videos, language)
    release_dates = details.get("release_dates", {}).get("results", [])
    digital_date, digital_date_source = extract_digital_date(release_dates, region)
    genres = [g["name"] for g in details.get("genres", []) if g.get("name")]
    studios = [s["name"] for s in details.get("production_companies", []) if s.get("name")]
    return EnrichedMovie(
        tmdb_id=cand.tmdb_id,
        title=details.get("title") or cand.title,
        year=cand.year or _year_from(details.get("release_date")),
        overview=details.get("overview") or cand.overview,
        popularity=float(details.get("popularity", cand.popularity)),
        source=cand.source,
        poster_path=details.get("poster_path") or cand.poster_path,
        backdrop_path=details.get("backdrop_path") or cand.backdrop_path,
        runtime=details.get("runtime"),
        genres=genres,
        studios=studios,
        certification=_certification(release_dates, region),
        premiere_date=details.get("release_date") or cand.release_date,
        digital_date=digital_date,
        digital_date_source=digital_date_source,
        youtube_key=trailer.key if trailer else None,
        trailer=trailer,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_curator.py -v`
Expected: PASS — 16 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/marquee/tmdb/curator.py backend/tests/test_curator.py
git commit -m "feat: add curator (discover, best-trailer, digital-date chain, enrich)"
```

---

### Task 7: CLI `discover` subcommand (`__main__.py`)

**Files:**
- Create: `backend/marquee/__main__.py`
- Test: `backend/tests/test_cli.py`

**Interfaces:**
- Consumes: `marquee.config.load_config`, `marquee.tmdb.client.TMDBClient`, `marquee.tmdb.curator.discover/enrich`.
- Produces:
  - `cmd_discover(config: Config, client=None) -> str` — discovers, enriches each candidate, returns a rendered table string (header + one row per movie: rank, tmdb id, popularity, digital date `YYYY-MM-DD` or `-`, digital-date source, title). `client` injectable for tests; defaults to a real `TMDBClient(config.tmdb_token)`.
  - `main(argv=None) -> int` — argparse with required `discover` subcommand; loads config from `os.environ`, prints `cmd_discover`, returns `0`. Console-script entrypoint (`marquee`) from Task 1's pyproject.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_cli.py`:

```python
from marquee.__main__ import cmd_discover
from marquee.config import load_config


class FakeClient:
    def __init__(self, lists, details):
        self._lists = lists
        self._details = details

    def list_movies(self, source, region, language, pages=3):
        return self._lists.get(source, [])

    def movie_details(self, tmdb_id, language, append=("videos", "release_dates", "images")):
        return self._details[tmdb_id]


def test_cmd_discover_renders_table():
    config = load_config({"TMDB_TOKEN": "x", "COUNT": "2"})
    lists = {
        "upcoming": [
            {"id": 5, "title": "Movie Five", "popularity": 42.0, "release_date": "2026-04-01", "overview": "ov"}
        ],
        "now_playing": [],
    }
    details = {
        5: {
            "id": 5,
            "title": "Movie Five",
            "overview": "ov",
            "popularity": 42.0,
            "runtime": 120,
            "release_date": "2026-04-01",
            "genres": [{"name": "Action"}],
            "production_companies": [{"name": "Studio X"}],
            "videos": {
                "results": [
                    {
                        "key": "yt5",
                        "site": "YouTube",
                        "type": "Trailer",
                        "official": True,
                        "size": 1080,
                        "iso_639_1": "en",
                        "published_at": "2026-01-01T00:00:00.000Z",
                    }
                ]
            },
            "release_dates": {
                "results": [
                    {
                        "iso_3166_1": "US",
                        "release_dates": [
                            {"type": 4, "release_date": "2026-06-01T00:00:00.000Z"}
                        ],
                    }
                ]
            },
        }
    }
    out = cmd_discover(config, client=FakeClient(lists, details))
    assert "Movie Five" in out
    assert "2026-06-01" in out
    assert "region" in out
    assert "5" in out  # tmdb id column


def test_cmd_discover_dash_when_no_digital_date():
    config = load_config({"TMDB_TOKEN": "x", "COUNT": "1"})
    lists = {
        "upcoming": [
            {"id": 8, "title": "Theatrical Only", "popularity": 5.0, "release_date": "2026-04-01", "overview": ""}
        ],
        "now_playing": [],
    }
    details = {
        8: {
            "id": 8,
            "title": "Theatrical Only",
            "overview": "",
            "popularity": 5.0,
            "runtime": 90,
            "release_date": "2026-04-01",
            "genres": [],
            "production_companies": [],
            "videos": {"results": []},
            "release_dates": {
                "results": [
                    {"iso_3166_1": "US", "release_dates": [{"type": 3, "release_date": "2026-04-01T00:00:00.000Z"}]}
                ]
            },
        }
    }
    out = cmd_discover(config, client=FakeClient(lists, details))
    assert "Theatrical Only" in out
    assert "-" in out
    assert "none" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'marquee.__main__'`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/marquee/__main__.py` (complete file):

```python
from __future__ import annotations

import argparse
import os
import sys

from .config import Config, load_config
from .tmdb import curator
from .tmdb.client import TMDBClient


def cmd_discover(config: Config, client=None) -> str:
    client = client or TMDBClient(config.tmdb_token)
    candidates = curator.discover(
        client, config.sources, config.region, config.language, config.count
    )
    lines = [f"{'#':>3}  {'TMDB':>8}  {'POP':>8}  {'DIGITAL':<12}  {'SRC':<9}  TITLE"]
    for index, cand in enumerate(candidates, start=1):
        enriched = curator.enrich(client, cand, config.region, config.language)
        digital = (
            enriched.digital_date.date().isoformat() if enriched.digital_date else "-"
        )
        lines.append(
            f"{index:>3}  {enriched.tmdb_id:>8}  {enriched.popularity:>8.1f}  "
            f"{digital:<12}  {enriched.digital_date_source:<9}  {enriched.title}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(prog="marquee")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("discover", help="Print the ranked, enriched top-N movies")
    args = parser.parse_args(argv)

    config = load_config(os.environ)
    if args.command == "discover":
        print(cmd_discover(config))
        return 0
    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_cli.py -v`
Expected: PASS — 2 passed.

- [ ] **Step 5: Run the whole suite to confirm the plan is green**

Run: `cd backend && python -m pytest -v`
Expected: PASS — all tests from Tasks 1–7 pass (version, models, config, store, tmdb client, curator, cli).

- [ ] **Step 6: Commit**

```bash
git add backend/marquee/__main__.py backend/tests/test_cli.py
git commit -m "feat: add discover CLI subcommand printing ranked enriched table"
```

---

## Self-Review

### 1. Spec-coverage checklist (requirements relevant to Backend Core)

| Spec / contract requirement | Task |
|---|---|
| PEP 621 `pyproject.toml`, package `marquee` under `backend/`, deps httpx/fastapi/uvicorn/apscheduler/yt-dlp/pydantic + dev pytest/respx/ruff (§2, §13, contract Global Constraints) | Task 1 |
| Data model dataclasses/enums (contract §Data model; spec §9) | Task 2 |
| Config keys + defaults, SOURCES comma parse, env→settings overlay (§10, contract `config.py`) | Task 3 |
| SQLite state: movies/activity_log/settings, JSON genres/studios, pinned, status filter (§9, contract `store.py`) | Task 4 |
| TMDB Bearer auth, base URL, list endpoints incl trending_day/week, pages loop, `append_to_response` detail, cached `/configuration`, image URL, 429 `Retry-After` backoff (§8, contract `tmdb/client.py`) | Task 5 |
| Merge/dedupe-by-id/rank-by-popularity/top-N discover (§4.1) | Task 6 (`discover`) |
| Best-trailer selection ordering YouTube→Trailer>Teaser→official→lang→size→published (§4.3) | Task 6 (`pick_best_trailer`) |
| Digital-date extraction w/ full fallback chain region→US→global→physical→tv→None, aware UTC (§6, contract release-types) | Task 6 (`extract_digital_date`) |
| Enrich into `EnrichedMovie` (best trailer, digital date, poster/backdrop, overview, runtime, genres, studios, certification, year, premiere) (§4.2) | Task 6 (`enrich`) |
| `python -m marquee discover` dry-run prints ranked enriched top-N with digital dates (contract `__main__.py`) | Task 7 |
| Tests: respx-mocked HTTP, tmp_path SQLite, inline JSON fixtures, injected client, conventional commits (§14, contract test conventions) | All tasks |

Out-of-scope for this plan (covered by Plans 2–3, correctly absent): downloader, library writer/reaper, jellyfin client, pipeline, scheduler, FastAPI api/SSE, Docker/CI, React frontend, `run`/`reap`/`serve` CLI subcommands, e2e real-TMDB test.

### 2. Placeholder scan

No `TBD`/`TODO`/`implement later`/"add error handling"/"similar to Task N"/"write tests for the above" appear. Every code step contains complete, runnable file contents; every test step contains complete assertions; every run step has an exact command and expected outcome. The two test files that need a duck-typed TMDB client each define their own complete `FakeClient` (repeated rather than cross-referenced).

### 3. Type-consistency check against the contract

- `Status`, `ErrorKind`, `MovieCandidate`, `TrailerVideo`, `EnrichedMovie`, `Movie` field names/types/defaults match the contract Data-model block verbatim (Task 2); `TrailerVideo.youtube_url` returns the exact contract URL form.
- `Config` field set/order and defaults match the contract `config.py` block; `load_config(env, overrides)` signature matches. `sources` uses `default_factory` (valid because `tmdb_token` has no default and precedes it).
- `Store` method names/signatures (`upsert_movie/get_movie/list_movies/set_status(**fields)/set_pinned/delete_movie/log/recent_activity/get_setting/set_setting/all_settings`) match the contract `store.py` block. Datetimes stored/read as UTC-aware; genres/studios round-trip as JSON.
- `TMDBClient.__init__/list_movies/movie_details/image_base_url/build_image_url` signatures and defaults (`base_url`, `append`, `pages`) match the contract; source→endpoint map covers all five contract sources.
- `curator.discover/pick_best_trailer/extract_digital_date/enrich` signatures match the contract exactly; `extract_digital_date` returns `(datetime|None, str)` with source strings `region/us/global/physical/tv/none`.
- Names used across tasks are stable: `cmd_discover` (defined and consumed in Task 7 only), `TMDBClient` (Task 5 → used Task 7), curator functions (Task 6 → used Task 7).

**Contract symbols added/clarified (for orchestrator reconciliation):**
1. `load_config` — `env` and `overrides` are both keyed by the **uppercase env-var names** of spec §10; `overrides` overlay `env`; empty strings fall back to defaults. (Contract didn't state the key convention.)
2. `Store.set_status(**fields)` accepts **any `movies` column name** as a keyword; values that are `datetime`/`list`/`dict`/`bool`/`Status` are auto-serialized to their column encoding. (Contract left `**fields` semantics unspecified.)
3. `Store` — **settings rows are keyed by lowercase Config field names** (e.g. `count`, `region`, `sources`), matching the contract's `config.py` convention. DB settings are applied at startup via `apply_setting_overrides(load_config(env), store.all_settings())` (lowercase field-name keys) — **not** through `load_config`'s uppercase env-style `overrides` param. Timestamps persist as UTC-aware ISO strings.
4. `TMDBClient` — internal `_get` retries up to 5× on HTTP 429; `region` is sent to all list endpoints (harmless on `/trending`); `build_image_url` composes `secure_base_url + size + path`.
5. `curator.enrich` field derivations: `genres` ← `details["genres"][].name`, `studios` ← `details["production_companies"][].name`, `certification` ← first non-empty `certification` in the region's `release_dates` entry. (Contract named the fields but not the TMDB source keys.)
