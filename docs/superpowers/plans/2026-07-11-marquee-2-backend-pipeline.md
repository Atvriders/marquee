# Marquee Backend Pipeline & API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the full Marquee backend — a yt-dlp downloader, library writer, Jellyfin client, reaper, refresh pipeline, SSE broadcaster, FastAPI app, APScheduler wrapper, and CLI — so a scheduled or on-demand pass downloads trailers, writes a browsable Jellyfin "Coming Soon" library, expires titles at digital release, and serves everything over `/api`.

**Architecture:** Single FastAPI process (Python 3.13) with an in-process APScheduler running two cron jobs (refresh + reaper) guarded by a single-flight lock. `RefreshPipeline` orchestrates the Plan-1 curator/TMDB client, the yt-dlp `TrailerDownloader`, and the `LibraryWriter`, persisting state through the Plan-1 `Store` and fanning progress to SSE subscribers via `Broadcaster`. The `Reaper` deletes expired folders and issues authoritative `DELETE /Items` calls to Jellyfin.

**Tech Stack:** Python 3.13, FastAPI, uvicorn, APScheduler, httpx (+ respx in tests), yt-dlp, ffmpeg, pytest.

## Global Constraints

- **Python 3.13**, package name `marquee`, src under `backend/`.
- **yt-dlp** installed as `yt-dlp[default]`; **ffmpeg** required at runtime on PATH.
- **Download format string (exact):** `bv*[height<=1080]+ba/b[height<=1080]/b` with `merge_output_format` = configured container (`mkv` default). Merge is stream-copy (no re-encode).
- **Real output path** comes from `info["requested_downloads"][0]["filepath"]`, never `prepare_filename`.
- **Library layout:** one folder per movie `"<SanitizedTitle> (<year>) [tmdbid-<id>]"`; the video filename **begins character-for-character with the folder name**; illegal chars `< > : " / \ | ? *` stripped/replaced.
- **NFO** fields exactly per spec §5 (`plot`→overview, `runtime` in minutes, `uniqueid type="tmdb" default="true"`, `thumb aspect="poster"`, `fanart/thumb`). No reliance on `<lockdata>`.
- **Images:** poster `w500`, backdrop `w1280`, via `secure_base_url` from `/configuration`.
- **Jellyfin:** `DELETE /Items/{id}` requires an **admin user token** from `POST /Users/AuthenticateByName`; scans use the API key. Auth header `X-Emby-Token: <key>`.
- **TMDB release types:** 4 = Digital. Digital-date fallback chain: region type-4 → US type-4 → earliest type-4 anywhere → type-5 → type-6 → None(keep).
- **Time:** store timestamps UTC-aware; compare expiry end-of-day in configured `TZ`.
- **Container:** non-root `appuser` UID 1000; volumes `/library` (rw) and `/config` (rw). GHCR package public. Multi-arch amd64+arm64.
- **Not in scope:** `.strm` mode, Radarr/Sonarr, TV shows, transcoding, weighted blending.
- **Tests:** pytest; HTTP mocked with `respx`; yt-dlp mocked by patching `yt_dlp.YoutubeDL`; injected `now_fn` clock; golden NFO at `tests/golden/movie.nfo`; conventional commits, one per task.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/marquee/downloader.py` | yt-dlp wrapper: `probe()`, `download()`, exact options dict, output-path extraction, `DownloadFailed(kind)` classification. |
| `backend/marquee/library/__init__.py` | Package marker for the `library` subpackage. |
| `backend/marquee/library/writer.py` | `LibraryWriter`: sanitize, folder naming, NFO render, move video + write NFO/poster/backdrop, delete folder. |
| `backend/marquee/jellyfin.py` | `JellyfinClient`: cred test, library refresh, admin authenticate (cached), find-by-tmdb, authoritative delete. |
| `backend/marquee/library/reaper.py` | `Reaper`: end-of-day expiry selection (tz + grace, pin-protected) and expire (folder + JF item + mark EXPIRED). |
| `backend/marquee/api/__init__.py` | Package marker for the `api` subpackage. |
| `backend/marquee/api/sse.py` | `Broadcaster`: asyncio-queue fan-out of progress/log events to SSE subscribers. |
| `backend/marquee/pipeline.py` | `RefreshPipeline.run()`: discover→enrich→skip-if-ready→download→write→status transitions→JF refresh; returns `RunSummary`. |
| `backend/marquee/scheduler.py` | `Scheduler`: APScheduler cron jobs (refresh, reaper) with single-flight lock; on-demand triggers; status. |
| `backend/marquee/api/app.py` | FastAPI factory `create_app(context)`, `AppContext`, SPA StaticFiles catch-all that never shadows `/api`. |
| `backend/marquee/api/routes.py` | `build_router(context)`: every `/api` route from the contract; serialization helpers. |
| `backend/marquee/__main__.py` | CLI `discover`/`run`/`reap`/`serve`; `build_components()` wiring; `serve` launches uvicorn. |
| `tests/golden/movie.nfo` | Golden fixture for `render_nfo`. |
| `tests/test_downloader.py`, `tests/library/test_writer.py`, `tests/test_jellyfin.py`, `tests/library/test_reaper.py`, `tests/api/test_sse.py`, `tests/test_pipeline.py`, `tests/test_scheduler.py`, `tests/api/test_api.py`, `tests/test_main.py` | Test modules per component. |

**Assumes Plan 1 is complete:** `backend/marquee/models.py` (Status, ErrorKind, MovieCandidate, TrailerVideo, EnrichedMovie, Movie), `backend/marquee/config.py` (`Config`, `load_config`), `backend/marquee/store.py` (`Store`), `backend/marquee/tmdb/client.py` (`TMDBClient.build_image_url`, `movie_details`, …), `backend/marquee/tmdb/curator.py` (`discover`, `enrich`, `pick_best_trailer`, `extract_digital_date`) all exist with the contract signatures, and `pyproject.toml` sets `[tool.pytest.ini_options] pythonpath = ["backend"]` plus `pytest`, `httpx`, `respx`, `yt-dlp[default]` dependencies. All `pytest`/`git` commands below run from repo root `/home/kasm-user/marquee`.

---

### Task 1: Downloader (`downloader.py`)

**Files:**
- Create: `backend/marquee/downloader.py`
- Test: `tests/test_downloader.py`

**Interfaces:**
- Consumes: `Config` (from `marquee.config`, has `.container`, `.max_height`, `.config_dir`, `.ytdlp_cookies`, `.ytdlp_proxy`); `ErrorKind` (from `marquee.models`).
- Produces: `ProbeResult(ok, duration, title, has_maxheight, availability)`; `DownloadResult(path, title, duration, ext, video_id)`; `DownloadFailed(kind: ErrorKind, message: str)` with `.kind`/`.message`; `TrailerDownloader(config, on_progress=None)` with `.probe(url)->ProbeResult`, `.download(url, dest_dir, tmdb_id)->DownloadResult`, and `._build_options(dest_dir)->dict`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_downloader.py
import os
from unittest.mock import MagicMock

import pytest

from marquee.config import Config
from marquee.models import ErrorKind
from marquee.downloader import (
    TrailerDownloader,
    DownloadResult,
    ProbeResult,
    DownloadFailed,
)


def make_config(tmp_path, **over):
    base = dict(
        tmdb_token="x",
        sources=["upcoming"],
        config_dir=str(tmp_path),
        library_dir=str(tmp_path / "lib"),
        container="mkv",
        max_height=1080,
    )
    base.update(over)
    return Config(**base)


def _fake_ydl(**attrs):
    fake = MagicMock()
    fake.__enter__.return_value = fake
    fake.__exit__.return_value = False
    for k, v in attrs.items():
        setattr(fake.extract_info, k, v)
    return fake


def test_build_options_exact(tmp_path):
    cfg = make_config(tmp_path)
    dl = TrailerDownloader(cfg)
    opts = dl._build_options(str(tmp_path / "dest"))
    assert opts["format"] == "bv*[height<=1080]+ba/b[height<=1080]/b"
    assert opts["merge_output_format"] == "mkv"
    assert opts["outtmpl"] == "%(title)s [%(id)s].%(ext)s"
    assert opts["paths"] == {
        "home": str(tmp_path / "dest"),
        "temp": os.path.join(str(tmp_path), "tmp"),
    }
    assert opts["restrictfilenames"] is True
    assert opts["extractor_args"] == {
        "youtube": {"player_client": ["default", "tv", "web_safari"]}
    }
    assert "cookiefile" not in opts
    assert "proxy" not in opts
    assert opts["download_archive"] == os.path.join(str(tmp_path), "download_archive.txt")
    assert dl._progress_hook in opts["progress_hooks"]
    assert dl._pp_hook in opts["postprocessor_hooks"]


def test_build_options_cookies_proxy_and_maxheight(tmp_path):
    cfg = make_config(
        tmp_path,
        max_height=720,
        container="mp4",
        ytdlp_cookies="/config/cookies.txt",
        ytdlp_proxy="http://p:8080",
    )
    opts = TrailerDownloader(cfg)._build_options(str(tmp_path / "d"))
    assert opts["format"] == "bv*[height<=720]+ba/b[height<=720]/b"
    assert opts["merge_output_format"] == "mp4"
    assert opts["cookiefile"] == "/config/cookies.txt"
    assert opts["proxy"] == "http://p:8080"


def test_download_success(monkeypatch, tmp_path):
    cfg = make_config(tmp_path)
    dl = TrailerDownloader(cfg)
    fake = _fake_ydl(
        return_value={
            "id": "abc",
            "title": "Trailer",
            "duration": 90,
            "requested_downloads": [{"filepath": str(tmp_path / "Trailer [abc].mkv")}],
        }
    )
    monkeypatch.setattr(
        "marquee.downloader.yt_dlp.YoutubeDL", MagicMock(return_value=fake)
    )
    res = dl.download("https://youtu.be/abc", str(tmp_path), 7)
    assert isinstance(res, DownloadResult)
    assert res.path == str(tmp_path / "Trailer [abc].mkv")
    assert res.video_id == "abc"
    assert res.title == "Trailer"
    assert res.duration == 90
    assert res.ext == "mkv"


def test_download_missing_requested_downloads(monkeypatch, tmp_path):
    cfg = make_config(tmp_path)
    dl = TrailerDownloader(cfg)
    fake = _fake_ydl(return_value={"id": "abc", "title": "T"})
    monkeypatch.setattr(
        "marquee.downloader.yt_dlp.YoutubeDL", MagicMock(return_value=fake)
    )
    with pytest.raises(DownloadFailed) as ei:
        dl.download("u", str(tmp_path), 1)
    assert ei.value.kind == ErrorKind.ERROR


@pytest.mark.parametrize(
    "msg,kind",
    [
        ("ERROR: Sign in to confirm you're not a bot", ErrorKind.BOT_CHECK),
        (
            "Sign in to confirm your age. This video may be inappropriate for some users.",
            ErrorKind.AGE_GATED,
        ),
        ("Video unavailable. This video is private", ErrorKind.UNAVAILABLE),
        ("Requested format is not available", ErrorKind.NO_FORMAT),
        ("Some other weird error", ErrorKind.ERROR),
    ],
)
def test_download_classifies(monkeypatch, tmp_path, msg, kind):
    from yt_dlp.utils import DownloadError

    cfg = make_config(tmp_path)
    dl = TrailerDownloader(cfg)
    fake = MagicMock()
    fake.__enter__.return_value = fake
    fake.__exit__.return_value = False
    fake.extract_info.side_effect = DownloadError(msg)
    monkeypatch.setattr(
        "marquee.downloader.yt_dlp.YoutubeDL", MagicMock(return_value=fake)
    )
    with pytest.raises(DownloadFailed) as ei:
        dl.download("u", str(tmp_path), 1)
    assert ei.value.kind == kind
    assert ei.value.message == msg


def test_download_georestricted(monkeypatch, tmp_path):
    from yt_dlp.utils import GeoRestrictedError

    cfg = make_config(tmp_path)
    dl = TrailerDownloader(cfg)
    fake = MagicMock()
    fake.__enter__.return_value = fake
    fake.__exit__.return_value = False
    fake.extract_info.side_effect = GeoRestrictedError("blocked in your country")
    monkeypatch.setattr(
        "marquee.downloader.yt_dlp.YoutubeDL", MagicMock(return_value=fake)
    )
    with pytest.raises(DownloadFailed) as ei:
        dl.download("u", str(tmp_path), 1)
    assert ei.value.kind == ErrorKind.REGION_BLOCKED


def test_probe_ok(monkeypatch, tmp_path):
    cfg = make_config(tmp_path)
    dl = TrailerDownloader(cfg)
    fake = _fake_ydl(
        return_value={
            "id": "abc",
            "title": "T",
            "duration": 120,
            "is_live": False,
            "availability": "public",
            "formats": [{"height": 720, "vcodec": "vp9"}],
        }
    )
    monkeypatch.setattr(
        "marquee.downloader.yt_dlp.YoutubeDL", MagicMock(return_value=fake)
    )
    res = dl.probe("https://youtu.be/abc")
    assert isinstance(res, ProbeResult)
    assert res.ok is True
    assert res.has_maxheight is True
    assert res.duration == 120
    assert res.availability == "public"
    _, kwargs = fake.extract_info.call_args
    assert kwargs["download"] is False


def test_probe_live_not_ok(monkeypatch, tmp_path):
    cfg = make_config(tmp_path)
    dl = TrailerDownloader(cfg)
    fake = _fake_ydl(
        return_value={"id": "a", "is_live": True, "formats": [{"height": 720, "vcodec": "vp9"}]}
    )
    monkeypatch.setattr(
        "marquee.downloader.yt_dlp.YoutubeDL", MagicMock(return_value=fake)
    )
    assert dl.probe("u").ok is False


def test_progress_hook_reports(tmp_path):
    seen = []
    cfg = make_config(tmp_path)
    dl = TrailerDownloader(cfg, on_progress=lambda *a: seen.append(a))
    dl._current_tmdb_id = 42
    dl._progress_hook(
        {"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100, "speed": 10.0, "eta": 5}
    )
    assert seen == [(42, 50.0, 10.0, 5)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_downloader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marquee.downloader'`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/marquee/downloader.py
