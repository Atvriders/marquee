// Mirrors the FastAPI JSON contract (backend/marquee/models.py Movie + api routers).
// datetimes are serialized as ISO 8601 strings; *_url/download_pct are API-added
// convenience fields (backend resolves TMDB image base + live progress).

export type Status = "queued" | "downloading" | "ready" | "failed" | "expired";

export interface Movie {
  tmdb_id: number;
  title: string;
  year: number | null;
  overview: string;
  runtime: number | null;
  genres: string[];
  studios: string[];
  certification: string | null;
  premiere_date: string | null;
  digital_date: string | null; // ISO datetime, tz-aware UTC
  digital_date_source: string;
  region: string;
  popularity: number;
  poster_path: string | null;
  backdrop_path: string | null;
  youtube_key: string | null;
  status: Status;
  file_path: string | null;
  folder: string | null;
  jellyfin_item_id: string | null;
  pinned: boolean;
  added_at: string;
  expires_at: string | null;
  last_checked: string | null;
  error_kind: string | null;
  error_msg: string | null;
  // API-added convenience fields:
  poster_url: string | null; // resolved TMDB w500 URL, or null
  backdrop_url: string | null; // resolved TMDB w1280 URL, or null
  download_pct: number | null; // live progress when status === "downloading"
}

export interface Config {
  tmdb_token: string;
  sources: string[];
  count: number;
  region: string;
  language: string;
  container: string;
  max_height: number;
  refresh_cron: string;
  reaper_cron: string;
  grace_days: number;
  tz: string;
  library_dir: string;
  config_dir: string;
  max_size_gb: number;
  jellyfin_url: string | null;
  jellyfin_api_key: string | null;
  jellyfin_user: string | null;
  jellyfin_pass: string | null;
  ytdlp_cookies: string | null;
  ytdlp_proxy: string | null;
}

export interface ActivityEntry {
  id?: number; // present on DB backlog rows; absent on live-streamed log events
  ts: string; // ISO datetime
  level: string; // "info" | "warn" | "error"
  event: string;
  tmdb_id: number | null;
  message: string;
}

export interface StatusSummary {
  next_refresh: string | null;
  next_reap: string | null;
  running: boolean;
  counts: {
    ready: number;
    queued: number;
    downloading: number;
    failed: number;
    expired: number;
  };
  disk: {
    used_gb: number;
    free_gb: number;
    total_gb: number;
  };
  ytdlp_version: string;
}

// Live health of the external services Marquee talks to.
export interface Connections {
  tmdb: string; // "ok" | "unauthorized" | "error"
  jellyfin: string; // "ok" | "error" | "not_configured"
}

// SSE payloads on GET /api/activity are one of:
export type ActivityMessage =
  | { type: "log"; entry: ActivityEntry }
  | {
      type: "progress";
      tmdb_id: number;
      pct: number;
      speed: number | null; // bytes/sec (yt-dlp), per SSE contract
      eta: number | null; // seconds remaining, per SSE contract
    };
