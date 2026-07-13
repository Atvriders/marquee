# Marquee 🎬

**A self-hosted "coming attractions" board for Jellyfin.** Marquee pulls the top ~50 new & upcoming movies from TMDB, downloads each one's trailer as an MKV, and builds a self-contained **"Coming Soon" Jellyfin _Movies_ library** — every entry is a real, browsable title (poster + metadata) whose "movie" file is the trailer. When a film reaches its **digital/streaming release**, Marquee **automatically deletes** it, so the library always shows what's coming that you can't stream yet.

A full web control center (poster-grid dashboard, live activity, settings) runs on **port 3022**.

> Why it's different from other trailer tools: they only ever _attach_ trailers to media you already own. Marquee is TMDB-first, curates a bounded top-N, and — uniquely — **auto-expires each trailer when the movie starts streaming.**

---

## Quick start (Docker Compose)

1. Get a **TMDB API Read Access Token** (v4) from your [TMDB account settings → API](https://www.themoviedb.org/settings/api).
2. Grab [`docker-compose.yml`](docker-compose.yml), then:

```bash
export TMDB_TOKEN="your_tmdb_v4_read_token"
mkdir -p library config
docker compose up -d
```

   The container runs as UID 1000 (matching Jellyfin's default `PUID=1000`), so the host `./library` and `./config` directories must be writable by UID 1000 or the app can't write its state DB — e.g. `sudo chown -R 1000:1000 library config`.

3. Open **http://localhost:3022**, go to **Settings**, review sources/schedule, and click **Run now**. Trailers land in `./library`.

The image is published at `ghcr.io/atvriders/marquee:latest` (multi-arch amd64/arm64).

---

## Point Jellyfin at the library (required — read this)

Marquee writes a folder-per-movie library with local `movie.nfo` + `poster.jpg`. For Jellyfin to show your coming-soon entries **and not overwrite them with online metadata**, configure the library exactly like this:

1. Mount the **same host path** into Jellyfin that Marquee writes to. In the sample compose, Marquee's `./library` → Jellyfin's `/media/coming-soon` (read-only is fine).
2. In Jellyfin: **Dashboard → Libraries → Add Media Library**, Content type **Movies**, folder = `/media/coming-soon`.
3. In that library's settings:
   - **Metadata downloaders (Movies):** UNCHECK **TheMovieDb** and **The Open Movie Database**.
   - **Metadata readers:** make sure **Nfo** is present and drag it to the **top**.
   - **Metadata savers:** leave **Nfo** UNCHECKED (Marquee writes the NFO; Jellyfin should only read it).
   - **Image fetchers (Movies):** UNCHECK **TheMovieDb** / **OMDb** (local `poster.jpg`/`backdrop.jpg` are auto-detected).
4. **Never** run **"Replace all metadata"** on this library — it discards the local coming-soon data.

Marquee can also trigger a library scan and delete stale items for you — see the Jellyfin env vars below.

---

## Configuration

All settings are environment variables (also editable live in the **Settings** page, which overrides the env value).

| Var | Default | What it controls |
|---|---|---|
| `TMDB_TOKEN` | — (**required**) | TMDB v4 read token |
| `SOURCES` | `upcoming,now_playing` | Any of `upcoming,now_playing,popular,trending_day,trending_week` |
| `COUNT` | `50` | How many trailers to keep |
| `REGION` | `US` | ISO region for release dates / lists |
| `LANGUAGE` | `en-US` | TMDB language |
| `CONTAINER` | `mkv` | `mkv` (keep source, no re-encode) or `mp4` |
| `MAX_HEIGHT` | `1080` | Max trailer resolution |
| `GRACE_DAYS` | `0` | Keep a trailer this many days _after_ its digital release before deleting |
| `TZ` | `UTC` | Timezone for expiry date comparison |
| `REFRESH_CRON` | `0 3 * * *` | When to fetch new trailers |
| `REAPER_CRON` | `0 4 * * *` | When to delete streaming-released titles |
| `LIBRARY_DIR` | `/library` | Where the Coming-Soon library is written (share with Jellyfin) |
| `CONFIG_DIR` | `/config` | State DB, yt-dlp cache, cookies |
| `MAX_SIZE_GB` | `0` (off) | Optional total-size cap (LRU eviction) — reserved |
| `JELLYFIN_URL` | — | Jellyfin base URL (enables scan + clean delete) |
| `JELLYFIN_API_KEY` | — | Jellyfin API key (library scans) |
| `JELLYFIN_USER` / `JELLYFIN_PASS` | — | Admin login — needed for a clean item delete (avoids "ghost" entries) |
| `YTDLP_COOKIES` | — | Path to a `cookies.txt` (helps with bot-blocking) |
| `YTDLP_PROXY` | — | Proxy URL for yt-dlp |
| `PORT` | `3022` | Web UI / API port |

---

## How it works

- **Refresh** (scheduled + "Run now"): fetch the configured TMDB lists → merge, dedupe, rank by popularity, take the top `COUNT` → for each, pick the best official YouTube trailer and read its **digital release date** → download with yt-dlp (stream-copy, no re-encode) → write `Title (Year) [tmdbid-N]/` with the trailer, `movie.nfo`, `poster.jpg` → trigger a Jellyfin scan.
- **Reaper** (scheduled): any title whose **digital release date (+ `GRACE_DAYS`)** has passed is deleted — folder on disk _and_ the Jellyfin item (via the admin API, so no ghost entries).
- **Pin** a title in the UI to keep it from ever auto-deleting.

---

## Troubleshooting

- **"Sign in to confirm you're not a bot" / age-gated / "Video unavailable" downloads fail.** YouTube throttles datacenter IPs and gates some trailers. Fix: export a **Netscape-format `cookies.txt`** from a logged-in (ideally throwaway) browser account and **paste it into `./config/cookies.txt`** — the bundled `docker-compose.yml` is preconfigured to read it (`YTDLP_COOKIES=/config/cookies.txt`); a missing file is safely ignored. Then `docker compose restart marquee`. A proxy (`YTDLP_PROXY`) helps too. The container attempts a best-effort yt-dlp update on start (and via the **Update yt-dlp** button in the UI) — it doesn't block startup and isn't guaranteed to succeed (e.g. offline, PyPI unreachable), so pull/rebuild the image for a guaranteed update. A failed trailer just retries next run.
- **Jellyfin overwrote my coming-soon metadata.** You left an online metadata/image downloader enabled — re-check the library setup above (Nfo reader first, downloaders off, never "Replace all metadata").
- **A deleted movie still shows in Jellyfin ("ghost").** Provide `JELLYFIN_USER`/`JELLYFIN_PASS` so Marquee can delete the item via the admin API; a plain API key can't remove items.
- **No trailer for a title.** Some upcoming films have no YouTube trailer yet; Marquee logs it and skips, retrying on later runs.

---

## Development

Backend (Python 3.13):
```bash
cd backend && python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
python -m pytest -q            # test suite
python -m marquee discover     # dry-run: print the ranked top-N (needs TMDB_TOKEN)
```

Frontend (Node 22):
```bash
cd frontend && npm install
npm run dev                    # dev server, proxies /api -> :3022
npm test                       # vitest
npm run build                  # outputs into backend/marquee/api/static
```

The backend serves the built SPA, so `python -m marquee serve` (or the container) exposes both the UI and API on port 3022.

## License

MIT.