from __future__ import annotations

import os
from dataclasses import dataclass

import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError, GeoRestrictedError

from marquee.config import Config
from marquee.models import ErrorKind


@dataclass
class ProbeResult:
    ok: bool
    duration: int | None
    title: str | None
    has_maxheight: bool
    availability: str | None


@dataclass
class DownloadResult:
    path: str
    title: str | None
    duration: int | None
    ext: str
    video_id: str


class DownloadFailed(Exception):
    def __init__(self, kind: ErrorKind, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


class TrailerDownloader:
    def __init__(self, config: Config, on_progress=None):
        self.config = config
        self._on_progress = on_progress
        self._current_tmdb_id: int | None = None

    def _build_options(self, dest_dir: str) -> dict:
        h = self.config.max_height
        opts: dict = {
            "format": f"bv*[height<={h}]+ba/b[height<={h}]/b",
            "merge_output_format": self.config.container,
            "outtmpl": "%(title)s [%(id)s].%(ext)s",
            "paths": {
                "home": dest_dir,
                "temp": os.path.join(self.config.config_dir, "tmp"),
            },
            "restrictfilenames": True,
            "extractor_args": {
                "youtube": {"player_client": ["default", "tv", "web_safari"]}
            },
            "retries": 10,
            "fragment_retries": 10,
            "sleep_interval": 1,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "progress_hooks": [self._progress_hook],
            "postprocessor_hooks": [self._pp_hook],
        }
        opts["download_archive"] = os.path.join(
            self.config.config_dir, "download_archive.txt"
        )
        if self.config.ytdlp_cookies:
            opts["cookiefile"] = self.config.ytdlp_cookies
        if self.config.ytdlp_proxy:
            opts["proxy"] = self.config.ytdlp_proxy
        return opts

    def _progress_hook(self, d: dict) -> None:
        if self._on_progress is None:
            return
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            pct = round(done / total * 100, 1) if total else 0.0
            self._on_progress(self._current_tmdb_id, pct, d.get("speed"), d.get("eta"))
        elif status == "finished":
            self._on_progress(self._current_tmdb_id, 100.0, None, 0)

    def _pp_hook(self, d: dict) -> None:
        if self._on_progress and d.get("status") == "finished":
            self._on_progress(self._current_tmdb_id, 100.0, None, 0)

    @staticmethod
    def _classify(msg: str) -> ErrorKind:
        m = msg.lower()
        if (
            "confirm your age" in m
            or "inappropriate for some users" in m
            or "age-restricted" in m
            or "age restricted" in m
        ):
            return ErrorKind.AGE_GATED
        if "not a bot" in m or ("sign in to confirm" in m and "bot" in m):
            return ErrorKind.BOT_CHECK
        if (
            "not available in your country" in m
            or "blocked it in your country" in m
            or "geo" in m
        ):
            return ErrorKind.REGION_BLOCKED
        if "requested format" in m or "no video formats" in m or "no formats" in m:
            return ErrorKind.NO_FORMAT
        if (
            "unavailable" in m
            or "private" in m
            or "removed" in m
            or "deleted" in m
            or "terminated" in m
        ):
            return ErrorKind.UNAVAILABLE
        return ErrorKind.ERROR

    def probe(self, url: str) -> ProbeResult:
        opts = self._build_options(self.config.config_dir)
        opts["skip_download"] = True
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except (DownloadError, ExtractorError):
            return ProbeResult(
                ok=False,
                duration=None,
                title=None,
                has_maxheight=False,
                availability="error",
            )
        is_live = bool(info.get("is_live"))
        formats = info.get("formats", []) or []
        has_max = any(
            (f.get("height") or 0) <= self.config.max_height
            and f.get("vcodec", "none") != "none"
            for f in formats
        )
        return ProbeResult(
            ok=(not is_live) and has_max,
            duration=info.get("duration"),
            title=info.get("title"),
            has_maxheight=has_max,
            availability=info.get("availability"),
        )

    def download(self, url: str, dest_dir: str, tmdb_id: int) -> DownloadResult:
        self._current_tmdb_id = tmdb_id
        opts = self._build_options(dest_dir)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except GeoRestrictedError as e:
            raise DownloadFailed(ErrorKind.REGION_BLOCKED, str(e)) from e
        except (DownloadError, ExtractorError) as e:
            raise DownloadFailed(self._classify(str(e)), str(e)) from e
        requested = (info or {}).get("requested_downloads")
        if not requested:
            raise DownloadFailed(
                ErrorKind.ERROR, "no requested_downloads in yt-dlp result"
            )
        path = requested[0]["filepath"]
        ext = os.path.splitext(path)[1].lstrip(".")
        return DownloadResult(
            path=path,
            title=info.get("title"),
            duration=info.get("duration"),
            ext=ext,
            video_id=info.get("id", ""),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_downloader.py -v`
Expected: PASS (9 test functions, 13 collected cases — `test_download_classifies` is parametrized with 5 cases).

- [ ] **Step 5: Commit**

```bash
git add backend/marquee/downloader.py tests/test_downloader.py
git commit -m "feat: yt-dlp TrailerDownloader with probe, options, and error classification"
```

---

### Task 2: Library writer (`library/writer.py`)

**Files:**
- Create: `backend/marquee/library/__init__.py`, `backend/marquee/library/writer.py`, `tests/golden/movie.nfo`
- Test: `tests/library/test_writer.py`

**Interfaces:**
- Consumes: `EnrichedMovie` (from `marquee.models`); a `client` exposing `build_image_url(path, size) -> str` (Plan-1 `TMDBClient`).
- Produces: `WrittenMovie(folder, video_path, nfo_path, poster_path, backdrop_path)`; `LibraryWriter(library_dir, client)` with `sanitize(name)` (staticmethod), `folder_name(title, year, tmdb_id)`, `render_nfo(m)->str`, `write_movie(m, source_video)->WrittenMovie`, `delete_movie(folder)`.

- [ ] **Step 1: Create the golden NFO fixture**

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<movie>
  <title>Dune: Part Three</title>
  <originaltitle>Dune: Part Three</originaltitle>
  <sorttitle>Dune: Part Three</sorttitle>
  <plot>COMING SOON. The saga concludes. In theaters 2026-12-18.</plot>
  <runtime>166</runtime>
  <year>2026</year>
  <premiered>2026-12-18</premiered>
  <releasedate>2026-12-18</releasedate>
  <mpaa>PG-13</mpaa>
  <genre>Science Fiction</genre>
  <genre>Adventure</genre>
  <studio>Legendary Pictures</studio>
  <tag>Coming Soon</tag>
  <tag>Trailer</tag>
  <uniqueid type="tmdb" default="true">1234567</uniqueid>
  <tmdbid>1234567</tmdbid>
  <thumb aspect="poster">poster.jpg</thumb>
  <fanart>
    <thumb>backdrop.jpg</thumb>
  </fanart>
</movie>
```

(Write exactly this content, with a single trailing newline, to `tests/golden/movie.nfo`.)

- [ ] **Step 2: Write the failing test**

```python
# tests/library/test_writer.py
import os

import httpx
import pytest
import respx

from marquee.models import EnrichedMovie
from marquee.library.writer import LibraryWriter, WrittenMovie


class FakeClient:
    def build_image_url(self, path: str, size: str) -> str:
        return f"https://image.tmdb.org/t/p/{size}{path}"


def make_movie(**over):
    base = dict(
        tmdb_id=1234567,
        title="Dune: Part Three",
        year=2026,
        overview="The saga concludes.",
        popularity=99.0,
        source="upcoming",
        poster_path="/p.jpg",
        backdrop_path="/b.jpg",
        runtime=166,
        genres=["Science Fiction", "Adventure"],
        studios=["Legendary Pictures"],
        certification="PG-13",
        premiere_date="2026-12-18",
        digital_date=None,
        digital_date_source="none",
        youtube_key="yt123",
        trailer=None,
    )
    base.update(over)
    return EnrichedMovie(**base)


def test_sanitize_strips_illegal_and_collapses():
    assert LibraryWriter.sanitize("Dune: Part Three") == "Dune Part Three"
    assert LibraryWriter.sanitize('A/B\\C:D?E*F') == "A B C D E F"
    assert LibraryWriter.sanitize("Trailing dots...") == "Trailing dots"


def test_folder_name():
    w = LibraryWriter("/library", FakeClient())
    assert (
        w.folder_name("Dune: Part Three", 2026, 1234567)
        == "Dune Part Three (2026) [tmdbid-1234567]"
    )
    assert w.folder_name("No Year", None, 5) == "No Year [tmdbid-5]"


def test_render_nfo_matches_golden():
    w = LibraryWriter("/library", FakeClient())
    golden = open(
        os.path.join(os.path.dirname(__file__), "..", "golden", "movie.nfo")
    ).read()
    assert w.render_nfo(make_movie()) == golden


@respx.mock
def test_write_movie(tmp_path):
    respx.get("https://image.tmdb.org/t/p/w500/p.jpg").mock(
        return_value=httpx.Response(200, content=b"POSTERBYTES")
    )
    respx.get("https://image.tmdb.org/t/p/w1280/b.jpg").mock(
        return_value=httpx.Response(200, content=b"BACKBYTES")
    )
    src = tmp_path / "raw.mkv"
    src.write_bytes(b"VIDEO")
    w = LibraryWriter(str(tmp_path / "lib"), FakeClient())
    written = w.write_movie(make_movie(), str(src))
    assert isinstance(written, WrittenMovie)
    folder_base = "Dune Part Three (2026) [tmdbid-1234567]"
    assert os.path.basename(written.folder) == folder_base
    assert os.path.basename(written.video_path) == folder_base + ".mkv"
    assert not src.exists()  # moved, not copied
    assert open(written.nfo_path).read().startswith("<?xml")
    assert open(written.poster_path, "rb").read() == b"POSTERBYTES"
    assert open(written.backdrop_path, "rb").read() == b"BACKBYTES"


@respx.mock
def test_write_movie_no_backdrop(tmp_path):
    respx.get("https://image.tmdb.org/t/p/w500/p.jpg").mock(
        return_value=httpx.Response(200, content=b"P")
    )
    src = tmp_path / "raw.mkv"
    src.write_bytes(b"V")
    w = LibraryWriter(str(tmp_path / "lib"), FakeClient())
    written = w.write_movie(make_movie(backdrop_path=None), str(src))
    assert written.backdrop_path is None


def test_delete_movie(tmp_path):
    folder = tmp_path / "lib" / "x"
    folder.mkdir(parents=True)
    (folder / "a.txt").write_text("hi")
    w = LibraryWriter(str(tmp_path / "lib"), FakeClient())
    w.delete_movie(str(folder))
    assert not folder.exists()
    w.delete_movie(str(folder))  # idempotent, no raise
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/library/test_writer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marquee.library'`.

- [ ] **Step 4: Write minimal implementation**

Create `backend/marquee/library/__init__.py` (empty file), then:

```python
# backend/marquee/library/writer.py
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from xml.sax.saxutils import escape

import httpx

from marquee.models import EnrichedMovie

_ILLEGAL = '<>:"/\\|?*'


@dataclass
class WrittenMovie:
    folder: str
    video_path: str
    nfo_path: str
    poster_path: str | None
    backdrop_path: str | None


class LibraryWriter:
    def __init__(self, library_dir: str, client):
        self.library_dir = library_dir
        self.client = client

    @staticmethod
    def sanitize(name: str) -> str:
        cleaned = "".join(" " if c in _ILLEGAL else c for c in name)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned.rstrip(". ")

    def folder_name(self, title: str, year: int | None, tmdb_id: int) -> str:
        safe = self.sanitize(title)
        if year:
            return f"{safe} ({year}) [tmdbid-{tmdb_id}]"
        return f"{safe} [tmdbid-{tmdb_id}]"

    @staticmethod
    def _plot(m: EnrichedMovie) -> str:
        parts = ["COMING SOON."]
        if m.overview:
            parts.append(m.overview)
        if m.premiere_date:
            parts.append(f"In theaters {m.premiere_date}.")
        return " ".join(parts)

    def render_nfo(self, m: EnrichedMovie) -> str:
        lines = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            "<movie>",
            f"  <title>{escape(m.title)}</title>",
            f"  <originaltitle>{escape(m.title)}</originaltitle>",
            f"  <sorttitle>{escape(m.title)}</sorttitle>",
            f"  <plot>{escape(self._plot(m))}</plot>",
        ]
        if m.runtime is not None:
            lines.append(f"  <runtime>{m.runtime}</runtime>")
        if m.year is not None:
            lines.append(f"  <year>{m.year}</year>")
        if m.premiere_date:
            lines.append(f"  <premiered>{escape(m.premiere_date)}</premiered>")
            lines.append(f"  <releasedate>{escape(m.premiere_date)}</releasedate>")
        if m.certification:
            lines.append(f"  <mpaa>{escape(m.certification)}</mpaa>")
        for g in m.genres:
            lines.append(f"  <genre>{escape(g)}</genre>")
        for s in m.studios:
            lines.append(f"  <studio>{escape(s)}</studio>")
        lines.append("  <tag>Coming Soon</tag>")
        lines.append("  <tag>Trailer</tag>")
        lines.append(
            f'  <uniqueid type="tmdb" default="true">{m.tmdb_id}</uniqueid>'
        )
        lines.append(f"  <tmdbid>{m.tmdb_id}</tmdbid>")
        if m.poster_path:
            lines.append('  <thumb aspect="poster">poster.jpg</thumb>')
        if m.backdrop_path:
            lines.append("  <fanart>")
            lines.append("    <thumb>backdrop.jpg</thumb>")
            lines.append("  </fanart>")
        lines.append("</movie>")
        return "\n".join(lines) + "\n"

    def _fetch(self, url: str) -> bytes:
        resp = httpx.get(url, timeout=30.0)
        resp.raise_for_status()
        return resp.content

    def write_movie(self, m: EnrichedMovie, source_video: str) -> WrittenMovie:
        name = self.folder_name(m.title, m.year, m.tmdb_id)
        folder = os.path.join(self.library_dir, name)
        os.makedirs(folder, exist_ok=True)

        ext = os.path.splitext(source_video)[1].lstrip(".") or "mkv"
        video_path = os.path.join(folder, f"{name}.{ext}")
        shutil.move(source_video, video_path)

        nfo_path = os.path.join(folder, "movie.nfo")
        with open(nfo_path, "w", encoding="utf-8") as fh:
            fh.write(self.render_nfo(m))

        poster_path = None
        if m.poster_path:
            poster_path = os.path.join(folder, "poster.jpg")
            with open(poster_path, "wb") as fh:
                fh.write(self._fetch(self.client.build_image_url(m.poster_path, "w500")))

        backdrop_path = None
        if m.backdrop_path:
            backdrop_path = os.path.join(folder, "backdrop.jpg")
            with open(backdrop_path, "wb") as fh:
                fh.write(
                    self._fetch(self.client.build_image_url(m.backdrop_path, "w1280"))
                )

        return WrittenMovie(
            folder=folder,
            video_path=video_path,
            nfo_path=nfo_path,
            poster_path=poster_path,
            backdrop_path=backdrop_path,
        )

    def delete_movie(self, folder: str) -> None:
        shutil.rmtree(folder, ignore_errors=True)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/library/test_writer.py -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/marquee/library/__init__.py backend/marquee/library/writer.py tests/library/test_writer.py tests/golden/movie.nfo
git commit -m "feat: LibraryWriter with NFO golden render, poster/backdrop write, and sanitization"
```

---

### Task 3: Jellyfin client (`jellyfin.py`)

**Files:**
- Create: `backend/marquee/jellyfin.py`
- Test: `tests/test_jellyfin.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (standalone httpx client).
- Produces: `JellyfinClient(url, api_key, username=None, password=None, session=None)` with `test()->bool`, `refresh_library()`, `authenticate()->str` (cached admin token), `find_item_by_tmdb(tmdb_id)->str|None`, `delete_item(item_id)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_jellyfin.py
import httpx
import pytest
import respx

from marquee.jellyfin import JellyfinClient

URL = "http://jelly:8096"


def make_client(**over):
    base = dict(url=URL + "/", api_key="APIKEY", username="admin", password="pw")
    base.update(over)
    return JellyfinClient(**base)


@respx.mock
def test_test_ok_and_key_header():
    route = respx.get(f"{URL}/System/Info").mock(
        return_value=httpx.Response(200, json={"Version": "10.11"})
    )
    assert make_client().test() is True
    assert route.calls.last.request.headers["X-Emby-Token"] == "APIKEY"


@respx.mock
def test_test_false_on_error():
    respx.get(f"{URL}/System/Info").mock(return_value=httpx.Response(401))
    assert make_client().test() is False


@respx.mock
def test_refresh_uses_api_key():
    route = respx.post(f"{URL}/Library/Refresh").mock(
        return_value=httpx.Response(204)
    )
    make_client().refresh_library()
    assert route.calls.last.request.headers["X-Emby-Token"] == "APIKEY"


@respx.mock
def test_authenticate_caches_admin_token():
    route = respx.post(f"{URL}/Users/AuthenticateByName").mock(
        return_value=httpx.Response(200, json={"AccessToken": "ADMIN123"})
    )
    c = make_client()
    assert c.authenticate() == "ADMIN123"
    assert c.authenticate() == "ADMIN123"
    assert route.call_count == 1  # cached


@respx.mock
def test_find_item_by_tmdb():
    respx.get(f"{URL}/Items").mock(
        return_value=httpx.Response(200, json={"Items": [{"Id": "ITEM42"}]})
    )
    assert make_client().find_item_by_tmdb(1234567) == "ITEM42"


@respx.mock
def test_find_item_none():
    respx.get(f"{URL}/Items").mock(
        return_value=httpx.Response(200, json={"Items": []})
    )
    assert make_client().find_item_by_tmdb(1) is None


@respx.mock
def test_delete_uses_admin_token():
    respx.post(f"{URL}/Users/AuthenticateByName").mock(
        return_value=httpx.Response(200, json={"AccessToken": "ADMIN123"})
    )
    route = respx.delete(f"{URL}/Items/ITEM42").mock(
        return_value=httpx.Response(204)
    )
    make_client().delete_item("ITEM42")
    assert route.calls.last.request.headers["X-Emby-Token"] == "ADMIN123"


def test_authenticate_requires_creds():
    with pytest.raises(RuntimeError):
        make_client(username=None, password=None).authenticate()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_jellyfin.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marquee.jellyfin'`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/marquee/jellyfin.py
from __future__ import annotations

import httpx

_AUTH_HEADER = (
    'MediaBrowser Client="Marquee", Device="Marquee", '
    'DeviceId="marquee", Version="1.0"'
)


class JellyfinClient:
    def __init__(
        self,
        url: str,
        api_key: str,
        username: str | None = None,
        password: str | None = None,
        session: httpx.Client | None = None,
    ):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.username = username
        self.password = password
        self._session = session or httpx.Client(timeout=30.0)
        self._admin_token: str | None = None

    def _key_headers(self) -> dict:
        return {"X-Emby-Token": self.api_key}

    def test(self) -> bool:
        try:
            resp = self._session.get(
                f"{self.url}/System/Info", headers=self._key_headers()
            )
        except httpx.HTTPError:
            return False
        return resp.status_code == 200

    def refresh_library(self) -> None:
        resp = self._session.post(
            f"{self.url}/Library/Refresh", headers=self._key_headers()
        )
        resp.raise_for_status()

    def authenticate(self) -> str:
        if self._admin_token:
            return self._admin_token
        if not (self.username and self.password):
            raise RuntimeError("Jellyfin admin credentials not configured")
        resp = self._session.post(
            f"{self.url}/Users/AuthenticateByName",
            json={"Username": self.username, "Pw": self.password},
            headers={"Authorization": _AUTH_HEADER, "X-Emby-Authorization": _AUTH_HEADER},
        )
        resp.raise_for_status()
        self._admin_token = resp.json()["AccessToken"]
        return self._admin_token

    def find_item_by_tmdb(self, tmdb_id: int) -> str | None:
        resp = self._session.get(
            f"{self.url}/Items",
            params={
                "recursive": "true",
                "anyProviderIdEquals": f"tmdb.{tmdb_id}",
                "fields": "ProviderIds",
            },
            headers=self._key_headers(),
        )
        resp.raise_for_status()
        items = resp.json().get("Items", [])
        return items[0]["Id"] if items else None

    def delete_item(self, item_id: str) -> None:
        token = self.authenticate()
        resp = self._session.delete(
            f"{self.url}/Items/{item_id}", headers={"X-Emby-Token": token}
        )
        resp.raise_for_status()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_jellyfin.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/marquee/jellyfin.py tests/test_jellyfin.py
git commit -m "feat: JellyfinClient with cached admin auth and authoritative item delete"
```

---

### Task 4: Reaper (`library/reaper.py`)

**Files:**
- Create: `backend/marquee/library/reaper.py`
- Test: `tests/library/test_reaper.py`

**Interfaces:**
- Consumes: `Store`, `LibraryWriter.delete_movie(folder)`, `JellyfinClient` (`find_item_by_tmdb`, `delete_item`, `refresh_library`), `Movie`/`Status` (from `marquee.models`).
- Produces: `Reaper(store, writer, jellyfin, now_fn=..., grace_days=0, tz="UTC", count=50)` with `find_expired(movies)->list[Movie]` and `expire(m)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/library/test_reaper.py
from datetime import UTC, datetime

from marquee.models import Movie, Status
from marquee.library.reaper import Reaper


def mkmovie(**over):
    base = dict(
        tmdb_id=1,
        title="M",
        year=2026,
        overview="",
        runtime=100,
        genres=[],
        studios=[],
        certification=None,
        premiere_date=None,
        digital_date=datetime(2026, 12, 18, 0, 0, tzinfo=UTC),
        digital_date_source="region",
        region="US",
        popularity=1.0,
        poster_path=None,
        backdrop_path=None,
        youtube_key="k",
        status=Status.READY,
        file_path=None,
        folder="/lib/M",
        jellyfin_item_id=None,
        pinned=False,
        added_at=datetime(2026, 1, 1, tzinfo=UTC),
        expires_at=None,
        last_checked=None,
        error_kind=None,
        error_msg=None,
    )
    base.update(over)
    return Movie(**base)


class FakeWriter:
    def __init__(self):
        self.deleted = []

    def delete_movie(self, folder):
        self.deleted.append(folder)


class FakeStore:
    def __init__(self):
        self.status_calls = []
        self.logs = []

    def set_status(self, tmdb_id, status, **fields):
        self.status_calls.append((tmdb_id, status, fields))

    def log(self, level, event, message, tmdb_id=None):
        self.logs.append((level, event, message, tmdb_id))


class FakeJellyfin:
    def __init__(self, found="JELLY9"):
        self.found = found
        self.deleted = []
        self.refreshed = 0
        self.calls = []

    def find_item_by_tmdb(self, tmdb_id):
        self.calls.append(("find", tmdb_id))
        return self.found

    def delete_item(self, item_id):
        self.calls.append(("delete", item_id))
        self.deleted.append(item_id)

    def refresh_library(self):
        self.calls.append(("refresh", None))
        self.refreshed += 1


def reaper(**over):
    kw = dict(
        store=FakeStore(),
        writer=FakeWriter(),
        jellyfin=None,
        now_fn=lambda: datetime(2026, 12, 20, 12, 0, tzinfo=UTC),
        grace_days=0,
        tz="UTC",
        count=50,
    )
    kw.update(over)
    return Reaper(**kw)


def test_find_expired_passed():
    r = reaper()
    assert [m.tmdb_id for m in r.find_expired([mkmovie()])] == [1]


def test_find_expired_pinned_skipped():
    r = reaper()
    assert r.find_expired([mkmovie(pinned=True)]) == []


def test_find_expired_none_date_kept():
    r = reaper()
    assert r.find_expired([mkmovie(digital_date=None)]) == []


def test_find_expired_grace_not_yet():
    r = reaper(grace_days=5)  # expiry end of 2026-12-23, now is 12-20
    assert r.find_expired([mkmovie()]) == []


def test_find_expired_end_of_day_boundary():
    # digital date is today (2026-12-20); expiry is end-of-day, now is noon -> keep
    r = reaper()
    m = mkmovie(digital_date=datetime(2026, 12, 20, 0, 0, tzinfo=UTC))
    assert r.find_expired([m]) == []


def test_expire_no_jellyfin():
    store = FakeStore()
    writer = FakeWriter()
    r = reaper(store=store, writer=writer, jellyfin=None)
    r.expire(mkmovie())
    assert writer.deleted == ["/lib/M"]
    assert store.status_calls[0][1] == Status.EXPIRED
    assert store.logs


def test_expire_with_jellyfin_orders_folder_then_delete():
    store = FakeStore()
    writer = FakeWriter()
    jf = FakeJellyfin()
    r = reaper(store=store, writer=writer, jellyfin=jf)
    r.expire(mkmovie())
    assert writer.deleted == ["/lib/M"]  # folder deleted first
    assert jf.deleted == ["JELLY9"]
    assert jf.refreshed == 1
    assert store.status_calls[0][1] == Status.EXPIRED


def test_expire_uses_stored_item_id():
    jf = FakeJellyfin(found="SHOULD_NOT_USE")
    r = reaper(jellyfin=jf)
    r.expire(mkmovie(jellyfin_item_id="STORED1"))
    assert jf.deleted == ["STORED1"]
    assert ("find", 1) not in jf.calls
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/library/test_reaper.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marquee.library.reaper'`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/marquee/library/reaper.py
from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from marquee.models import Movie, Status


def _default_now() -> datetime:
    return datetime.now(tz=UTC)


class Reaper:
    def __init__(
        self,
        store,
        writer,
        jellyfin,
        now_fn=_default_now,
        grace_days: int = 0,
        tz: str = "UTC",
        count: int = 50,
    ):
        self.store = store
        self.writer = writer
        self.jellyfin = jellyfin
        self.now_fn = now_fn
        self.grace_days = grace_days
        self.tz = tz
        self.count = count

    def _expires_at(self, digital_date: datetime) -> datetime:
        tzinfo = ZoneInfo(self.tz)
        local_date = digital_date.astimezone(tzinfo).date() + timedelta(
            days=self.grace_days
        )
        return datetime.combine(local_date, time(23, 59, 59, 999999), tzinfo=tzinfo)

    def find_expired(self, movies: list[Movie]) -> list[Movie]:
        now = self.now_fn()
        out = []
        for m in movies:
            if m.pinned or m.digital_date is None:
                continue
            if now >= self._expires_at(m.digital_date):
                out.append(m)
        return out

    def expire(self, m: Movie) -> None:
        if m.folder:
            self.writer.delete_movie(m.folder)
        if self.jellyfin is not None:
            item_id = m.jellyfin_item_id or self.jellyfin.find_item_by_tmdb(m.tmdb_id)
            if item_id:
                self.jellyfin.delete_item(item_id)
            self.jellyfin.refresh_library()
        self.store.set_status(m.tmdb_id, Status.EXPIRED)
        # NOTE: the Reaper's contract signature has no `broadcaster` reference, so
        # expiry uses `store.log` (persist-only) rather than the pipeline's
        # `emit_log` live-fan-out helper. This is intentional: reaper runs are a
        # separate cron job whose rows surface on the next SSE backlog fetch. If a
        # future iteration wants live expiry events, add a `broadcaster` param here
        # and swap this for `emit_log(...)` — the row shape is identical.
        self.store.log("info", "expired", f"Expired {m.title}", m.tmdb_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/library/test_reaper.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/marquee/library/reaper.py tests/library/test_reaper.py
git commit -m "feat: Reaper end-of-day expiry with grace/pin protection and JF ghost delete"
```

---

### Task 5: SSE Broadcaster (`api/sse.py`)

**Files:**
- Create: `backend/marquee/api/__init__.py`, `backend/marquee/api/sse.py`
- Test: `tests/api/test_sse.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Broadcaster()` with `subscribe()->asyncio.Queue`, `unsubscribe(q)`, `publish(event: dict)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_sse.py
import asyncio

import pytest

from marquee.api.sse import Broadcaster


def test_fanout_to_all_subscribers():
    b = Broadcaster()
    q1 = b.subscribe()
    q2 = b.subscribe()
    b.publish({"a": 1})
    assert q1.get_nowait() == {"a": 1}
    assert q2.get_nowait() == {"a": 1}


def test_unsubscribe_stops_delivery():
    b = Broadcaster()
    q1 = b.subscribe()
    q2 = b.subscribe()
    b.unsubscribe(q2)
    b.publish({"b": 2})
    assert q1.get_nowait() == {"b": 2}
    with pytest.raises(asyncio.QueueEmpty):
        q2.get_nowait()


def test_publish_with_no_subscribers_is_noop():
    b = Broadcaster()
    b.publish({"c": 3})  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/api/test_sse.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marquee.api'`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/marquee/api/__init__.py` (empty file), then:

```python
# backend/marquee/api/sse.py
from __future__ import annotations

import asyncio


class Broadcaster:
    def __init__(self, maxsize: int = 1000):
        self._subscribers: set[asyncio.Queue] = set()
        self._maxsize = maxsize

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._maxsize)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def publish(self, event: dict) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/api/test_sse.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/marquee/api/__init__.py backend/marquee/api/sse.py tests/api/test_sse.py
git commit -m "feat: SSE Broadcaster with asyncio-queue fan-out"
```

---

### Task 6: Refresh pipeline (`pipeline.py`)

**Files:**
- Create: `backend/marquee/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `discover(client, sources, region, language, count)` and `enrich(client, cand, region, language)` (from `marquee.tmdb.curator`, patched in module namespace); `TrailerDownloader.download(url, dest_dir, tmdb_id)->DownloadResult`; `DownloadFailed`; `LibraryWriter.write_movie(m, source_video)->WrittenMovie`; `JellyfinClient.refresh_library()`; `Store` (`get_movie`, `upsert_movie`, `set_status`, `log`); `Broadcaster.publish`; `Config`; `Movie`/`Status`/`ErrorKind`/`EnrichedMovie` from `marquee.models`.
- Produces: `RunSummary(discovered, downloaded, skipped, failed, expired)`; `RefreshPipeline(client, downloader, writer, reaper, jellyfin, store, config, broadcaster)` with `run()->RunSummary`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline.py
import os
import shutil

from datetime import UTC, datetime

from marquee.config import Config
from marquee.store import Store
from marquee.models import EnrichedMovie, MovieCandidate, Status
from marquee.downloader import DownloadResult, DownloadFailed, ProbeResult
from marquee.models import ErrorKind
from marquee.library.writer import WrittenMovie
from marquee import pipeline as pipeline_mod
from marquee.pipeline import RefreshPipeline, RunSummary
from marquee.api.sse import Broadcaster


def make_config(tmp_path):
    return Config(
        tmdb_token="x",
        sources=["upcoming"],
        config_dir=str(tmp_path / "config"),
        library_dir=str(tmp_path / "lib"),
        count=50,
        region="US",
        language="en-US",
    )


def make_enriched(**over):
    from marquee.models import TrailerVideo

    base = dict(
        tmdb_id=1,
        title="M",
        year=2026,
        overview="o",
        popularity=9.0,
        source="upcoming",
        poster_path="/p.jpg",
        backdrop_path=None,
        runtime=100,
        genres=[],
        studios=[],
        certification=None,
        premiere_date="2026-12-18",
        digital_date=None,
        digital_date_source="none",
        youtube_key="YT1",
        trailer=TrailerVideo(
            key="YT1",
            site="YouTube",
            type="Trailer",
            official=True,
            size=1080,
            iso_639_1="en",
            published_at="2026-06-01",
        ),
    )
    base.update(over)
    return EnrichedMovie(**base)


def _ok_probe():
    return ProbeResult(ok=True, duration=90, title="M", has_maxheight=True, availability="public")


class FakeDownloader:
    def __init__(self, probe_ok=True):
        self.calls = []
        self.probe_calls = []
        self._probe_ok = probe_ok

    def probe(self, url):
        self.probe_calls.append(url)
        return ProbeResult(
            ok=self._probe_ok, duration=90, title="M",
            has_maxheight=self._probe_ok, availability="public",
        )

    def download(self, url, dest_dir, tmdb_id):
        self.calls.append((url, tmdb_id))
        os.makedirs(dest_dir, exist_ok=True)
        p = os.path.join(dest_dir, f"{tmdb_id}.mkv")
        open(p, "wb").close()
        return DownloadResult(path=p, title="M", duration=90, ext="mkv", video_id=str(tmdb_id))


class FailingDownloader:
    def probe(self, url):
        return _ok_probe()

    def download(self, url, dest_dir, tmdb_id):
        raise DownloadFailed(ErrorKind.BOT_CHECK, "bot")


class FakeWriter:
    def __init__(self, libdir):
        self.libdir = libdir

    def write_movie(self, m, source_video):
        folder = os.path.join(self.libdir, str(m.tmdb_id))
        os.makedirs(folder, exist_ok=True)
        vp = os.path.join(folder, "movie.mkv")
        shutil.move(source_video, vp)
        return WrittenMovie(
            folder=folder, video_path=vp, nfo_path=os.path.join(folder, "movie.nfo"),
            poster_path=None, backdrop_path=None,
        )


class FakeJellyfin:
    def __init__(self):
        self.refreshed = 0

    def refresh_library(self):
        self.refreshed += 1


def build(tmp_path, downloader, monkeypatch, candidates, enriched_list):
    cfg = make_config(tmp_path)
    store = Store(str(tmp_path / "state.db"))
    it = iter(enriched_list)
    monkeypatch.setattr(pipeline_mod, "discover", lambda *a, **k: candidates)
    monkeypatch.setattr(pipeline_mod, "enrich", lambda *a, **k: next(it))
    jf = FakeJellyfin()
    p = RefreshPipeline(
        client=object(),
        downloader=downloader,
        writer=FakeWriter(cfg.library_dir),
        reaper=object(),
        jellyfin=jf,
        store=store,
        config=cfg,
        broadcaster=Broadcaster(),
    )
    return p, store, jf


def cand(tmdb_id=1):
    return MovieCandidate(
        tmdb_id=tmdb_id, title="M", year=2026, overview="o", popularity=9.0,
        poster_path="/p.jpg", backdrop_path=None, source="upcoming",
        release_date="2026-12-18",
    )


def test_run_downloads_and_writes(tmp_path, monkeypatch):
    dl = FakeDownloader()
    p, store, jf = build(tmp_path, dl, monkeypatch, [cand()], [make_enriched()])
    summary = p.run()
    assert isinstance(summary, RunSummary)
    assert summary.discovered == 1
    assert summary.downloaded == 1
    assert summary.failed == 0
    m = store.get_movie(1)
    assert m.status == Status.READY
    assert m.file_path and os.path.exists(m.file_path)
    assert jf.refreshed == 1
    assert dl.calls == [("https://www.youtube.com/watch?v=YT1", 1)]


def test_run_idempotent_skips_ready(tmp_path, monkeypatch):
    dl = FakeDownloader()
    p, store, jf = build(tmp_path, dl, monkeypatch, [cand()], [make_enriched()])
    p.run()
    # second pass: re-inject discover/enrich to return same movie
    monkeypatch.setattr(pipeline_mod, "discover", lambda *a, **k: [cand()])
    it = iter([make_enriched()])
    monkeypatch.setattr(pipeline_mod, "enrich", lambda *a, **k: next(it))
    summary = p.run()
    assert summary.skipped == 1
    assert summary.downloaded == 0
    assert len(dl.calls) == 1  # not re-downloaded


def test_run_no_trailer_marks_failed(tmp_path, monkeypatch):
    dl = FakeDownloader()
    p, store, jf = build(
        tmp_path, dl, monkeypatch, [cand()], [make_enriched(youtube_key=None, trailer=None)]
    )
    summary = p.run()
    assert summary.failed == 1
    assert summary.downloaded == 0
    m = store.get_movie(1)
    assert m.status == Status.FAILED
    assert m.error_kind == ErrorKind.NO_TRAILER.value


def test_run_download_failure_marks_failed(tmp_path, monkeypatch):
    p, store, jf = build(tmp_path, FailingDownloader(), monkeypatch, [cand()], [make_enriched()])
    summary = p.run()
    assert summary.failed == 1
    m = store.get_movie(1)
    assert m.status == Status.FAILED
    assert m.error_kind == ErrorKind.BOT_CHECK.value


def test_run_probe_not_ok_marks_failed_and_skips_download(tmp_path, monkeypatch):
    dl = FakeDownloader(probe_ok=False)
    p, store, jf = build(tmp_path, dl, monkeypatch, [cand()], [make_enriched()])
    summary = p.run()
    assert summary.failed == 1
    assert summary.downloaded == 0
    m = store.get_movie(1)
    assert m.status == Status.FAILED
    assert m.error_kind == ErrorKind.NO_FORMAT.value
    assert dl.probe_calls == ["https://www.youtube.com/watch?v=YT1"]
    assert dl.calls == []  # download() NOT called
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marquee.pipeline'`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/marquee/pipeline.py
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime

from marquee.config import Config
from marquee.models import EnrichedMovie, ErrorKind, Movie, Status
from marquee.downloader import DownloadFailed
from marquee.tmdb.curator import discover, enrich


@dataclass
class RunSummary:
    discovered: int
    downloaded: int
    skipped: int
    failed: int
    expired: int


def emit_log(store, broadcaster, level, event, message, tmdb_id=None) -> None:
    """Persist a log row AND fan it out to SSE subscribers as a contract
    `{"type":"log","entry":{...}}` event, keeping all live pipeline output
    within the SSE log|progress tagged union."""
    row = {"level": level, "event": event, "message": message, "tmdb_id": tmdb_id}
    store.log(level, event, message, tmdb_id)
    broadcaster.publish({"type": "log", "entry": row})


def _row(e: EnrichedMovie, config: Config, status: Status, now: datetime) -> Movie:
    return Movie(
        tmdb_id=e.tmdb_id,
        title=e.title,
        year=e.year,
        overview=e.overview,
        runtime=e.runtime,
        genres=e.genres,
        studios=e.studios,
        certification=e.certification,
        premiere_date=e.premiere_date,
        digital_date=e.digital_date,
        digital_date_source=e.digital_date_source,
        region=config.region,
        popularity=e.popularity,
        poster_path=e.poster_path,
        backdrop_path=e.backdrop_path,
        youtube_key=e.youtube_key,
        status=status,
        file_path=None,
        folder=None,
        jellyfin_item_id=None,
        pinned=False,
        added_at=now,
        expires_at=None,
        last_checked=now,
        error_kind=None,
        error_msg=None,
    )


class RefreshPipeline:
    def __init__(
        self, client, downloader, writer, reaper, jellyfin, store, config, broadcaster
    ):
        self.client = client
        self.downloader = downloader
        self.writer = writer
        self.reaper = reaper
        self.jellyfin = jellyfin
        self.store = store
        self.config = config
        self.broadcaster = broadcaster

    def run(self) -> RunSummary:
        now = datetime.now(tz=UTC)
        temp_dir = os.path.join(self.config.config_dir, "tmp")
        os.makedirs(temp_dir, exist_ok=True)

        candidates = discover(
            self.client,
            self.config.sources,
            self.config.region,
            self.config.language,
            self.config.count,
        )
        summary = RunSummary(
            discovered=len(candidates), downloaded=0, skipped=0, failed=0, expired=0
        )
        emit_log(
            self.store,
            self.broadcaster,
            "info",
            "run_start",
            f"Refresh started: {len(candidates)} discovered",
        )

        for cand in candidates:
            existing = self.store.get_movie(cand.tmdb_id)
            enriched = enrich(
                self.client, cand, self.config.region, self.config.language
            )

            if enriched.youtube_key is None:
                row = _row(enriched, self.config, Status.FAILED, now)
                if existing:
                    row.pinned = existing.pinned
                    row.added_at = existing.added_at
                row.error_kind = ErrorKind.NO_TRAILER.value
                row.error_msg = "no trailer found"
                self.store.upsert_movie(row)
                emit_log(
                    self.store,
                    self.broadcaster,
                    "warn",
                    "no_trailer",
                    f"No trailer for {enriched.title}",
                    enriched.tmdb_id,
                )
                summary.failed += 1
                continue

            if (
                existing
                and existing.status == Status.READY
                and existing.youtube_key == enriched.youtube_key
                and existing.file_path
                and os.path.exists(existing.file_path)
            ):
                self.store.set_status(
                    enriched.tmdb_id,
                    Status.READY,
                    popularity=enriched.popularity,
                    last_checked=now,
                )
                summary.skipped += 1
                continue

            row = _row(enriched, self.config, Status.DOWNLOADING, now)
            if existing:
                row.pinned = existing.pinned
                row.jellyfin_item_id = existing.jellyfin_item_id
                row.added_at = existing.added_at
            self.store.upsert_movie(row)
            emit_log(
                self.store,
                self.broadcaster,
                "info",
                "download_start",
                f"Downloading {enriched.title}",
                enriched.tmdb_id,
            )

            # Pre-validate the trailer before spending a full download (spec §4.5/§7).
            probe_res = self.downloader.probe(enriched.trailer.youtube_url)
            if not probe_res.ok:
                self.store.set_status(
                    enriched.tmdb_id,
                    Status.FAILED,
                    error_kind=ErrorKind.NO_FORMAT.value,
                    error_msg="pre-validate failed: no suitable format",
                    last_checked=now,
                )
                emit_log(
                    self.store,
                    self.broadcaster,
                    "error",
                    "no_format",
                    f"Pre-validate failed for {enriched.title}",
                    enriched.tmdb_id,
                )
                summary.failed += 1
                continue

            try:
                result = self.downloader.download(
                    enriched.trailer.youtube_url, temp_dir, enriched.tmdb_id
                )
            except DownloadFailed as e:
                self.store.set_status(
                    enriched.tmdb_id,
                    Status.FAILED,
                    error_kind=e.kind.value,
                    error_msg=e.message,
                    last_checked=now,
                )
                emit_log(
                    self.store,
                    self.broadcaster,
                    "error",
                    "download_failed",
                    f"{enriched.title}: {e.message}",
                    enriched.tmdb_id,
                )
                summary.failed += 1
                continue

            written = self.writer.write_movie(enriched, result.path)
            self.store.set_status(
                enriched.tmdb_id,
                Status.READY,
                file_path=written.video_path,
                folder=written.folder,
                last_checked=now,
            )
            emit_log(
                self.store,
                self.broadcaster,
                "info",
                "ready",
                f"Downloaded {enriched.title}",
                enriched.tmdb_id,
            )
            summary.downloaded += 1

        if self.jellyfin is not None:
            self.jellyfin.refresh_library()
        emit_log(
            self.store,
            self.broadcaster,
            "info",
            "run_done",
            f"Refresh complete: {summary.downloaded} downloaded, "
            f"{summary.skipped} skipped, {summary.failed} failed",
        )
        return summary
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/marquee/pipeline.py tests/test_pipeline.py
git commit -m "feat: RefreshPipeline discover-enrich-download-write with idempotent skips"
```

---

### Task 7: Scheduler (`scheduler.py`)

**Files:**
- Create: `backend/marquee/scheduler.py`
- Modify: `pyproject.toml` (add `apscheduler` dependency)
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `RefreshPipeline.run()`; `Reaper.find_expired(movies)`/`expire(m)`; `Store.list_movies([Status])`/`log`; `Config` (`.refresh_cron`, `.reaper_cron`, `.tz`); `Status` from `marquee.models`.
- Produces: `Scheduler(pipeline, reaper, store, config)` with `start()`, `stop()`, `trigger_refresh()`, `trigger_reap()`, `status()->dict`.

- [ ] **Step 1: Add the APScheduler dependency**

In `pyproject.toml`, add `"apscheduler>=3.10"` to the `[project]` `dependencies` array (alongside the Plan-1 entries), then install:

Run: `pip install "apscheduler>=3.10"`
Expected: APScheduler installs successfully.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_scheduler.py
from datetime import UTC, datetime

from marquee.config import Config
from marquee.store import Store
from marquee.models import Movie, Status
from marquee.scheduler import Scheduler


def make_config(tmp_path):
    return Config(tmdb_token="x", sources=["upcoming"], config_dir=str(tmp_path),
                  library_dir=str(tmp_path / "lib"), tz="UTC")


class FakePipeline:
    def __init__(self):
        self.runs = 0

    def run(self):
        self.runs += 1


class FakeReaper:
    def __init__(self):
        self.expired = []

    def find_expired(self, movies):
        return list(movies)

    def expire(self, m):
        self.expired.append(m.tmdb_id)


def mkmovie(tmdb_id=1):
    return Movie(
        tmdb_id=tmdb_id, title="M", year=2026, overview="", runtime=1, genres=[],
        studios=[], certification=None, premiere_date=None, digital_date=None,
        digital_date_source="none", region="US", popularity=1.0, poster_path=None,
        backdrop_path=None, youtube_key="k", status=Status.READY, file_path=None,
        folder="/lib/M", jellyfin_item_id=None, pinned=False,
        added_at=datetime(2026, 1, 1, tzinfo=UTC), expires_at=None, last_checked=None,
        error_kind=None, error_msg=None,
    )


def build(tmp_path):
    cfg = make_config(tmp_path)
    store = Store(str(tmp_path / "s.db"))
    pipeline = FakePipeline()
    reaper = FakeReaper()
    return Scheduler(pipeline, reaper, store, cfg), pipeline, reaper, store


def test_trigger_refresh_runs_pipeline(tmp_path):
    sch, pipeline, reaper, store = build(tmp_path)
    sch.trigger_refresh()
    assert pipeline.runs == 1


def test_single_flight_skips_when_locked(tmp_path):
    sch, pipeline, reaper, store = build(tmp_path)
    assert sch._lock.acquire(blocking=False)
    try:
        sch.trigger_refresh()  # lock held -> must skip
        assert pipeline.runs == 0
    finally:
        sch._lock.release()
    sch.trigger_refresh()
    assert pipeline.runs == 1


def test_trigger_reap_expires_ready(tmp_path):
    sch, pipeline, reaper, store = build(tmp_path)
    store.upsert_movie(mkmovie(1))
    sch.trigger_reap()
    assert reaper.expired == [1]


def test_status_reports_after_start(tmp_path):
    sch, pipeline, reaper, store = build(tmp_path)
    sch.start()
    try:
        st = sch.status()
        assert set(st) == {"next_refresh", "next_reap", "running"}
        assert st["running"] is False
    finally:
        sch.stop()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_scheduler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marquee.scheduler'`.

- [ ] **Step 4: Write minimal implementation**

```python
# backend/marquee/scheduler.py
from __future__ import annotations

import threading
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from marquee.models import Status


class Scheduler:
    def __init__(self, pipeline, reaper, store, config):
        self._pipeline = pipeline
        self._reaper = reaper
        self._store = store
        self._config = config
        self._tz = ZoneInfo(config.tz)
        self._sched = BackgroundScheduler(timezone=self._tz)
        self._lock = threading.Lock()
        self._running = False

    def start(self) -> None:
        self._sched.add_job(
            self.trigger_refresh,
            CronTrigger.from_crontab(self._config.refresh_cron, timezone=self._tz),
            id="refresh",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        self._sched.add_job(
            self.trigger_reap,
            CronTrigger.from_crontab(self._config.reaper_cron, timezone=self._tz),
            id="reap",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        self._sched.start()

    def stop(self) -> None:
        if self._sched.running:
            self._sched.shutdown(wait=False)

    def trigger_refresh(self) -> None:
        if not self._lock.acquire(blocking=False):
            self._store.log("warn", "skip", "refresh skipped: run already in progress")
            return
        try:
            self._running = True
            self._pipeline.run()
        finally:
            self._running = False
            self._lock.release()

    def trigger_reap(self) -> None:
        if not self._lock.acquire(blocking=False):
            self._store.log("warn", "skip", "reap skipped: run already in progress")
            return
        try:
            self._running = True
            movies = self._store.list_movies([Status.READY])
            for m in self._reaper.find_expired(movies):
                self._reaper.expire(m)
        finally:
            self._running = False
            self._lock.release()

    def status(self) -> dict:
        def nxt(job_id: str):
            job = self._sched.get_job(job_id) if self._sched.running else None
            return job.next_run_time.isoformat() if job and job.next_run_time else None

        return {
            "next_refresh": nxt("refresh"),
            "next_reap": nxt("reap"),
            "running": self._running,
        }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_scheduler.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/marquee/scheduler.py tests/test_scheduler.py pyproject.toml
git commit -m "feat: APScheduler wrapper with single-flight refresh/reap triggers"
```

---

### Task 8: FastAPI app + routes (`api/app.py`, `api/routes.py`)

**Files:**
- Create: `backend/marquee/api/app.py`, `backend/marquee/api/routes.py`
- Modify: `pyproject.toml` (add `fastapi`, `uvicorn[standard]`)
- Test: `tests/api/test_api.py`

**Interfaces:**
- Consumes: `Store` (`list_movies`, `get_movie`, `set_status`, `set_pinned`, `all_settings`, `set_setting`, `recent_activity`); `Scheduler` (`trigger_refresh`, `trigger_reap`, `status`); `Reaper.expire(m)`; `Broadcaster` (`subscribe`, `unsubscribe`); `JellyfinClient.test()`; `Config`; `Status` from `marquee.models`.
- Produces: `AppContext(store, scheduler, reaper, config, broadcaster, static_dir=None)`; `create_app(context)->FastAPI`; `build_router(context)->APIRouter`; `serialize_movie(m)->dict`.

- [ ] **Step 1: Add FastAPI/uvicorn dependencies**

In `pyproject.toml`, add `"fastapi>=0.111"` and `"uvicorn[standard]>=0.30"` to the `[project]` `dependencies` array, then install:

Run: `pip install "fastapi>=0.111" "uvicorn[standard]>=0.30" httpx`
Expected: installs succeed (httpx already present via Plan 1; TestClient needs it).

- [ ] **Step 2: Write the failing test**

```python
# tests/api/test_api.py
from datetime import UTC, datetime

import httpx
import respx
from fastapi.testclient import TestClient

from marquee.config import Config
from marquee.store import Store
from marquee.models import Movie, Status
from marquee.api.sse import Broadcaster
from marquee.api.app import AppContext, create_app


class FakeScheduler:
    def __init__(self):
        self.refresh = 0
        self.reap = 0

    def trigger_refresh(self):
        self.refresh += 1

    def trigger_reap(self):
        self.reap += 1

    def status(self):
        return {"next_refresh": None, "next_reap": None, "running": False}


class FakeReaper:
    def __init__(self):
        self.expired = []

    def expire(self, m):
        self.expired.append(m.tmdb_id)


def mkmovie(tmdb_id=1, **over):
    base = dict(
        tmdb_id=tmdb_id, title="M", year=2026, overview="", runtime=1, genres=[],
        studios=[], certification=None, premiere_date=None, digital_date=None,
        digital_date_source="none", region="US", popularity=1.0, poster_path=None,
        backdrop_path=None, youtube_key="k", status=Status.READY, file_path=None,
        folder="/lib/M", jellyfin_item_id=None, pinned=False,
        added_at=datetime(2026, 1, 1, tzinfo=UTC), expires_at=None, last_checked=None,
        error_kind=None, error_msg=None,
    )
    base.update(over)
    return Movie(**base)


def build(tmp_path, static_dir=None, jellyfin_url=None):
    store = Store(str(tmp_path / "s.db"))
    cfg = Config(tmdb_token="x", sources=["upcoming"], config_dir=str(tmp_path),
                 library_dir=str(tmp_path / "lib"), jellyfin_url=jellyfin_url,
                 jellyfin_api_key="APIKEY")
    sched = FakeScheduler()
    reaper = FakeReaper()
    ctx = AppContext(store=store, scheduler=sched, reaper=reaper, config=cfg,
                     broadcaster=Broadcaster(), static_dir=static_dir)
    return TestClient(create_app(ctx)), store, sched, reaper


def test_health(tmp_path):
    client, *_ = build(tmp_path)
    assert client.get("/api/health").json() == {"status": "ok"}


def test_movies_list_and_get(tmp_path):
    client, store, *_ = build(tmp_path)
    store.upsert_movie(mkmovie(1))
    data = client.get("/api/movies").json()
    assert [m["tmdb_id"] for m in data] == [1]
    assert data[0]["status"] == "ready"
    # API-added fields present (see contract "API JSON & SSE Contract")
    assert data[0]["poster_url"] is None
    assert data[0]["backdrop_url"] is None
    assert data[0]["download_pct"] is None
    assert client.get("/api/movies/1").json()["tmdb_id"] == 1
    assert client.get("/api/movies/999").status_code == 404


def test_poster_url_built_from_path(tmp_path):
    client, store, *_ = build(tmp_path)
    store.upsert_movie(mkmovie(1, poster_path="/abc.jpg", backdrop_path="/bg.jpg"))
    m = client.get("/api/movies/1").json()
    assert m["poster_url"] == "https://image.tmdb.org/t/p/w500/abc.jpg"
    assert m["backdrop_url"] == "https://image.tmdb.org/t/p/w1280/bg.jpg"


def test_pin_toggle(tmp_path):
    client, store, *_ = build(tmp_path)
    store.upsert_movie(mkmovie(1, pinned=False))
    body = client.post("/api/movies/1/pin").json()  # returns the updated movie
    assert body["tmdb_id"] == 1
    assert body["pinned"] is True
    assert store.get_movie(1).pinned is True


def test_settings_round_trip(tmp_path):
    client, store, *_ = build(tmp_path)
    put = client.put("/api/settings", json={"count": "25"})
    assert put.status_code == 200
    assert put.json()["count"] == 25          # flat public Config, coerced to int
    got = client.get("/api/settings").json()
    assert got["count"] == 25
    assert got["tmdb_token"] == "***"         # secret masked


def test_run_and_reap_trigger(tmp_path):
    client, store, sched, reaper = build(tmp_path)
    assert client.post("/api/run").status_code == 200
    assert client.post("/api/reap").status_code == 200
    assert sched.refresh == 1
    assert sched.reap == 1


def test_download_now_queues_and_triggers(tmp_path):
    client, store, sched, reaper = build(tmp_path)
    store.upsert_movie(mkmovie(1, status=Status.FAILED))
    assert client.post("/api/movies/1/download").status_code == 200
    assert store.get_movie(1).status == Status.QUEUED
    assert sched.refresh == 1


def test_delete_now_expires(tmp_path):
    client, store, sched, reaper = build(tmp_path)
    store.upsert_movie(mkmovie(1))
    assert client.request("DELETE", "/api/movies/1").status_code == 200
    assert reaper.expired == [1]


def test_status(tmp_path):
    client, store, *_ = build(tmp_path)
    store.upsert_movie(mkmovie(1, status=Status.READY))
    body = client.get("/api/status").json()
    assert body["running"] is False            # flat StatusSummary
    assert body["counts"]["ready"] == 1
    assert set(body["disk"]) == {"used_gb", "free_gb", "total_gb"}
    assert "ytdlp_version" in body


@respx.mock
def test_jellyfin_test(tmp_path):
    respx.get("http://jelly:8096/System/Info").mock(
        return_value=httpx.Response(200, json={"Version": "10.11"})
    )
    client, *_ = build(tmp_path, jellyfin_url="http://jelly:8096")
    assert client.post("/api/jellyfin/test").json() == {"ok": True}


def test_spa_catch_all_does_not_shadow_api(tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>SPA</html>")
    client, *_ = build(tmp_path, static_dir=str(static))
    # API still works
    assert client.get("/api/health").json() == {"status": "ok"}
    # Unknown SPA route returns index
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "SPA" in r.text
    # Unknown /api path is 404, not the SPA
    assert client.get("/api/nope").status_code == 404
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/api/test_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marquee.api.app'`.

- [ ] **Step 4: Write minimal implementation**

```python
# backend/marquee/api/routes.py
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import StreamingResponse

from marquee.jellyfin import JellyfinClient
from marquee.models import Movie, Status

_SECRET_KEYS = {"tmdb_token", "jellyfin_api_key", "jellyfin_pass"}


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

        return {"version": yt_dlp.version.__version__}

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

    @router.get("/activity")
    async def activity(request: Request):
        q = context.broadcaster.subscribe()

        async def gen():
            try:
                # Backlog: wrap each stored row as a tagged {"type":"log","entry":...}
                for row in context.store.recent_activity(50):
                    ev = {"type": "log", "entry": row}
                    yield f"data: {json.dumps(ev, default=str)}\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        # Live events are already tagged by the publisher:
                        # {"type":"log","entry":...} or {"type":"progress",...}
                        ev = await asyncio.wait_for(q.get(), timeout=15.0)
                        yield f"data: {json.dumps(ev, default=str)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                context.broadcaster.unsubscribe(q)

        return StreamingResponse(gen(), media_type="text/event-stream")

    return router
```

```python
# backend/marquee/api/app.py
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
            if full_path.startswith("api"):
                raise HTTPException(status_code=404, detail="not found")
            candidate = (base / full_path).resolve()
            if full_path and candidate.is_file() and candidate.is_relative_to(base):
                return FileResponse(str(candidate))
            return FileResponse(str(index_path))

    return app
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/api/test_api.py -v`
Expected: PASS (11 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/marquee/api/app.py backend/marquee/api/routes.py tests/api/test_api.py pyproject.toml
git commit -m "feat: FastAPI app factory and /api routes with SPA catch-all"
```

---

### Task 9: CLI entrypoint (`__main__.py`)

**Files:**
- Create: `backend/marquee/__main__.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `load_config(env, overrides)`; `Store`, `TMDBClient`, `TrailerDownloader`, `LibraryWriter`, `JellyfinClient`, `Reaper`, `RefreshPipeline`, `Scheduler`, `Broadcaster`, `AppContext`, `create_app`; `discover` (curator); `Status` from `marquee.models`.
- Produces: `Components` dataclass; `build_components(config)->Components`; `cmd_run(config)`, `cmd_reap(config)`, `cmd_discover(config)`, `cmd_serve(config)`; `main(argv=None)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_main.py
from types import SimpleNamespace

import marquee.__main__ as m
from marquee.models import Status


class FakePipeline:
    def __init__(self):
        self.runs = 0

    def run(self):
        self.runs += 1


class FakeReaper:
    def __init__(self):
        self.expired = []

    def find_expired(self, movies):
        return list(movies)

    def expire(self, movie):
        self.expired.append(movie)


class FakeStore:
    def __init__(self, movies):
        self._movies = movies

    def list_movies(self, statuses=None):
        return list(self._movies)


def fake_components(pipeline=None, reaper=None, store=None):
    return m.Components(
        store=store or FakeStore([]),
        client=object(),
        downloader=object(),
        writer=object(),
        jellyfin=None,
        reaper=reaper or FakeReaper(),
        pipeline=pipeline or FakePipeline(),
        scheduler=object(),
        broadcaster=object(),
        config=object(),
    )


def test_main_run_invokes_pipeline(monkeypatch):
    pipeline = FakePipeline()
    comps = fake_components(pipeline=pipeline)
    monkeypatch.setattr(m, "build_components", lambda config: comps)
    monkeypatch.setattr(m, "load_config", lambda env, overrides=None: object())
    m.main(["run"])
    assert pipeline.runs == 1


def test_main_reap_invokes_reaper(monkeypatch):
    reaper = FakeReaper()
    store = FakeStore([SimpleNamespace(tmdb_id=1)])
    comps = fake_components(reaper=reaper, store=store)
    monkeypatch.setattr(m, "build_components", lambda config: comps)
    monkeypatch.setattr(m, "load_config", lambda env, overrides=None: object())
    m.main(["reap"])
    assert len(reaper.expired) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marquee.__main__'` (or `AttributeError` on `Components`).

- [ ] **Step 3: Write minimal implementation**

```python
# backend/marquee/__main__.py
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass

from marquee.config import Config, load_config
from marquee.store import Store
from marquee.tmdb.client import TMDBClient
from marquee.tmdb.curator import discover
from marquee.downloader import TrailerDownloader
from marquee.library.writer import LibraryWriter
from marquee.library.reaper import Reaper
from marquee.jellyfin import JellyfinClient
from marquee.pipeline import RefreshPipeline
from marquee.scheduler import Scheduler
from marquee.api.sse import Broadcaster
from marquee.api.app import AppContext, create_app
from marquee.models import Status


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


def cmd_discover(config: Config) -> None:
    comps = build_components(config)
    cands = discover(
        comps.client, config.sources, config.region, config.language, config.count
    )
    for c in cands:
        print(f"{c.tmdb_id:>8}  {c.popularity:8.1f}  {c.title}")


def cmd_serve(config: Config) -> None:
    import uvicorn

    comps = build_components(config)
    comps.scheduler.start()
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    context = AppContext(
        store=comps.store,
        scheduler=comps.scheduler,
        reaper=comps.reaper,
        config=config,
        broadcaster=comps.broadcaster,
        static_dir=static_dir if os.path.isdir(static_dir) else None,
    )
    app = create_app(context)
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "3022")))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="marquee")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("discover", "run", "reap", "serve"):
        sub.add_parser(name)
    args = parser.parse_args(argv)

    config = load_config(os.environ)
    {
        "discover": cmd_discover,
        "run": cmd_run,
        "reap": cmd_reap,
        "serve": cmd_serve,
    }[args.cmd](config)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_main.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the full backend suite**

Run: `pytest tests/ -v`
Expected: PASS (all Plan-1 and Plan-2 tests green).

- [ ] **Step 6: Commit**

```bash
git add backend/marquee/__main__.py tests/test_main.py
git commit -m "feat: CLI discover/run/reap/serve subcommands wiring the backend"
```

---

## Self-Review

### 1. Spec coverage

| Spec requirement | Task |
|---|---|
| §7 Downloader format string, `merge_output_format`, `player_client` fallback, cookies/proxy, `requested_downloads[0].filepath`, error classification, progress hooks, pre-validate probe | Task 1 |
| §5 Folder/file naming (video begins with folder name), sanitization of illegal chars | Task 2 |
| §5 `movie.nfo` fields (golden), poster `w500` / backdrop `w1280` fetch+write | Task 2 |
| §5/§8 Image URLs via `build_image_url` (w500/w1280) | Task 2 (consumes Plan-1 client) |
| §5/§6 Jellyfin `System/Info` test, `Library/Refresh`, `AuthenticateByName` (cached admin token), find-by-tmdb, `DELETE /Items` | Task 3 |
| §6 Expiry: `digital_date + grace_days` end-of-day in tz, pin protection, keep when no date | Task 4 |
| §6 Ghost mitigation: delete folder first, then admin `DELETE /Items`, then scan; use stored `jellyfin_item_id` else look up | Task 4 |
| §4 Refresh pipeline discover→enrich→skip-if-ready(dedupe tmdb_id+youtube_key)→download→write→status transitions→JF refresh; idempotent | Task 6 |
| §4/§7 No-trailer → skip+log; download failure → classify+`failed`+retry-next-run | Task 6 |
| §7/§12 Progress hooks feed SSE stream (non-blocking queue fan-out) | Task 5 + Task 1 (`on_progress`) + Task 9 (wiring) |
| §3 APScheduler cron refresh+reaper jobs, single-flight lock, on-demand triggers, status | Task 7 |
| §11 All `/api` routes (movies, pin, delete, settings, run, reap, activity SSE, status, health, ytdlp/update, jellyfin/test) | Task 8 |
| §3/§13 SPA served via StaticFiles catch-all; `/api` never shadowed | Task 8 |
| §17 CLI sequencing entrypoints (`discover`/`run`/`reap`/`serve`; serve launches uvicorn + scheduler) | Task 9 |
| §9 Persisted `Movie` rows with status transitions, error_kind/error_msg, activity log | Tasks 6, 4, 8 (via Plan-1 `Store`) |

**Gaps intentionally out of this plan's slice:** TMDB client/curator, models, config, store (Plan 1); React SPA build (Plan 3); Dockerfile/compose/CI/README (Plan 3). `MAX_SIZE_GB` LRU overflow eviction (§4 step 8) is spec-optional and default-off; not implemented here — flagged below for the orchestrator.

### 2. Placeholder scan

Searched for TBD / TODO / "add error handling" / "similar to Task N" / "write tests for the above" / bare ellipses in code bodies: none present. Every code step contains complete, runnable code. Cross-references between tasks appear only in the `Interfaces` blocks (signatures), never as substitutes for code — each implementation and test is spelled out in full, including repeated `mkmovie`/`make_config` helpers per test file.

### 3. Type consistency against the contract

- `ProbeResult`, `DownloadResult`, `DownloadFailed(kind, message)`, `TrailerDownloader(config, on_progress=None)` — match contract §downloader verbatim; `download()` reads `info["requested_downloads"][0]["filepath"]` and raises `DownloadFailed`.
- `WrittenMovie`, `LibraryWriter(library_dir, client)` with `sanitize` (staticmethod), `folder_name`, `render_nfo`, `write_movie`, `delete_movie` — match contract §writer.
- `JellyfinClient(url, api_key, username=None, password=None, session=None)` with `test`/`refresh_library`/`authenticate`/`find_item_by_tmdb`/`delete_item` — match contract §jellyfin; DELETE uses admin token, refresh/find use API key.
- `Reaper(store, writer, jellyfin, now_fn=..., grace_days=0, tz="UTC", count=50)` with `find_expired`/`expire` — match contract §reaper.
- `RunSummary(discovered, downloaded, skipped, failed, expired)` and `RefreshPipeline(client, downloader, writer, reaper, jellyfin, store, config, broadcaster).run()` — match contract §pipeline verbatim (positional order preserved).
- `Scheduler(pipeline, reaper, store, config)` with `start`/`stop`/`trigger_refresh`/`trigger_reap`/`status` — match contract §scheduler.
- `Broadcaster` in `api/sse.py`; routes cover the exact `/api` surface; `create_app` factory in `api/app.py` — match contract §api.
- `__main__.py` exposes `discover`/`run`/`reap`/`serve` — match contract §__main__.
- Enum values used as strings (`e.kind.value`, `ErrorKind.NO_TRAILER.value`, `Status.EXPIRED`) are consistent with the `str, Enum` definitions in `models.py`. `Store.set_status(tmdb_id, status, **fields)` is called with `file_path`, `folder`, `error_kind`, `error_msg`, `popularity`, `last_checked` — all `Movie` column names from contract §data model.
