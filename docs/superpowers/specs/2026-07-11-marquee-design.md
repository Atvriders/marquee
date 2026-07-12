# Marquee — Design Spec

**Date:** 2026-07-11
**Status:** Approved (design), pending implementation plan
**Repo:** `Atvriders/marquee` · **Image:** `ghcr.io/atvriders/marquee`

---

## 1. Summary

Marquee is a self-hosted Docker app that keeps a **"Coming Soon" Jellyfin _Movies_ library** freshly stocked with the trailers of the **top ~50 new/upcoming movies** from TMDB. Each movie gets its own library folder where the **downloaded trailer (MKV) is the movie file**, accompanied by a `movie.nfo` and poster/backdrop so Jellyfin shows it as a real, browsable title. When TMDB reports a movie has reached its **digital (streaming) release**, Marquee **auto-deletes** that entry — folder on disk _and_ the Jellyfin item — so the library always reflects "great stuff coming that you can't stream yet."

A full web control center (React SPA) manages everything: a poster-grid dashboard with per-title status and streaming-countdown, per-item actions (download / delete / pin), a live activity log, scheduler status, and a settings page.

### Why this is novel

The self-hosted trailer space is crowded but splits into "attach a trailer to media you already own" (Trailarr, JellyTrailers) and "stream trailers as an enhancement" (Trailerfin, HoverTrailer). The one real overlap, **Trailers4Jellyfin**, pulls TMDB Upcoming but as an in-server plugin producing Cinema-Mode _pre-roll fodder_, not a browsable library, and with **no lifecycle**. **No existing tool auto-expires trailers when the film reaches streaming.** Marquee's differentiators:

1. **Auto-expiring lifecycle** keyed on TMDB digital release date (novel).
2. **Standalone, TMDB-first** — needs no Radarr/Sonarr/owned media.
3. A **first-class browsable "Coming Soon" _Movies_ library** with real per-title metadata.
4. **Bounded + churning** (top-N) so storage stays capped and the list stays fresh.

---

## 2. Locked decisions

| Area | Decision |
|---|---|
| **Name** | Marquee (`Atvriders/marquee`, `ghcr.io/atvriders/marquee`) |
| **Trailer source** | Configurable mix of TMDB lists. Default: `upcoming` + `now_playing`. Optional: `popular`, `trending`. Merge, dedupe by TMDB id, rank by popularity, take top N (default 50). |
| **Delete trigger** | TMDB **digital release date (release type 4)** has passed, with a region fallback chain and a configurable grace period + timezone. |
| **Format** | **MKV**, keep-source video/audio, ≤1080p, stream-copy (no re-encode). Container configurable (mp4 supported with H.264/AAC caveat). |
| **Download failure mode** | **MKV only; on failure, log & skip, retry next run.** Reliability mitigations built in (yt-dlp auto-update, multi player_client). Cookies/proxy exposed as optional advanced settings. No `.strm` fallback. |
| **UI** | Full control center — React/Vite SPA, cinema aesthetic (via frontend-design skill). |
| **Stack** | FastAPI (Python 3.13) backend using yt-dlp as a native library + React/Vite SPA, single container. |
| **Jellyfin integration** | **Full**: server URL + API key (library scans) + admin username/password (clean `DELETE /Items` to avoid ghost items). |
| **Deploy** | Single container, multi-arch (amd64+arm64) GitHub Actions → GHCR (public package). `docker-compose.yml` shares the `/library` path with Jellyfin. |

---

## 3. Architecture

Single container, background scheduler inside the FastAPI process (APScheduler), SQLite for state.

```
┌──────────────────────────────────────────────────────────────┐
│  Container: marquee                                            │
│                                                                │
│  FastAPI (Python 3.13)               React/Vite SPA (built)    │
│   ├─ /api/*  REST + SSE   ◄───────────  served via StaticFiles │
│   ├─ APScheduler (cron)                                        │
│   │    ├─ Refresh job → discover → enrich → download → write   │
│   │    └─ Reaper  job → find expired → delete folder + JF item │
│   ├─ SQLite state         (/config/state.db)                   │
│   └─ yt-dlp + ffmpeg      (bundled in image)                   │
│                                                                │
│  Volumes:  /library (shared w/ Jellyfin, rw)   /config (rw)    │
└──────────────────────────────────────────────────────────────┘
        │ writes MKV + NFO + poster        │ optional REST (scan, delete)
        ▼                                   ▼
  Jellyfin "Coming Soon" Movies library   Jellyfin server
```

### Components (each independently testable)

| Component | Responsibility | Depends on |
|---|---|---|
| `tmdb.client` | Auth'd TMDB HTTP: list endpoints, `append_to_response` detail fetch, `/configuration` image cache. Rate-limit + 429 backoff. | httpx |
| `tmdb.curator` | Merge configured lists → dedupe by id → rank by popularity → top N. Best-trailer selection. Digital-date extraction w/ fallback chain. | tmdb.client |
| `downloader` | yt-dlp wrapper: pre-validate, download to temp, capture real output path, progress hooks. Error classification (bot/age/region/unavailable). | yt-dlp, ffmpeg |
| `library.writer` | Build `Title (Year) [tmdbid-N]/` folder, move MKV in, render `movie.nfo`, fetch+write `poster.jpg`/`backdrop.jpg`. | tmdb.client |
| `library.reaper` | Find entries whose digital date passed (+grace) or that fell out of top-N (unless pinned); delete folder + call Jellyfin delete. | jellyfin.client |
| `jellyfin.client` | `GET /Library/VirtualFolders`, `POST /Library/Refresh`, `POST /Users/AuthenticateByName`, `DELETE /Items/{id}`. Cred test. | httpx |
| `scheduler` | APScheduler jobs (refresh, reaper); on-demand triggers; single-flight lock so runs don't overlap. | all above |
| `store` | SQLite access layer (movies, activity_log, settings). | sqlite3/SQLModel |
| `api` | FastAPI routers, SSE activity stream, SPA static serving. | store, scheduler |
| `web` | React/Vite SPA. | api |

---

## 4. Refresh pipeline (scheduled + on-demand)

1. **Discover.** For each enabled source (`upcoming`, `now_playing`, optionally `popular`, `trending/{day|week}`), fetch pages 1–3 (`region`, `language` applied). Merge results, dedupe by `id`, rank by `popularity` desc, truncate to `count` (50).
2. **Enrich.** For each selected movie, one call:
   `GET /movie/{id}?append_to_response=videos,release_dates,images&language={lang}&include_video_language={lang2},null&include_image_language={lang2},null`
   Extract: best trailer, digital release date, poster/backdrop paths, overview, runtime, genres, studios, certification, year, premiere date.
3. **Best-trailer selection** (from `videos.results`): filter `site == "YouTube"`; prefer `type == "Trailer"` then `"Teaser"`; prefer `official == true`; prefer matching `iso_639_1`; then sort by `size` desc, `published_at` desc. YouTube URL = `https://www.youtube.com/watch?v=<key>`. No YouTube video → try title+year YouTube search fallback → else skip (poster-only entry optional, default skip), log it.
4. **Dedupe / idempotency.** Skip movies already `ready` on disk with the same YouTube key (SQLite state + yt-dlp `download_archive`). Runs are idempotent.
5. **Download.** yt-dlp (see §7). On success, `status=ready`, record `file_path`, `duration`. On failure, classify + log, `status=failed`, retry next run.
6. **Write library.** Create folder + MKV + `movie.nfo` + `poster.jpg` (+ `backdrop.jpg`). See §5.
7. **Notify Jellyfin.** If configured, `POST /Library/Refresh` (or the Coming-Soon library's item refresh) so new titles appear.
8. **Evict overflow.** Titles that dropped out of the top-N and are not `pinned` and not yet expired are candidates for the reaper (or immediate eviction, configurable; default: keep until digital-release expiry to avoid churn-thrash, but enforce a hard max-size cap with LRU eviction if set).

---

## 5. Jellyfin "Coming Soon" library contract (verified)

### Folder / file layout
```
/library/
└── Dune Part Three (2026) [tmdbid-1234567]/
    ├── Dune Part Three (2026) [tmdbid-1234567].mkv   ← trailer, filename begins EXACTLY with folder name
    ├── movie.nfo
    ├── poster.jpg
    └── backdrop.jpg
```
Rules: one movie per folder; the video filename must begin character-for-character with the folder name; include `(year)` and `[tmdbid-N]` for deterministic matching; avoid `< > : " / \ | ? *` in names (sanitize titles).

### `movie.nfo` (Jellyfin's `MediaBrowser.XbmcMetadata` reader)
Consumed fields we set: `title`, `originaltitle`, `sorttitle`, `tagline`, `plot` (→ Overview; last plot wins), `runtime` (minutes), `year`, `premiered`, `releasedate`, `mpaa`, `genre`×, `studio`×, `country`, `tag` (e.g. `Coming Soon`, `Trailer`), `uniqueid type="tmdb" default="true"` (+ legacy `tmdbid`/`imdbid`). We keep `rating` at 0/omitted for unreleased. `<lockdata>` is **not** relied upon (buggy on 10.11.x). Example produced:

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<movie>
  <title>Dune: Part Three</title>
  <originaltitle>Dune: Part Three</originaltitle>
  <plot>COMING SOON — Official trailer. … In theaters 2026-12-18.</plot>
  <runtime>3</runtime>
  <year>2026</year>
  <premiered>2026-12-18</premiered>
  <releasedate>2026-12-18</releasedate>
  <mpaa>PG-13</mpaa>
  <genre>Science Fiction</genre>
  <genre>Adventure</genre>
  <studio>Legendary Pictures</studio>
  <tag>Coming Soon</tag>
  <uniqueid type="tmdb" default="true">1234567</uniqueid>
  <tmdbid>1234567</tmdbid>
  <thumb aspect="poster">poster.jpg</thumb>
  <fanart><thumb>backdrop.jpg</thumb></fanart>
</movie>
```

### Images
`poster.jpg` (portrait ~2:3, TMDB `poster_path` at `w500`) and optional `backdrop.jpg` (16:9, `backdrop_path` at `w1280`). Standalone names (`poster.jpg`/`backdrop.jpg`) — pick one alias each. Images built as `https://image.tmdb.org/t/p/{size}{path}` using `/configuration` (cached).

### Required Jellyfin library configuration (documented for the user, in README)
Content type **Movies**; **Nfo** metadata reader dragged to the **top**; **uncheck** TheMovieDb + OMDb **metadata downloaders** _and_ **image fetchers** for this library; leave **Nfo saver off**; never run "Replace all metadata". This makes our local NFO/poster authoritative and stops Jellyfin "correcting" coming-soon entries.

---

## 6. Expiry lifecycle (the novel part)

### Digital date extraction (`GET /movie/{id}/release_dates`, type codes: 1 Premiere, 2 Theatrical-ltd, 3 Theatrical, **4 Digital**, 5 Physical, 6 TV)
1. In the configured `region`, take the earliest `type == 4` `release_date`.
2. Fallback chain if absent: US type 4 → earliest type 4 across all countries → Physical (5) → TV (6).
3. If none of 4/5/6 exist, movie has no known streaming date → **keep** (don't expire).

### Reaper job
Runs on its own schedule (default daily). For each `ready` entry:
- Compute `expires_at = digital_date + grace_days`, evaluated at end-of-day in the configured `timezone`. Store dates UTC; compare in tz.
- If `now >= expires_at` and not `pinned` → **expire**: delete the movie folder, then (if Jellyfin configured) authenticate as admin and `DELETE /Items/{jellyfin_item_id}`, then trigger a scan. Mark `status=expired`.

### Ghost-item mitigation (verified bug)
Deleting a folder does **not** make Jellyfin purge the item via rescan — it lingers as an unplayable ghost. Marquee therefore uses `DELETE /Items/{id}` (which needs a real **admin user** token from `POST /Users/AuthenticateByName`, not a bare API key) as the authoritative removal, and deletes the folder while the parent library path is still mounted/reachable. To resolve `jellyfin_item_id`, Marquee looks the item up by its `tmdb` provider id (or path) after the add-scan and stores it. If Jellyfin isn't configured, files are deleted and the README documents manual ghost cleanup.

---

## 7. Downloader (yt-dlp, verified)

- **Format:** `bv*[height<=1080]+ba/b[height<=1080]/b`, `merge_output_format="mkv"`. The `+` merge is an ffmpeg **stream-copy remux (no transcode)**; MKV always succeeds losslessly for YouTube VP9/AV1+Opus. (mp4 container: force `[vcodec^=avc1]+[acodec^=mp4a]` or post-remux, else yt-dlp falls back to mkv — documented in settings help.)
- **Output path:** read `info["requested_downloads"][0]["filepath"]` (not `prepare_filename`, whose extension is pre-merge). Download to `/config/tmp`, final move into the library folder.
- **Reliability:** entrypoint runs `yt-dlp -U` on start; `extractor_args={"youtube":{"player_client":["default","tv","web_safari"]}}`; `retries`/`fragment_retries`; polite `sleep_interval`. Optional `cookiefile` (`/config/cookies.txt`) and `proxy` from settings.
- **Pre-validate** with `extract_info(download=False)` to reject livestreams / missing ≤1080p stream / `needs_auth` before spending a download.
- **Error classification** (catch `DownloadError`/`GeoRestrictedError`, match message): `bot_check`, `age_gated`, `region_blocked`, `unavailable`, `no_format`, `error`. All → log + skip + retry next run.
- **Progress:** `progress_hooks` (download %) + `postprocessor_hooks` (merge done = file exists) feed the SSE activity/status stream. Hooks push to a queue (non-blocking).
- **ffmpeg** installed in the image; found on PATH.

---

## 8. TMDB client (verified)

- **Base:** `https://api.themoviedb.org/3`. **Auth:** v4 **API Read Access Token** as `Authorization: Bearer <token>` (preferred; keeps creds out of URLs). v3 `api_key` query also accepted.
- **Lists:** `/movie/upcoming`, `/movie/now_playing`, `/movie/popular`, `/trending/movie/{day|week}` — 20/page, envelope `{page,results,total_pages,total_results}`, params `language`, `page`, `region`.
- **Detail batch:** `/movie/{id}?append_to_response=videos,release_dates,images` (≤20 append items; each nested under its key, e.g. `"release_dates"`, `"videos"`).
- **Images:** `/configuration` → `images.secure_base_url` + size lists (cached). Poster `w500`, backdrop `w1280`.
- **Rate limits:** ~40–50 req/s soft, no hard daily cap; on HTTP 429 respect `Retry-After`. Cap our concurrency ≤5, cache responses, re-check digital dates on schedule (not per view).
- **Attribution:** if we ever surface watch/providers data, attribute JustWatch (not used in core flow; digital date is primary trigger).

---

## 9. Data model (SQLite, `/config/state.db`)

**movies** — `tmdb_id` PK, `title`, `year`, `overview`, `runtime`, `genres` (json), `studios` (json), `certification`, `premiere_date`, `digital_date`, `digital_date_source` (region/us/global/physical/tv/none), `region`, `popularity`, `poster_path`, `backdrop_path`, `youtube_key`, `status` (`queued`|`downloading`|`ready`|`failed`|`expired`), `file_path`, `folder`, `jellyfin_item_id`, `pinned` (bool), `added_at`, `expires_at`, `last_checked`, `error_kind`, `error_msg`.

**activity_log** — `id`, `ts`, `level`, `event`, `tmdb_id`, `message`.

**settings** — `key`, `value` (JSON). Effective config = env defaults overlaid by settings rows edited in the UI.

**Pinning:** a `pinned` title is never auto-expired and never evicted for overflow.

---

## 10. Configuration (env defaults + UI overrides)

| Key | Default | Notes |
|---|---|---|
| `TMDB_TOKEN` | — (required) | v4 read token |
| `SOURCES` | `upcoming,now_playing` | subset of `upcoming,now_playing,popular,trending_day,trending_week` |
| `COUNT` | `50` | top-N (10–200) |
| `REGION` | `US` | ISO 3166-1 |
| `LANGUAGE` | `en-US` | TMDB language |
| `CONTAINER` | `mkv` | `mkv`\|`mp4` |
| `MAX_HEIGHT` | `1080` | resolution cap |
| `REFRESH_CRON` | `0 3 * * *` | daily 03:00 |
| `REAPER_CRON` | `0 4 * * *` | daily 04:00 |
| `GRACE_DAYS` | `0` | days after digital release before delete |
| `TZ` | `UTC` | timezone for date comparison |
| `LIBRARY_DIR` | `/library` | shared with Jellyfin |
| `CONFIG_DIR` | `/config` | state db, tmp, cookies |
| `MAX_SIZE_GB` | `0` (off) | optional total-size cap w/ LRU eviction |
| `JELLYFIN_URL` | — | optional |
| `JELLYFIN_API_KEY` | — | scans |
| `JELLYFIN_USER` / `JELLYFIN_PASS` | — | admin login for clean delete |
| `YTDLP_COOKIES` | — | optional `/config/cookies.txt` |
| `YTDLP_PROXY` | — | optional |

---

## 11. API surface (FastAPI, `/api` prefix; SPA served at `/`)

`GET /api/movies` (list + status) · `GET /api/movies/{id}` · `POST /api/movies/{id}/download` · `DELETE /api/movies/{id}` (delete now) · `POST /api/movies/{id}/pin` (toggle) · `GET /api/settings` · `PUT /api/settings` · `POST /api/run` (refresh now) · `POST /api/reap` (expire now) · `GET /api/activity` (SSE live log + progress) · `GET /api/status` (scheduler next-run, counts) · `GET /api/health` · `POST /api/ytdlp/update` · `POST /api/jellyfin/test`.

---

## 12. Frontend (React/Vite, cinema aesthetic via frontend-design)

- **Dashboard:** poster-grid of current titles. Each card: poster, title, release date, **streaming-countdown badge** ("streams in 42d"), status pill (`queued` / `downloading NN%` / `ready` / `expiring 3d` / `failed`), pin toggle, per-card menu (download, delete). Filter/sort (status, source, soonest-to-stream).
- **Activity:** live-updating log (SSE) with progress bars for active downloads.
- **Status bar:** next refresh/reaper run, counts (ready / queued / failed), disk usage, yt-dlp version + "update" button.
- **Settings:** all of §10, grouped (Sources, Format, Schedule, Jellyfin, Advanced/cookies-proxy), with a "Test Jellyfin" button and a "Run now" button.
- Design applied via the **frontend-design** skill at build time — distinctive, not templated.

---

## 13. Deployment

- **Image:** two-stage — `node:22-alpine` builds the SPA → `python:3.13-slim` runtime installs `ffmpeg` (apt) + `yt-dlp[default]` + deps (pip), copies backend + built `dist/` into `static/`. Non-root `appuser` (UID 1000 to match Jellyfin `PUID`). Serves SPA via `StaticFiles(html=True)` with an SPA catch-all; API under `/api`. `HEALTHCHECK` → `GET /api/health`. Entrypoint self-updates yt-dlp then launches uvicorn.
- **Volumes:** `/library` (bind-mounted into both Marquee rw and Jellyfin ro), `/config` (named volume: state db, tmp, cookies).
- **CI:** GitHub Actions on push/tag → `setup-qemu` + `buildx` → `metadata-action` → `build-push-action` multi-arch `linux/amd64,linux/arm64` to `ghcr.io/atvriders/marquee`, GHA layer cache; package set **public**. (If QEMU arm64 build is too slow, split into native amd64 + `ubuntu-24.04-arm` jobs and merge manifests.)
- **compose:** ships a `docker-compose.yml` with Marquee + a commented Jellyfin service sharing the library bind mount, and a README with the exact Jellyfin library setup steps (§5).

---

## 14. Testing (TDD)

- **tmdb.client** — mocked HTTP fixtures: list parsing, append_to_response shape, 429 backoff, image URL building.
- **tmdb.curator** — merge/dedupe/rank/top-N; best-trailer selection ordering; digital-date extraction + full fallback chain; timezone/grace in expiry math.
- **library.writer** — golden-file `movie.nfo`; folder/file naming rules incl. sanitization of illegal chars; poster/backdrop write.
- **downloader** — yt-dlp wrapped and mocked: output-path extraction from `requested_downloads`, error classification, pre-validate. (No real network in unit tests.)
- **jellyfin.client** — mocked: VirtualFolders, Refresh, AuthenticateByName, DELETE flow, cred test.
- **reaper** — end-to-end with fake clock: expiry selection, pin protection, overflow eviction, ghost-delete call ordering.
- **api** — route contracts, settings round-trip, SSE emits.
- **e2e dry-run** — real TMDB (read-only) discovery+enrich with downloads stubbed, asserting a valid library tree + NFOs would be produced.

---

## 15. Risks & mitigations (from research)

| Risk | Mitigation |
|---|---|
| YouTube bot-blocking of datacenter IPs | yt-dlp auto-update; multi `player_client`; polite rate-limit; optional cookies/proxy; failures skip & retry (no crash). |
| Stale yt-dlp breaks extraction | `yt-dlp -U` on container start; optional in-app update button. |
| Jellyfin ghost items after folder delete | Authoritative `DELETE /Items/{id}` via admin token; delete folder while path reachable. |
| Jellyfin ignores local NFO | README setup: Nfo reader first + downloaders/fetchers off; deterministic `[tmdbid-N]` + valid NFO. |
| Jellyfin doesn't auto-pick-up folders | Trigger `POST /Library/Refresh` after each run rather than relying on file-watching. |
| TMDB rate limits | Concurrency ≤5, 429 `Retry-After` backoff, cache `/configuration`, batch with append_to_response. |
| Storage growth | Bounded top-N, expiry deletion, optional `MAX_SIZE_GB` LRU cap, resolution cap. |
| Duplicate downloads across runs | SQLite state keyed by tmdb_id + youtube_key; yt-dlp `download_archive`; idempotent runs. |
| Timezone ambiguity in release dates | Configurable `region` + `TZ`; store UTC, compare end-of-day in tz; configurable grace. |
| No trailer for a movie | Title+year YouTube search fallback → else skip + log (never abort batch). |

---

## 16. Out of scope (YAGNI)

- Radarr/Sonarr integration (we're TMDB-first by design).
- TV-show trailers (movies only).
- Multi-user auth on the Marquee UI beyond an optional single app password (matching `jellyfin-manager`).
- `.strm` streaming mode (explicitly declined).
- Weighted source blending (simple popularity ranking is enough).
- Trailer transcoding / editing.

---

## 17. Open questions for implementation plan

None blocking. Plan will sequence: (1) project scaffold + CI, (2) store + config, (3) tmdb client+curator, (4) downloader, (5) library writer, (6) jellyfin client + reaper, (7) scheduler + API, (8) React SPA, (9) Docker + compose + docs, (10) end-to-end verification. Independent tasks (per-component) will be built by parallel agents.
