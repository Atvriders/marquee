# Marquee Frontend & Ship Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the polished React/Vite "coming attractions" control-center SPA, wire it to the FastAPI `/api` from Plans 1–2, and ship the whole thing as a multi-arch GHCR Docker image with compose, CI, and docs.

**Architecture:** A same-origin React SPA (Vite + TypeScript + react-router) talks to the FastAPI backend under `/api`; the built static bundle is copied into the Python package's `static/` dir and served by FastAPI via `StaticFiles(html=True)` plus an SPA catch-all so deep links resolve to `index.html`. A two-stage Dockerfile (`node:22-alpine` builds the SPA → `python:3.13-slim` runtime) produces a single non-root image published multi-arch (amd64+arm64) to `ghcr.io/atvriders/marquee` by GitHub Actions.

**Tech Stack:** React 18, Vite 6, TypeScript 5.6, react-router-dom 6, Vitest + React Testing Library (jsdom); FastAPI static serving; Docker Buildx/QEMU; GitHub Actions → GHCR.

## Global Constraints

- **Container:** non-root `appuser` UID 1000; volumes `/library` (rw, shared with Jellyfin) and `/config` (rw). GHCR package **public**. Multi-arch amd64+arm64.
- **SPA served from `static/` via `StaticFiles(html=True)` + catch-all → `index.html`; `/api` never shadowed.** API base is same-origin `/api`.
- **Images:** poster `w500`, backdrop `w1280`, via `secure_base_url` from `/configuration` (backend resolves; frontend consumes resolved URLs or falls back to `https://image.tmdb.org/t/p/w500{path}`).
- **yt-dlp** installed as `yt-dlp[default]` (latest; nightly acceptable). **ffmpeg** required at runtime, found on PATH.
- **Frontend tests:** Vitest + RTL; mock `fetch`/api client; test rendering + interactions, not visuals.
- **Commits:** conventional (`feat:`, `test:`, `chore:`), one per completed task.
- **Design applied via the frontend-design skill** — distinctive, not templated (Task 8).

---

## File Structure

| File | Responsibility |
|---|---|
| `frontend/package.json` | Deps + scripts (dev/build/test/typecheck). |
| `frontend/vite.config.ts` | Vite build (`outDir` → backend static dir), dev `/api` proxy, Vitest config. |
| `frontend/tsconfig.json` | TypeScript compiler options for the SPA. |
| `frontend/index.html` | HTML entry, mounts `#root`. |
| `frontend/src/setupTests.ts` | Vitest global setup (jest-dom matchers). |
| `frontend/src/main.tsx` | React entry; `BrowserRouter` + `<App/>`. |
| `frontend/src/App.tsx` | Shell: header/nav + routed pages + `StatusBar`. |
| `frontend/src/styles.css` | Global theme/layout (restyled in Task 8). |
| `frontend/src/types.ts` | TypeScript mirror of the API JSON shapes. |
| `frontend/src/api.ts` | Typed same-origin `/api` fetch client. |
| `frontend/src/components/StatusPill.tsx` | Per-`Status` pill (incl. `downloading NN%`). |
| `frontend/src/components/CountdownBadge.tsx` | Streaming countdown from `digital_date`. |
| `frontend/src/components/MovieCard.tsx` | Poster card: badges, pin toggle, action menu. |
| `frontend/src/components/StatusBar.tsx` | Next-run times, counts, disk, yt-dlp version+update. |
| `frontend/src/components/ActivityLog.tsx` | SSE live log + download progress bars. |
| `frontend/src/components/SettingsForm.tsx` | Grouped Config form + Test-Jellyfin/Run-now. |
| `frontend/src/pages/DashboardPage.tsx` | Poster grid + filter/sort over `api.getMovies`. |
| `frontend/src/pages/ActivityPage.tsx` | Wraps `ActivityLog`. |
| `frontend/src/pages/SettingsPage.tsx` | Wraps `SettingsForm`. |
| `backend/marquee/api/static/` | Vite `build.outDir` target; Plan 2's `create_app` auto-serves it (no `app.py` change here). |
| `backend/tests/test_spa_static.py` | Verifies `/` + deep-link fallback + `/api` not shadowed. |
| `Dockerfile` | Two-stage build → non-root runtime image. |
| `entrypoint.sh` | `yt-dlp -U` best-effort, then `python -m marquee serve`. |
| `.dockerignore` | Keep build context lean. |
| `docker-compose.yml` | Marquee service + commented Jellyfin service. |
| `.github/workflows/docker.yml` | Multi-arch buildx → GHCR push. |
| `README.md` | What/why, quick start, Jellyfin setup, config table, troubleshooting. |

---

### Task 1: Frontend scaffold + smoke test

Stand up the Vite/React/TypeScript project with Vitest wired, a minimal routed shell, and one passing RTL smoke test.

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/index.html`
- Create: `frontend/src/setupTests.ts`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/styles.css`
- Test: `frontend/src/App.test.tsx`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `App` (named export, `() => JSX.Element`) rendered under a router; Vite `build.outDir` = `../backend/marquee/api/static`; npm scripts `dev`, `build`, `test`, `typecheck`.

- [ ] **Step 1: Write `frontend/package.json`**

```json
{
  "name": "marquee-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "typecheck": "tsc --noEmit",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.28.0"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.6.3",
    "@testing-library/react": "^16.1.0",
    "@testing-library/user-event": "^14.5.2",
    "@types/react": "^18.3.12",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^4.3.4",
    "jsdom": "^25.0.1",
    "typescript": "^5.6.3",
    "vite": "^6.0.3",
    "vitest": "^2.1.8"
  }
}
```

- [ ] **Step 2: Write `frontend/vite.config.ts`**

```ts
/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

export default defineConfig({
  plugins: [react()],
  build: {
    // Local/dev build lands directly in the Python package's static dir so
    // FastAPI serves it. The Docker build overrides this with --outDir dist.
    outDir: fileURLToPath(new URL("../backend/marquee/api/static", import.meta.url)),
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": "http://localhost:3022",
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: "./src/setupTests.ts",
    css: false,
  },
});
```

- [ ] **Step 3: Write `frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "skipLibCheck": true,
    "noUnusedLocals": false,
    "noUnusedParameters": false,
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src", "vite.config.ts"]
}
```

- [ ] **Step 4: Write `frontend/index.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Marquee</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 5: Write `frontend/src/setupTests.ts`, `frontend/src/styles.css`, `frontend/src/main.tsx`**

`frontend/src/setupTests.ts`:

```ts
import "@testing-library/jest-dom";
```

`frontend/src/styles.css` (base only; Task 8 restyles):

```css
:root {
  color-scheme: dark light;
}
* {
  box-sizing: border-box;
}
body {
  margin: 0;
  font-family: system-ui, sans-serif;
}
```

`frontend/src/main.tsx`:

```tsx
import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import "./styles.css";

const el = document.getElementById("root");
if (!el) throw new Error("#root not found");
createRoot(el).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
```

- [ ] **Step 6: Write the failing smoke test `frontend/src/App.test.tsx`**

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { App } from "./App";

test("renders the Marquee brand", () => {
  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );
  expect(screen.getByText("MARQUEE")).toBeInTheDocument();
});
```

- [ ] **Step 7: Install deps and run the test to verify it fails**

Run: `cd frontend && npm install && npx vitest run src/App.test.tsx`
Expected: FAIL — cannot resolve `./App` (module `frontend/src/App.tsx` does not exist yet).

- [ ] **Step 8: Write minimal `frontend/src/App.tsx`**

```tsx
import { NavLink } from "react-router-dom";

export function App() {
  return (
    <div className="app">
      <header className="app-header">
        <span className="brand">MARQUEE</span>
        <nav className="app-nav">
          <NavLink to="/">Dashboard</NavLink>
          <NavLink to="/activity">Activity</NavLink>
          <NavLink to="/settings">Settings</NavLink>
        </nav>
      </header>
      <main className="app-main" />
    </div>
  );
}
```

- [ ] **Step 9: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/App.test.tsx`
Expected: PASS (1 passed).

- [ ] **Step 10: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vite.config.ts \
  frontend/tsconfig.json frontend/index.html frontend/src/setupTests.ts \
  frontend/src/styles.css frontend/src/main.tsx frontend/src/App.tsx frontend/src/App.test.tsx
git commit -m "feat: scaffold Vite/React/TypeScript SPA with Vitest smoke test"
```

---

### Task 2: API types + typed fetch client

Mirror the backend JSON in `types.ts` and build the same-origin `/api` client with a mocked-fetch test.

**Files:**
- Create: `frontend/src/types.ts`
- Create: `frontend/src/api.ts`
- Test: `frontend/src/api.test.ts`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `types.ts`: `Status` (`"queued"|"downloading"|"ready"|"failed"|"expired"`), interfaces `Movie`, `Config`, `ActivityEntry`, `StatusSummary`, and union `ActivityMessage`.
  - `api.ts`: `api` object with `getMovies(): Promise<Movie[]>`, `getMovie(id:number): Promise<Movie>`, `downloadMovie(id:number): Promise<void>`, `deleteMovie(id:number): Promise<void>`, `pinMovie(id:number): Promise<Movie>`, `getSettings(): Promise<Config>`, `updateSettings(cfg:Config): Promise<Config>`, `runNow(): Promise<void>`, `reapNow(): Promise<void>`, `getStatus(): Promise<StatusSummary>`, `getHealth(): Promise<{status:string}>`, `updateYtdlp(): Promise<{version:string}>`, `testJellyfin(): Promise<{ok:boolean}>`, `activityUrl(): string`.

- [ ] **Step 1: Write `frontend/src/types.ts`**

```ts
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
  id: number;
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
```

- [ ] **Step 2: Write the failing test `frontend/src/api.test.ts`**

```ts
import { afterEach, expect, test, vi } from "vitest";
import { api } from "./api";
import type { Movie } from "./types";

afterEach(() => {
  vi.restoreAllMocks();
});

function mockFetch(body: unknown, init: Partial<Response> = {}) {
  const res = {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    statusText: init.statusText ?? "OK",
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
  return vi.spyOn(globalThis, "fetch").mockResolvedValue(res);
}

test("getMovies GETs /api/movies and returns parsed JSON", async () => {
  const movies = [{ tmdb_id: 1, title: "X" }] as unknown as Movie[];
  const spy = mockFetch(movies);
  const out = await api.getMovies();
  expect(spy).toHaveBeenCalledWith("/api/movies", expect.objectContaining({}));
  expect(out).toEqual(movies);
});

test("pinMovie POSTs to /api/movies/:id/pin", async () => {
  const spy = mockFetch({ tmdb_id: 7 });
  await api.pinMovie(7);
  expect(spy).toHaveBeenCalledWith(
    "/api/movies/7/pin",
    expect.objectContaining({ method: "POST" }),
  );
});

test("updateSettings PUTs JSON body to /api/settings", async () => {
  const spy = mockFetch({ region: "GB" });
  await api.updateSettings({ region: "GB" } as never);
  const [url, init] = spy.mock.calls[0];
  expect(url).toBe("/api/settings");
  expect((init as RequestInit).method).toBe("PUT");
  expect((init as RequestInit).body).toBe(JSON.stringify({ region: "GB" }));
});

test("throws on non-ok response", async () => {
  mockFetch({ detail: "nope" }, { ok: false, status: 500, statusText: "Server Error" });
  await expect(api.getStatus()).rejects.toThrow(/500/);
});

test("activityUrl returns the SSE endpoint", () => {
  expect(api.activityUrl()).toBe("/api/activity");
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/api.test.ts`
Expected: FAIL — cannot resolve `./api`.

- [ ] **Step 4: Write `frontend/src/api.ts`**

```ts
import type { Config, Movie, StatusSummary } from "./types";

const BASE = "/api";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get("content-type") ?? "";
  if (!ct.includes("application/json")) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  getMovies: () => req<Movie[]>("/movies"),
  getMovie: (id: number) => req<Movie>(`/movies/${id}`),
  downloadMovie: (id: number) =>
    req<void>(`/movies/${id}/download`, { method: "POST" }),
  deleteMovie: (id: number) => req<void>(`/movies/${id}`, { method: "DELETE" }),
  pinMovie: (id: number) => req<Movie>(`/movies/${id}/pin`, { method: "POST" }),
  getSettings: () => req<Config>("/settings"),
  updateSettings: (cfg: Config) =>
    req<Config>("/settings", { method: "PUT", body: JSON.stringify(cfg) }),
  runNow: () => req<void>("/run", { method: "POST" }),
  reapNow: () => req<void>("/reap", { method: "POST" }),
  getStatus: () => req<StatusSummary>("/status"),
  getHealth: () => req<{ status: string }>("/health"),
  updateYtdlp: () => req<{ version: string }>("/ytdlp/update", { method: "POST" }),
  testJellyfin: () => req<{ ok: boolean }>("/jellyfin/test", { method: "POST" }),
  activityUrl: () => `${BASE}/activity`,
};
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/api.test.ts`
Expected: PASS (5 passed).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types.ts frontend/src/api.ts frontend/src/api.test.ts
git commit -m "feat: add API types and same-origin /api fetch client"
```

---

### Task 3: StatusPill + CountdownBadge

Two small presentational components with per-state RTL tests.

**Files:**
- Create: `frontend/src/components/StatusPill.tsx`
- Create: `frontend/src/components/CountdownBadge.tsx`
- Test: `frontend/src/components/StatusPill.test.tsx`
- Test: `frontend/src/components/CountdownBadge.test.tsx`

**Interfaces:**
- Consumes: `Status` from `../types`.
- Produces:
  - `StatusPill({ status: Status; pct?: number | null }): JSX.Element` (testid `status-pill`).
  - `CountdownBadge({ digitalDate: string | null; now?: Date }): JSX.Element` (testid `countdown-badge`).
  - `daysUntil(iso: string | null, now?: Date): number | null` (named export from CountdownBadge).

- [ ] **Step 1: Write the failing test `frontend/src/components/StatusPill.test.tsx`**

```tsx
import { render, screen } from "@testing-library/react";
import { StatusPill } from "./StatusPill";

test("renders plain label for ready", () => {
  render(<StatusPill status="ready" />);
  expect(screen.getByTestId("status-pill")).toHaveTextContent("ready");
});

test("renders percent for downloading", () => {
  render(<StatusPill status="downloading" pct={42.6} />);
  expect(screen.getByTestId("status-pill")).toHaveTextContent("downloading 43%");
});

test("downloading without pct omits percent", () => {
  render(<StatusPill status="downloading" />);
  expect(screen.getByTestId("status-pill")).toHaveTextContent("downloading");
  expect(screen.getByTestId("status-pill")).not.toHaveTextContent("%");
});

test("applies per-status class", () => {
  render(<StatusPill status="failed" />);
  expect(screen.getByTestId("status-pill").className).toContain("status-failed");
});
```

- [ ] **Step 2: Write the failing test `frontend/src/components/CountdownBadge.test.tsx`**

```tsx
import { render, screen } from "@testing-library/react";
import { CountdownBadge, daysUntil } from "./CountdownBadge";

const NOW = new Date("2026-07-11T00:00:00Z");

test("daysUntil rounds up future dates", () => {
  expect(daysUntil("2026-08-22T00:00:00Z", NOW)).toBe(42);
});

test("daysUntil returns null for null/invalid", () => {
  expect(daysUntil(null, NOW)).toBeNull();
  expect(daysUntil("not-a-date", NOW)).toBeNull();
});

test("future date shows streams in Nd", () => {
  render(<CountdownBadge digitalDate="2026-08-22T00:00:00Z" now={NOW} />);
  expect(screen.getByTestId("countdown-badge")).toHaveTextContent("streams in 42d");
});

test("today shows streams today", () => {
  render(<CountdownBadge digitalDate="2026-07-11T00:00:00Z" now={NOW} />);
  expect(screen.getByTestId("countdown-badge")).toHaveTextContent("streams today");
});

test("past date shows streaming now", () => {
  render(<CountdownBadge digitalDate="2026-06-01T00:00:00Z" now={NOW} />);
  expect(screen.getByTestId("countdown-badge")).toHaveTextContent("streaming now");
});

test("missing date shows TBA", () => {
  render(<CountdownBadge digitalDate={null} now={NOW} />);
  expect(screen.getByTestId("countdown-badge")).toHaveTextContent("date TBA");
});
```

- [ ] **Step 3: Run both tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/StatusPill.test.tsx src/components/CountdownBadge.test.tsx`
Expected: FAIL — cannot resolve `./StatusPill` / `./CountdownBadge`.

- [ ] **Step 4: Write `frontend/src/components/StatusPill.tsx`**

```tsx
import type { Status } from "../types";

export function StatusPill({
  status,
  pct,
}: {
  status: Status;
  pct?: number | null;
}) {
  let label: string;
  switch (status) {
    case "queued":
      label = "queued";
      break;
    case "downloading":
      label = pct != null ? `downloading ${Math.round(pct)}%` : "downloading";
      break;
    case "ready":
      label = "ready";
      break;
    case "failed":
      label = "failed";
      break;
    case "expired":
      label = "expired";
      break;
    default:
      label = status;
  }
  return (
    <span className={`status-pill status-${status}`} data-testid="status-pill">
      {label}
    </span>
  );
}
```

- [ ] **Step 5: Write `frontend/src/components/CountdownBadge.tsx`**

```tsx
export function daysUntil(iso: string | null, now: Date = new Date()): number | null {
  if (!iso) return null;
  const target = new Date(iso);
  if (Number.isNaN(target.getTime())) return null;
  const ms = target.getTime() - now.getTime();
  return Math.ceil(ms / (1000 * 60 * 60 * 24));
}

export function CountdownBadge({
  digitalDate,
  now,
}: {
  digitalDate: string | null;
  now?: Date;
}) {
  const d = daysUntil(digitalDate, now ?? new Date());
  let label: string;
  if (d === null) label = "date TBA";
  else if (d > 0) label = `streams in ${d}d`;
  else if (d === 0) label = "streams today";
  else label = "streaming now";
  return (
    <span className="countdown-badge" data-testid="countdown-badge">
      {label}
    </span>
  );
}
```

- [ ] **Step 6: Run both tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/StatusPill.test.tsx src/components/CountdownBadge.test.tsx`
Expected: PASS (all passed).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/StatusPill.tsx frontend/src/components/CountdownBadge.tsx \
  frontend/src/components/StatusPill.test.tsx frontend/src/components/CountdownBadge.test.tsx
git commit -m "feat: add StatusPill and CountdownBadge components"
```

---

### Task 4: MovieCard

Poster card composing the badges, a pin toggle, and a download/delete action menu.

**Files:**
- Create: `frontend/src/components/MovieCard.tsx`
- Test: `frontend/src/components/MovieCard.test.tsx`

**Interfaces:**
- Consumes: `Movie` from `../types`; `StatusPill`, `CountdownBadge` (Task 3).
- Produces: `MovieCard(props: MovieCardProps): JSX.Element` where
  `MovieCardProps = { movie: Movie; now?: Date; onPin: (id:number)=>void; onDownload: (id:number)=>void; onDelete: (id:number)=>void }`.
  Also `posterUrlFor(movie: Movie): string | null` (named export).

- [ ] **Step 1: Write the failing test `frontend/src/components/MovieCard.test.tsx`**

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { MovieCard, posterUrlFor } from "./MovieCard";
import type { Movie } from "../types";

function makeMovie(over: Partial<Movie> = {}): Movie {
  return {
    tmdb_id: 1234567,
    title: "Dune: Part Three",
    year: 2026,
    overview: "Coming soon.",
    runtime: 180,
    genres: ["Science Fiction"],
    studios: ["Legendary"],
    certification: "PG-13",
    premiere_date: "2026-12-18",
    digital_date: "2026-08-22T00:00:00Z",
    digital_date_source: "region",
    region: "US",
    popularity: 900,
    poster_path: "/abc.jpg",
    backdrop_path: "/def.jpg",
    youtube_key: "xyz",
    status: "ready",
    file_path: null,
    folder: null,
    jellyfin_item_id: null,
    pinned: false,
    added_at: "2026-07-01T00:00:00Z",
    expires_at: null,
    last_checked: null,
    error_kind: null,
    error_msg: null,
    poster_url: null,
    backdrop_url: null,
    download_pct: null,
    ...over,
  };
}

const NOW = new Date("2026-07-11T00:00:00Z");

test("renders title, year, status pill and countdown", () => {
  render(
    <MovieCard movie={makeMovie()} now={NOW} onPin={vi.fn()} onDownload={vi.fn()} onDelete={vi.fn()} />,
  );
  expect(screen.getByText(/Dune: Part Three/)).toBeInTheDocument();
  expect(screen.getByText(/2026/)).toBeInTheDocument();
  expect(screen.getByTestId("status-pill")).toHaveTextContent("ready");
  expect(screen.getByTestId("countdown-badge")).toHaveTextContent("streams in 42d");
});

test("downloading status shows live percent from download_pct", () => {
  render(
    <MovieCard
      movie={makeMovie({ status: "downloading", download_pct: 37 })}
      now={NOW}
      onPin={vi.fn()}
      onDownload={vi.fn()}
      onDelete={vi.fn()}
    />,
  );
  expect(screen.getByTestId("status-pill")).toHaveTextContent("downloading 37%");
});

test("pin button fires onPin with tmdb_id", async () => {
  const onPin = vi.fn();
  render(
    <MovieCard movie={makeMovie()} now={NOW} onPin={onPin} onDownload={vi.fn()} onDelete={vi.fn()} />,
  );
  await userEvent.click(screen.getByRole("button", { name: /pin/i }));
  expect(onPin).toHaveBeenCalledWith(1234567);
});

test("menu download and delete fire callbacks", async () => {
  const onDownload = vi.fn();
  const onDelete = vi.fn();
  render(
    <MovieCard
      movie={makeMovie()}
      now={NOW}
      onPin={vi.fn()}
      onDownload={onDownload}
      onDelete={onDelete}
    />,
  );
  await userEvent.click(screen.getByRole("button", { name: /actions/i }));
  await userEvent.click(screen.getByRole("button", { name: /download/i }));
  expect(onDownload).toHaveBeenCalledWith(1234567);
  await userEvent.click(screen.getByRole("button", { name: /actions/i }));
  await userEvent.click(screen.getByRole("button", { name: /delete/i }));
  expect(onDelete).toHaveBeenCalledWith(1234567);
});

test("posterUrlFor prefers API url then builds TMDB url then null", () => {
  expect(posterUrlFor(makeMovie({ poster_url: "http://x/p.jpg" }))).toBe("http://x/p.jpg");
  expect(posterUrlFor(makeMovie({ poster_url: null, poster_path: "/abc.jpg" }))).toBe(
    "https://image.tmdb.org/t/p/w500/abc.jpg",
  );
  expect(posterUrlFor(makeMovie({ poster_url: null, poster_path: null }))).toBeNull();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/components/MovieCard.test.tsx`
Expected: FAIL — cannot resolve `./MovieCard`.

- [ ] **Step 3: Write `frontend/src/components/MovieCard.tsx`**

```tsx
import { useState } from "react";
import type { Movie } from "../types";
import { StatusPill } from "./StatusPill";
import { CountdownBadge } from "./CountdownBadge";

export function posterUrlFor(movie: Movie): string | null {
  if (movie.poster_url) return movie.poster_url;
  if (movie.poster_path) return `https://image.tmdb.org/t/p/w500${movie.poster_path}`;
  return null;
}

export interface MovieCardProps {
  movie: Movie;
  now?: Date;
  onPin: (id: number) => void;
  onDownload: (id: number) => void;
  onDelete: (id: number) => void;
}

export function MovieCard({ movie, now, onPin, onDownload, onDelete }: MovieCardProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const poster = posterUrlFor(movie);

  return (
    <article className={`movie-card${movie.pinned ? " is-pinned" : ""}`}>
      <div className="movie-card-poster">
        {poster ? (
          <img src={poster} alt={`${movie.title} poster`} loading="lazy" />
        ) : (
          <div className="movie-card-poster--empty" aria-hidden="true" />
        )}
        <div className="movie-card-badges">
          <CountdownBadge digitalDate={movie.digital_date} now={now} />
          <StatusPill status={movie.status} pct={movie.download_pct} />
        </div>
        <button
          type="button"
          className={`pin-toggle${movie.pinned ? " active" : ""}`}
          aria-label={movie.pinned ? "Unpin" : "Pin"}
          aria-pressed={movie.pinned}
          onClick={() => onPin(movie.tmdb_id)}
        >
          {movie.pinned ? "★" : "☆"}
        </button>
      </div>

      <div className="movie-card-body">
        <h3 className="movie-card-title">{movie.title}</h3>
        <div className="movie-card-meta">
          {movie.year != null && <span className="movie-card-year">{movie.year}</span>}
          {movie.certification && <span className="movie-card-cert">{movie.certification}</span>}
        </div>
        <div className="movie-card-actions">
          <button
            type="button"
            aria-label="Actions"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((v) => !v)}
          >
            ⋯
          </button>
          {menuOpen && (
            <div className="movie-card-menu" role="menu">
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setMenuOpen(false);
                  onDownload(movie.tmdb_id);
                }}
              >
                Download
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setMenuOpen(false);
                  onDelete(movie.tmdb_id);
                }}
              >
                Delete
              </button>
            </div>
          )}
        </div>
      </div>
    </article>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/components/MovieCard.test.tsx`
Expected: PASS (all passed).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/MovieCard.tsx frontend/src/components/MovieCard.test.tsx
git commit -m "feat: add MovieCard with badges, pin toggle and action menu"
```

---

### Task 5: DashboardPage

Poster grid with filter (status) and sort (soonest-to-stream / popularity), loading from `api.getMovies`.

**Files:**
- Create: `frontend/src/pages/DashboardPage.tsx`
- Test: `frontend/src/pages/DashboardPage.test.tsx`

**Interfaces:**
- Consumes: `api` (Task 2); `MovieCard` (Task 4); `Movie` from `../types`.
- Produces: `DashboardPage(): JSX.Element`.

- [ ] **Step 1: Write the failing test `frontend/src/pages/DashboardPage.test.tsx`**

```tsx
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, vi } from "vitest";
import { DashboardPage } from "./DashboardPage";
import { api } from "../api";
import type { Movie } from "../types";

vi.mock("../api", () => ({
  api: {
    getMovies: vi.fn(),
    pinMovie: vi.fn(),
    downloadMovie: vi.fn(),
    deleteMovie: vi.fn(),
  },
}));

function makeMovie(over: Partial<Movie>): Movie {
  return {
    tmdb_id: 0,
    title: "T",
    year: 2026,
    overview: "",
    runtime: null,
    genres: [],
    studios: [],
    certification: null,
    premiere_date: null,
    digital_date: null,
    digital_date_source: "none",
    region: "US",
    popularity: 0,
    poster_path: null,
    backdrop_path: null,
    youtube_key: null,
    status: "ready",
    file_path: null,
    folder: null,
    jellyfin_item_id: null,
    pinned: false,
    added_at: "2026-07-01T00:00:00Z",
    expires_at: null,
    last_checked: null,
    error_kind: null,
    error_msg: null,
    poster_url: null,
    backdrop_url: null,
    download_pct: null,
    ...over,
  };
}

const movies: Movie[] = [
  makeMovie({ tmdb_id: 1, title: "Soon", digital_date: "2026-08-01T00:00:00Z", popularity: 10, status: "ready" }),
  makeMovie({ tmdb_id: 2, title: "Later", digital_date: "2026-12-01T00:00:00Z", popularity: 99, status: "failed" }),
  makeMovie({ tmdb_id: 3, title: "NoDate", digital_date: null, popularity: 50, status: "ready" }),
];

beforeEach(() => {
  vi.clearAllMocks();
  (api.getMovies as ReturnType<typeof vi.fn>).mockResolvedValue(movies);
});

test("loads and renders all movie titles", async () => {
  render(<DashboardPage />);
  expect(await screen.findByText("Soon")).toBeInTheDocument();
  expect(screen.getByText("Later")).toBeInTheDocument();
  expect(screen.getByText("NoDate")).toBeInTheDocument();
});

test("default sort is soonest-to-stream (nulls last)", async () => {
  render(<DashboardPage />);
  await screen.findByText("Soon");
  const titles = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
  expect(titles).toEqual(["Soon", "Later", "NoDate"]);
});

test("status filter narrows the grid", async () => {
  render(<DashboardPage />);
  await screen.findByText("Soon");
  await userEvent.selectOptions(screen.getByLabelText("Filter by status"), "failed");
  expect(screen.getByText("Later")).toBeInTheDocument();
  expect(screen.queryByText("Soon")).not.toBeInTheDocument();
});

test("popularity sort reorders", async () => {
  render(<DashboardPage />);
  await screen.findByText("Soon");
  await userEvent.selectOptions(screen.getByLabelText("Sort by"), "popularity");
  const titles = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
  expect(titles).toEqual(["Later", "NoDate", "Soon"]);
});

test("pin action calls api.pinMovie and reloads", async () => {
  (api.pinMovie as ReturnType<typeof vi.fn>).mockResolvedValue(movies[0]);
  render(<DashboardPage />);
  await screen.findByText("Soon");
  const card = screen.getByText("Soon").closest("article")!;
  await userEvent.click(within(card).getByRole("button", { name: /pin/i }));
  expect(api.pinMovie).toHaveBeenCalledWith(1);
  await waitFor(() => expect(api.getMovies).toHaveBeenCalledTimes(2));
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/DashboardPage.test.tsx`
Expected: FAIL — cannot resolve `./DashboardPage`.

- [ ] **Step 3: Write `frontend/src/pages/DashboardPage.tsx`**

```tsx
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { Movie, Status } from "../types";
import { MovieCard } from "../components/MovieCard";

type Filter = "all" | Status;
type Sort = "soonest" | "popularity";

const FILTERS: Filter[] = ["all", "queued", "downloading", "ready", "failed", "expired"];

export function DashboardPage() {
  const [movies, setMovies] = useState<Movie[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<Sort>("soonest");

  const reload = useCallback(() => {
    setLoading(true);
    api
      .getMovies()
      .then((m) => {
        setMovies(m);
        setError(null);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const onPin = (id: number) => api.pinMovie(id).then(reload);
  const onDownload = (id: number) => api.downloadMovie(id).then(reload);
  const onDelete = (id: number) => api.deleteMovie(id).then(reload);

  const shown = useMemo(() => {
    let list = movies;
    if (filter !== "all") list = list.filter((m) => m.status === filter);
    return [...list].sort((a, b) => {
      if (sort === "popularity") return b.popularity - a.popularity;
      const ax = a.digital_date ? new Date(a.digital_date).getTime() : Infinity;
      const bx = b.digital_date ? new Date(b.digital_date).getTime() : Infinity;
      return ax - bx;
    });
  }, [movies, filter, sort]);

  return (
    <section className="dashboard">
      <div className="dashboard-controls">
        <label>
          Filter by status
          <select value={filter} onChange={(e) => setFilter(e.target.value as Filter)}>
            {FILTERS.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        </label>
        <label>
          Sort by
          <select value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
            <option value="soonest">Soonest to stream</option>
            <option value="popularity">Popularity</option>
          </select>
        </label>
      </div>

      {loading && <p className="dashboard-status">Loading titles…</p>}
      {error && <p className="dashboard-error">{error}</p>}
      {!loading && !error && shown.length === 0 && (
        <p className="dashboard-status">No titles yet. Run a refresh from Settings.</p>
      )}

      <div className="poster-grid">
        {shown.map((m) => (
          <MovieCard
            key={m.tmdb_id}
            movie={m}
            onPin={onPin}
            onDownload={onDownload}
            onDelete={onDelete}
          />
        ))}
      </div>
    </section>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/DashboardPage.test.tsx`
Expected: PASS (all passed).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/DashboardPage.tsx frontend/src/pages/DashboardPage.test.tsx
git commit -m "feat: add DashboardPage poster grid with filter and sort"
```

---

### Task 6: ActivityPage + ActivityLog (SSE)

Live log and download progress bars driven by an `EventSource` on `/api/activity`.

**Files:**
- Create: `frontend/src/components/ActivityLog.tsx`
- Create: `frontend/src/pages/ActivityPage.tsx`
- Test: `frontend/src/components/ActivityLog.test.tsx`

**Interfaces:**
- Consumes: `api.activityUrl()` (Task 2); `ActivityMessage`, `ActivityEntry` from `../types`.
- Produces: `ActivityLog(): JSX.Element`; `ActivityPage(): JSX.Element`.

- [ ] **Step 1: Write the failing test `frontend/src/components/ActivityLog.test.tsx`**

```tsx
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";
import { ActivityLog } from "./ActivityLog";

class MockEventSource {
  static instances: MockEventSource[] = [];
  url: string;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  readyState = 0;
  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }
  close() {
    this.readyState = 2;
  }
  emit(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent);
  }
}

beforeEach(() => {
  MockEventSource.instances = [];
  vi.stubGlobal("EventSource", MockEventSource as unknown as typeof EventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("connects to the SSE activity endpoint", () => {
  render(<ActivityLog />);
  expect(MockEventSource.instances[0].url).toBe("/api/activity");
});

test("appends log entries as they arrive", () => {
  render(<ActivityLog />);
  const es = MockEventSource.instances[0];
  act(() => {
    es.emit({
      type: "log",
      entry: { id: 1, ts: "2026-07-11T00:00:00Z", level: "info", event: "download", tmdb_id: 5, message: "Downloaded Dune" },
    });
  });
  expect(screen.getByText("Downloaded Dune")).toBeInTheDocument();
});

test("renders a progress bar for active downloads", () => {
  render(<ActivityLog />);
  const es = MockEventSource.instances[0];
  act(() => {
    es.emit({ type: "progress", tmdb_id: 5, pct: 62, speed: 3251200, eta: 10 });
  });
  const bar = screen.getByTestId("progress-5");
  expect(bar).toHaveAttribute("value", "62");
  expect(screen.getByText(/62%/)).toBeInTheDocument();
});

test("closes the connection on unmount", () => {
  const { unmount } = render(<ActivityLog />);
  const es = MockEventSource.instances[0];
  unmount();
  expect(es.readyState).toBe(2);
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/components/ActivityLog.test.tsx`
Expected: FAIL — cannot resolve `./ActivityLog`.

- [ ] **Step 3: Write `frontend/src/components/ActivityLog.tsx`**

```tsx
import { useEffect, useState } from "react";
import { api } from "../api";
import type { ActivityEntry, ActivityMessage } from "../types";

interface Progress {
  pct: number;
  speed: number | null;
  eta: number | null;
}

export function ActivityLog() {
  const [entries, setEntries] = useState<ActivityEntry[]>([]);
  const [progress, setProgress] = useState<Record<number, Progress>>({});

  useEffect(() => {
    const es = new EventSource(api.activityUrl());
    es.onmessage = (e) => {
      let msg: ActivityMessage;
      try {
        msg = JSON.parse(e.data) as ActivityMessage;
      } catch {
        return;
      }
      if (msg.type === "log") {
        setEntries((prev) => [msg.entry, ...prev].slice(0, 500));
      } else if (msg.type === "progress") {
        setProgress((prev) => ({
          ...prev,
          [msg.tmdb_id]: { pct: msg.pct, speed: msg.speed, eta: msg.eta },
        }));
      }
    };
    return () => es.close();
  }, []);

  const active = Object.entries(progress).filter(([, p]) => p.pct < 100);

  return (
    <section className="activity">
      {active.length > 0 && (
        <div className="activity-progress">
          {active.map(([id, p]) => (
            <div key={id} className="activity-progress-row">
              <span className="activity-progress-id">#{id}</span>
              <progress data-testid={`progress-${id}`} max={100} value={p.pct} />
              <span className="activity-progress-pct">{Math.round(p.pct)}%</span>
              {p.speed && <span className="activity-progress-speed">{p.speed}</span>}
              {p.eta && <span className="activity-progress-eta">ETA {p.eta}</span>}
            </div>
          ))}
        </div>
      )}

      <ul className="activity-log">
        {entries.map((en) => (
          <li key={en.id} className={`activity-line level-${en.level}`}>
            <time>{new Date(en.ts).toLocaleTimeString()}</time>
            <span className="activity-event">{en.event}</span>
            <span className="activity-message">{en.message}</span>
          </li>
        ))}
      </ul>
      {entries.length === 0 && active.length === 0 && (
        <p className="activity-empty">Waiting for activity…</p>
      )}
    </section>
  );
}
```

- [ ] **Step 4: Write `frontend/src/pages/ActivityPage.tsx`**

```tsx
import { ActivityLog } from "../components/ActivityLog";

export function ActivityPage() {
  return (
    <section className="activity-page">
      <h2>Activity</h2>
      <ActivityLog />
    </section>
  );
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/components/ActivityLog.test.tsx`
Expected: PASS (all passed).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ActivityLog.tsx frontend/src/pages/ActivityPage.tsx \
  frontend/src/components/ActivityLog.test.tsx
git commit -m "feat: add SSE ActivityLog with live progress and ActivityPage"
```

---

### Task 7: StatusBar + SettingsForm/SettingsPage, wire App routes

Status bar (next runs, counts, disk, yt-dlp version + update), the grouped settings form with Test-Jellyfin/Run-now, and the final routed `App`.

**Files:**
- Create: `frontend/src/components/StatusBar.tsx`
- Create: `frontend/src/components/SettingsForm.tsx`
- Create: `frontend/src/pages/SettingsPage.tsx`
- Modify: `frontend/src/App.tsx` (add routes + StatusBar)
- Test: `frontend/src/components/StatusBar.test.tsx`
- Test: `frontend/src/components/SettingsForm.test.tsx`

**Interfaces:**
- Consumes: `api` (Task 2); `Config`, `StatusSummary` from `../types`; `DashboardPage`, `ActivityPage` (Tasks 5–6).
- Produces: `StatusBar(): JSX.Element`; `SettingsForm(): JSX.Element`; `SettingsPage(): JSX.Element`; routed `App`.

- [ ] **Step 1: Write the failing test `frontend/src/components/StatusBar.test.tsx`**

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, vi } from "vitest";
import { StatusBar } from "./StatusBar";
import { api } from "../api";
import type { StatusSummary } from "../types";

vi.mock("../api", () => ({
  api: { getStatus: vi.fn(), updateYtdlp: vi.fn() },
}));

const summary: StatusSummary = {
  next_refresh: "2026-07-12T03:00:00Z",
  next_reap: "2026-07-12T04:00:00Z",
  running: false,
  counts: { ready: 40, queued: 3, downloading: 1, failed: 2, expired: 5 },
  disk: { used_gb: 12.5, free_gb: 87.5, total_gb: 100 },
  ytdlp_version: "2026.07.01",
};

beforeEach(() => {
  vi.clearAllMocks();
  (api.getStatus as ReturnType<typeof vi.fn>).mockResolvedValue(summary);
});

test("renders counts, disk and yt-dlp version", async () => {
  render(<StatusBar />);
  expect(await screen.findByText(/2026\.07\.01/)).toBeInTheDocument();
  expect(screen.getByText(/40/)).toBeInTheDocument();
  expect(screen.getByText(/87\.5 GB free/)).toBeInTheDocument();
});

test("update button calls api.updateYtdlp and refreshes status", async () => {
  (api.updateYtdlp as ReturnType<typeof vi.fn>).mockResolvedValue({ version: "2026.07.10" });
  render(<StatusBar />);
  await screen.findByText(/2026\.07\.01/);
  await userEvent.click(screen.getByRole("button", { name: /update yt-dlp/i }));
  expect(api.updateYtdlp).toHaveBeenCalled();
  await waitFor(() => expect(api.getStatus).toHaveBeenCalledTimes(2));
});
```

- [ ] **Step 2: Write the failing test `frontend/src/components/SettingsForm.test.tsx`**

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, vi } from "vitest";
import { SettingsForm } from "./SettingsForm";
import { api } from "../api";
import type { Config } from "../types";

vi.mock("../api", () => ({
  api: {
    getSettings: vi.fn(),
    updateSettings: vi.fn(),
    testJellyfin: vi.fn(),
    runNow: vi.fn(),
  },
}));

const cfg: Config = {
  tmdb_token: "tok",
  sources: ["upcoming", "now_playing"],
  count: 50,
  region: "US",
  language: "en-US",
  container: "mkv",
  max_height: 1080,
  refresh_cron: "0 3 * * *",
  reaper_cron: "0 4 * * *",
  grace_days: 0,
  tz: "UTC",
  library_dir: "/library",
  config_dir: "/config",
  max_size_gb: 0,
  jellyfin_url: null,
  jellyfin_api_key: null,
  jellyfin_user: null,
  jellyfin_pass: null,
  ytdlp_cookies: null,
  ytdlp_proxy: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  (api.getSettings as ReturnType<typeof vi.fn>).mockResolvedValue(cfg);
  (api.updateSettings as ReturnType<typeof vi.fn>).mockResolvedValue(cfg);
});

test("loads settings and round-trips an edit on save", async () => {
  render(<SettingsForm />);
  const region = (await screen.findByLabelText("region")) as HTMLInputElement;
  expect(region.value).toBe("US");
  await userEvent.clear(region);
  await userEvent.type(region, "GB");
  await userEvent.click(screen.getByRole("button", { name: /save/i }));
  await waitFor(() => expect(api.updateSettings).toHaveBeenCalled());
  const sent = (api.updateSettings as ReturnType<typeof vi.fn>).mock.calls[0][0] as Config;
  expect(sent.region).toBe("GB");
  expect(sent.sources).toEqual(["upcoming", "now_playing"]);
});

test("sources round-trip through comma text", async () => {
  render(<SettingsForm />);
  const sources = (await screen.findByLabelText("sources")) as HTMLInputElement;
  await userEvent.clear(sources);
  await userEvent.type(sources, "upcoming, popular");
  await userEvent.click(screen.getByRole("button", { name: /save/i }));
  const sent = (api.updateSettings as ReturnType<typeof vi.fn>).mock.calls[0][0] as Config;
  expect(sent.sources).toEqual(["upcoming", "popular"]);
});

test("Test Jellyfin button fires testJellyfin", async () => {
  (api.testJellyfin as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true });
  render(<SettingsForm />);
  await screen.findByLabelText("region");
  await userEvent.click(screen.getByRole("button", { name: /test jellyfin/i }));
  expect(api.testJellyfin).toHaveBeenCalled();
});

test("Run now button fires runNow", async () => {
  (api.runNow as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
  render(<SettingsForm />);
  await screen.findByLabelText("region");
  await userEvent.click(screen.getByRole("button", { name: /run now/i }));
  expect(api.runNow).toHaveBeenCalled();
});
```

- [ ] **Step 3: Run both tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/StatusBar.test.tsx src/components/SettingsForm.test.tsx`
Expected: FAIL — cannot resolve `./StatusBar` / `./SettingsForm`.

- [ ] **Step 4: Write `frontend/src/components/StatusBar.tsx`**

```tsx
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { StatusSummary } from "../types";

function fmt(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

export function StatusBar() {
  const [status, setStatus] = useState<StatusSummary | null>(null);
  const [updating, setUpdating] = useState(false);

  const reload = useCallback(() => {
    api.getStatus().then(setStatus).catch(() => undefined);
  }, []);

  useEffect(() => {
    reload();
    const t = setInterval(reload, 10000);
    return () => clearInterval(t);
  }, [reload]);

  const onUpdate = async () => {
    setUpdating(true);
    try {
      await api.updateYtdlp();
      reload();
    } finally {
      setUpdating(false);
    }
  };

  if (!status) return <div className="status-bar" data-testid="status-bar" />;

  return (
    <div className="status-bar" data-testid="status-bar">
      <span className="sb-item">
        <b>{status.counts.ready}</b> ready
      </span>
      <span className="sb-item">{status.counts.queued} queued</span>
      <span className="sb-item">{status.counts.downloading} downloading</span>
      <span className="sb-item">{status.counts.failed} failed</span>
      <span className="sb-item">Next refresh: {fmt(status.next_refresh)}</span>
      <span className="sb-item">Next reap: {fmt(status.next_reap)}</span>
      <span className="sb-item">{status.disk.free_gb.toFixed(1)} GB free</span>
      <span className="sb-item">
        yt-dlp {status.ytdlp_version}
        <button type="button" onClick={onUpdate} disabled={updating}>
          {updating ? "Updating…" : "Update yt-dlp"}
        </button>
      </span>
    </div>
  );
}
```

- [ ] **Step 5: Write `frontend/src/components/SettingsForm.tsx`**

```tsx
import { useEffect, useState } from "react";
import { api } from "../api";
import type { Config } from "../types";

const ALL_SOURCES = ["upcoming", "now_playing", "popular", "trending_day", "trending_week"];

export function SettingsForm() {
  const [cfg, setCfg] = useState<Config | null>(null);
  const [message, setMessage] = useState<string>("");

  useEffect(() => {
    api.getSettings().then(setCfg).catch((e) => setMessage(String(e)));
  }, []);

  if (!cfg) return <p>Loading settings…</p>;

  const set = <K extends keyof Config>(k: K, v: Config[K]) =>
    setCfg({ ...cfg, [k]: v });

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setMessage("Saving…");
    try {
      // GET /api/settings masks secrets as "***"; don't resend an unchanged mask
      // or we'd overwrite the stored secret with the literal "***".
      const payload: Record<string, unknown> = { ...cfg };
      for (const k of ["tmdb_token", "jellyfin_api_key", "jellyfin_pass"]) {
        if (payload[k] === "***") delete payload[k];
      }
      const saved = await api.updateSettings(payload as unknown as Config);
      setCfg(saved);
      setMessage("Saved.");
    } catch (err) {
      setMessage(String(err));
    }
  };

  const testJellyfin = async () => {
    setMessage("Testing Jellyfin…");
    try {
      const r = await api.testJellyfin();
      setMessage(r.ok ? "Jellyfin OK." : "Jellyfin test failed.");
    } catch (err) {
      setMessage(String(err));
    }
  };

  const runNow = async () => {
    setMessage("Triggering refresh…");
    try {
      await api.runNow();
      setMessage("Refresh started.");
    } catch (err) {
      setMessage(String(err));
    }
  };

  return (
    <form className="settings-form" onSubmit={save}>
      <fieldset>
        <legend>Sources</legend>
        <label>
          sources
          <input
            aria-label="sources"
            value={cfg.sources.join(", ")}
            onChange={(e) =>
              set(
                "sources",
                e.target.value
                  .split(",")
                  .map((s) => s.trim())
                  .filter(Boolean),
              )
            }
          />
        </label>
        <small>Any of: {ALL_SOURCES.join(", ")}</small>
        <label>
          count
          <input
            aria-label="count"
            type="number"
            value={cfg.count}
            onChange={(e) => set("count", Number(e.target.value))}
          />
        </label>
        <label>
          region
          <input
            aria-label="region"
            value={cfg.region}
            onChange={(e) => set("region", e.target.value)}
          />
        </label>
        <label>
          language
          <input
            aria-label="language"
            value={cfg.language}
            onChange={(e) => set("language", e.target.value)}
          />
        </label>
      </fieldset>

      <fieldset>
        <legend>Format</legend>
        <label>
          container
          <select
            aria-label="container"
            value={cfg.container}
            onChange={(e) => set("container", e.target.value)}
          >
            <option value="mkv">mkv</option>
            <option value="mp4">mp4</option>
          </select>
        </label>
        <label>
          max_height
          <input
            aria-label="max_height"
            type="number"
            value={cfg.max_height}
            onChange={(e) => set("max_height", Number(e.target.value))}
          />
        </label>
      </fieldset>

      <fieldset>
        <legend>Schedule</legend>
        <label>
          refresh_cron
          <input
            aria-label="refresh_cron"
            value={cfg.refresh_cron}
            onChange={(e) => set("refresh_cron", e.target.value)}
          />
        </label>
        <label>
          reaper_cron
          <input
            aria-label="reaper_cron"
            value={cfg.reaper_cron}
            onChange={(e) => set("reaper_cron", e.target.value)}
          />
        </label>
        <label>
          grace_days
          <input
            aria-label="grace_days"
            type="number"
            value={cfg.grace_days}
            onChange={(e) => set("grace_days", Number(e.target.value))}
          />
        </label>
        <label>
          tz
          <input aria-label="tz" value={cfg.tz} onChange={(e) => set("tz", e.target.value)} />
        </label>
        <label>
          max_size_gb
          <input
            aria-label="max_size_gb"
            type="number"
            value={cfg.max_size_gb}
            onChange={(e) => set("max_size_gb", Number(e.target.value))}
          />
        </label>
      </fieldset>

      <fieldset>
        <legend>Jellyfin</legend>
        <label>
          jellyfin_url
          <input
            aria-label="jellyfin_url"
            value={cfg.jellyfin_url ?? ""}
            onChange={(e) => set("jellyfin_url", e.target.value || null)}
          />
        </label>
        <label>
          jellyfin_api_key
          <input
            aria-label="jellyfin_api_key"
            value={cfg.jellyfin_api_key ?? ""}
            onChange={(e) => set("jellyfin_api_key", e.target.value || null)}
          />
        </label>
        <label>
          jellyfin_user
          <input
            aria-label="jellyfin_user"
            value={cfg.jellyfin_user ?? ""}
            onChange={(e) => set("jellyfin_user", e.target.value || null)}
          />
        </label>
        <label>
          jellyfin_pass
          <input
            aria-label="jellyfin_pass"
            type="password"
            value={cfg.jellyfin_pass ?? ""}
            onChange={(e) => set("jellyfin_pass", e.target.value || null)}
          />
        </label>
        <button type="button" onClick={testJellyfin}>
          Test Jellyfin
        </button>
      </fieldset>

      <fieldset>
        <legend>Advanced</legend>
        <label>
          tmdb_token
          <input
            aria-label="tmdb_token"
            value={cfg.tmdb_token}
            onChange={(e) => set("tmdb_token", e.target.value)}
          />
        </label>
        <label>
          ytdlp_cookies
          <input
            aria-label="ytdlp_cookies"
            value={cfg.ytdlp_cookies ?? ""}
            onChange={(e) => set("ytdlp_cookies", e.target.value || null)}
          />
        </label>
        <label>
          ytdlp_proxy
          <input
            aria-label="ytdlp_proxy"
            value={cfg.ytdlp_proxy ?? ""}
            onChange={(e) => set("ytdlp_proxy", e.target.value || null)}
          />
        </label>
      </fieldset>

      <div className="settings-actions">
        <button type="submit">Save</button>
        <button type="button" onClick={runNow}>
          Run now
        </button>
        {message && <span className="settings-message">{message}</span>}
      </div>
    </form>
  );
}
```

- [ ] **Step 6: Write `frontend/src/pages/SettingsPage.tsx`**

```tsx
import { SettingsForm } from "../components/SettingsForm";

export function SettingsPage() {
  return (
    <section className="settings-page">
      <h2>Settings</h2>
      <SettingsForm />
    </section>
  );
}
```

- [ ] **Step 7: Rewrite `frontend/src/App.tsx` with routes + StatusBar (complete file)**

```tsx
import { NavLink, Route, Routes } from "react-router-dom";
import { StatusBar } from "./components/StatusBar";
import { DashboardPage } from "./pages/DashboardPage";
import { ActivityPage } from "./pages/ActivityPage";
import { SettingsPage } from "./pages/SettingsPage";

export function App() {
  return (
    <div className="app">
      <header className="app-header">
        <span className="brand">MARQUEE</span>
        <nav className="app-nav">
          <NavLink to="/">Dashboard</NavLink>
          <NavLink to="/activity">Activity</NavLink>
          <NavLink to="/settings">Settings</NavLink>
        </nav>
      </header>
      <StatusBar />
      <main className="app-main">
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/activity" element={<ActivityPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  );
}
```

- [ ] **Step 8: Update the App smoke test to mock api (complete file `frontend/src/App.test.tsx`)**

The routed `App` now renders `StatusBar`/`DashboardPage`, which call the api on mount; mock the client so the smoke test stays isolated.

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { App } from "./App";

vi.mock("./api", () => ({
  api: {
    getStatus: vi.fn().mockResolvedValue({
      next_refresh: null,
      next_reap: null,
      running: false,
      counts: { ready: 0, queued: 0, downloading: 0, failed: 0, expired: 0 },
      disk: { used_gb: 0, free_gb: 0, total_gb: 0 },
      ytdlp_version: "test",
    }),
    getMovies: vi.fn().mockResolvedValue([]),
  },
}));

test("renders the Marquee brand", () => {
  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );
  expect(screen.getByText("MARQUEE")).toBeInTheDocument();
});
```

- [ ] **Step 9: Run the whole suite to verify everything passes**

Run: `cd frontend && npx vitest run`
Expected: PASS — all test files green (App, api, StatusPill, CountdownBadge, MovieCard, DashboardPage, ActivityLog, StatusBar, SettingsForm).

- [ ] **Step 10: Commit**

```bash
git add frontend/src/components/StatusBar.tsx frontend/src/components/SettingsForm.tsx \
  frontend/src/pages/SettingsPage.tsx frontend/src/App.tsx frontend/src/App.test.tsx \
  frontend/src/components/StatusBar.test.tsx frontend/src/components/SettingsForm.test.tsx
git commit -m "feat: add StatusBar, SettingsForm and wire routed App shell"
```

---

### Task 8: Apply the frontend-design skill (cinema aesthetic)

**This task is design work, not TDD.** Give the components a distinctive "coming attractions" identity while keeping all `data-testid`s, `aria-label`s, roles, and text labels the tests assert on (they must keep passing).

**Files:**
- Modify: `frontend/src/styles.css` (primary surface for the restyle)
- Modify (as needed, structure/className only — never change testids/labels/roles/visible text used in assertions): `frontend/src/App.tsx`, `frontend/src/components/*.tsx`, `frontend/src/pages/*.tsx`

**Interfaces:**
- Consumes: all components from Tasks 3–7.
- Produces: no new exported symbols; a themed, responsive stylesheet + minor markup hooks.

- [ ] **Step 1: Invoke the frontend-design skill**

Use the `frontend-design:frontend-design` skill and read its guidance before writing any CSS. Adopt an intentional, non-templated aesthetic.

- [ ] **Step 2: Apply this art direction (checklist)**

Cinema / "coming attractions" marquee aesthetic:
- [ ] **Dark, theatrical base.** Deep near-black background (e.g. `#0a0a0f`), warm marquee accent (amber/gold `#f5b301` or hot-red neon), high-contrast type. Support light theme via `@media (prefers-color-scheme: light)` and `:root[data-theme=...]` overrides so the page is theme-aware in both directions.
- [ ] **Poster-forward grid.** `.poster-grid` is a responsive `grid` with `grid-template-columns: repeat(auto-fill, minmax(180px, 1fr))`, 2:3 poster aspect (`aspect-ratio: 2/3`), subtle hover lift/scale and a soft glow. Posters are the hero — chrome recedes.
- [ ] **Marquee header.** The `MARQUEE` brand styled like a theater sign: condensed/uppercase display type, letter-spacing, optional bulb/dot flourish or top border-glow. Use one distinctive display font stack (system-available, e.g. `"Bebas Neue", "Oswald", Impact, sans-serif`) — do not ship a webfont (CSP/self-contained); fall back gracefully.
- [ ] **Badges read as signage.** `.countdown-badge` = glowing "NOW SHOWING / COMING SOON" ticket chip; `.status-pill` color-coded per state (`status-ready` green, `status-downloading` amber pulsing, `status-failed` red, `status-queued` neutral, `status-expired` muted). Downloading pill subtly animates.
- [ ] **Status bar as a film strip / ticker.** Horizontal, monospace-ish counts, sprocket or divider motif; wraps gracefully on narrow screens.
- [ ] **Activity log = projection booth.** Monospace log lines, level-colored, progress bars styled as glowing meters.
- [ ] **Responsive & no horizontal scroll.** Body never scrolls sideways; grid and status bar reflow on mobile; controls stack.
- [ ] **Motion is tasteful.** Respect `prefers-reduced-motion: reduce` (disable pulses/transitions).

- [ ] **Step 3: Verify tests still pass (no assertion-visible text/attributes changed)**

Run: `cd frontend && npx vitest run`
Expected: PASS — all files still green.

- [ ] **Step 4: Verify a production build succeeds**

Run: `cd frontend && npm run build`
Expected: build completes; assets written to `backend/marquee/api/static/`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/styles.css frontend/src/App.tsx frontend/src/components frontend/src/pages
git commit -m "feat: apply cinema coming-attractions design to the SPA"
```

Acceptance: a distinctive, non-templated theatrical look; theme-aware (light+dark); responsive with no horizontal overflow; all Vitest tests still pass.

---

### Task 9: Build integration — FastAPI serves the SPA

Point Vite's build at the package `static/` dir (already set in Task 1) and make FastAPI serve it with an SPA catch-all, verified by a backend test.

**Files:**
- Test: `backend/tests/test_spa_static.py` (integration test only)

**Interfaces:**
- Consumes: `create_app(context)` + `AppContext` (Plan 2). **SPA serving is already implemented by Plan 2's `create_app`** — it serves `AppContext.static_dir` (defaulting to the packaged `backend/marquee/api/static`), mounting `/assets` via `StaticFiles` and a `/api`-safe catch-all that falls back to `index.html`.
- Produces: **no new backend symbol.** This task (a) wires the Vite build output into `backend/marquee/api/static` (Task 1 already set `outDir` there), and (b) locks the serve-the-built-SPA behavior against regressions with an integration test using `create_app`.

- [ ] **Step 1: Write the integration test `backend/tests/test_spa_static.py`**

This test drives Plan 2's `create_app` with a built-like static dir and locks the serving contract (root, deep-link fallback, `/assets`, and `/api` isolation). SPA routes don't touch `store`/`scheduler`, so a minimal `AppContext` is sufficient.

```python
from pathlib import Path

from fastapi.testclient import TestClient

from marquee.api.app import AppContext, create_app
from marquee.api.sse import Broadcaster


def _build_static(tmp_path: Path) -> Path:
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text(
        '<!doctype html><html><head><title>Marquee</title></head>'
        '<body><div id="root"></div></body></html>',
        encoding="utf-8",
    )
    (static / "assets" / "app.js").write_text("console.log('marquee')", encoding="utf-8")
    return static


def _client(static: Path) -> TestClient:
    ctx = AppContext(
        store=None, scheduler=None, reaper=None, config=None,
        broadcaster=Broadcaster(), static_dir=str(static),
    )
    return TestClient(create_app(ctx))


def test_root_serves_index_html(tmp_path: Path) -> None:
    r = _client(_build_static(tmp_path)).get("/")
    assert r.status_code == 200
    assert "<title>Marquee</title>" in r.text


def test_deep_link_falls_back_to_index(tmp_path: Path) -> None:
    r = _client(_build_static(tmp_path)).get("/movies/1234567")
    assert r.status_code == 200
    assert '<div id="root"></div>' in r.text


def test_static_assets_are_served(tmp_path: Path) -> None:
    r = _client(_build_static(tmp_path)).get("/assets/app.js")
    assert r.status_code == 200
    assert "marquee" in r.text


def test_unknown_api_path_is_404_not_spa(tmp_path: Path) -> None:
    # The catch-all must NOT serve index.html for unknown /api/* paths.
    r = _client(_build_static(tmp_path)).get("/api/nope")
    assert r.status_code == 404
```

- [ ] **Step 2: Run the test**

Run: `cd backend && python -m pytest tests/test_spa_static.py -v`
Expected: PASS (4 passed) — Plan 2's `create_app` already implements SPA serving, so this integration test passes immediately and guards against regressions. (If it fails, a Plan 2 change broke SPA serving.)

- [ ] **Step 3: Verify the frontend build populates the packaged static dir**

Task 1 set Vite `build.outDir` to `../backend/marquee/api/static`. Confirm a build lands there:

Run: `cd frontend && npm run build && ls ../backend/marquee/api/static/index.html`
Expected: `index.html` exists under `backend/marquee/api/static/` (the same dir Plan 2's `create_app` auto-discovers).

- [ ] **Step 4: Manual end-to-end smoke (optional but recommended)**

```bash
cd frontend && npm run build && cd ..
python -m marquee serve &   # or: uvicorn per Plan 2
sleep 2
curl -sf http://localhost:3022/ | grep -q "id=\"root\"" && echo "SPA served OK"
curl -sf http://localhost:3022/settings | grep -q "id=\"root\"" && echo "Deep link OK"
curl -sf http://localhost:3022/api/health && echo " API OK"
kill %1
```

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_spa_static.py
git commit -m "test: integration test locking FastAPI SPA serving (create_app)"
```

---

### Task 10: Dockerfile + entrypoint + .dockerignore

Two-stage image: build the SPA, then a non-root Python runtime with ffmpeg + yt-dlp.

**Files:**
- Create: `Dockerfile`
- Create: `entrypoint.sh`
- Create: `.dockerignore`

**Interfaces:**
- Consumes: `frontend/` build (`npm run build -- --outDir dist`), `backend/` package (`pip install -e ./backend`), `python -m marquee serve` (Plan 1 `__main__.py`), `GET /api/health` (Plan 2).
- Produces: image entrypoint `/entrypoint.sh`; runtime user `appuser` UID 1000; volumes `/library`, `/config`; port 3022.

- [ ] **Step 1: Write `Dockerfile`**

```dockerfile
# syntax=docker/dockerfile:1

# ---- Stage 1: build the React/Vite SPA ----
FROM node:22-alpine AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
# Build into a local dist/ (the default outDir points outside the frontend root,
# which does not exist in this stage).
RUN npm run build -- --outDir dist --emptyOutDir

# ---- Stage 2: Python runtime ----
FROM python:3.13-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    LIBRARY_DIR=/library \
    CONFIG_DIR=/config

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install the backend (editable, so the copied static/ dir is used at runtime)
# plus a fresh yt-dlp with default extras.
COPY backend/ ./backend/
RUN pip install --no-cache-dir -e ./backend "yt-dlp[default]"

# Drop the built SPA into the package's static dir served by FastAPI.
COPY --from=web /app/frontend/dist ./backend/marquee/api/static

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh \
 && useradd --uid 1000 --create-home appuser \
 && mkdir -p /library /config \
 && chown -R appuser:appuser /app /library /config

USER appuser
VOLUME ["/library", "/config"]
EXPOSE 3022
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:3022/api/health || exit 1
ENTRYPOINT ["/entrypoint.sh"]
```

- [ ] **Step 2: Write `entrypoint.sh`**

```sh
#!/bin/sh
set -e

# Keep the YouTube extractor fresh; never block startup if the update fails
# (offline, rate-limited, etc.).
yt-dlp -U 2>/dev/null || true

exec python -m marquee serve
```

- [ ] **Step 3: Write `.dockerignore`**

```gitignore
# VCS / tooling
.git
.gitignore
.github

# Node
frontend/node_modules
frontend/dist

# Python
**/__pycache__
**/*.pyc
backend/.venv
backend/.pytest_cache
backend/**/*.egg-info

# Local build output copied by Vite dev builds
backend/marquee/api/static

# Docs & compose (not needed in the image)
docs
docker-compose.yml
README.md
```

- [ ] **Step 4: Docker build smoke (manual)**

```bash
docker build -t marquee:test .
# Runs the two stages; expect "Successfully tagged marquee:test".
docker run --rm -d --name marquee-smoke -p 3022:3022 -e TMDB_TOKEN=dummy marquee:test
sleep 8
curl -fsS http://localhost:3022/api/health && echo " health OK"
curl -fsS http://localhost:3022/ | grep -q 'id="root"' && echo "SPA OK"
docker rm -f marquee-smoke
```

Expected: health responds and the SPA HTML is served.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile entrypoint.sh .dockerignore
git commit -m "chore: add two-stage Dockerfile, entrypoint and dockerignore"
```

---

### Task 11: docker-compose.yml

Ship a compose file with the Marquee service and a commented Jellyfin service sharing the library.

**Files:**
- Create: `docker-compose.yml`

**Interfaces:**
- Consumes: image `ghcr.io/atvriders/marquee:latest`; env from spec §10; volumes `/library`, `/config`.
- Produces: runnable `docker compose up` deployment.

- [ ] **Step 1: Write `docker-compose.yml`**

```yaml
services:
  marquee:
    image: ghcr.io/atvriders/marquee:latest
    container_name: marquee
    restart: unless-stopped
    ports:
      - "3022:3022"
    environment:
      # --- required ---
      TMDB_TOKEN: "${TMDB_TOKEN:?set TMDB_TOKEN (v4 API Read Access Token) in .env}"
      # --- discovery ---
      SOURCES: "upcoming,now_playing"
      COUNT: "50"
      REGION: "US"
      LANGUAGE: "en-US"
      # --- format ---
      CONTAINER: "mkv"
      MAX_HEIGHT: "1080"
      # --- schedule / lifecycle ---
      REFRESH_CRON: "0 3 * * *"
      REAPER_CRON: "0 4 * * *"
      GRACE_DAYS: "0"
      TZ: "America/New_York"
      MAX_SIZE_GB: "0"
      # --- Jellyfin (optional; uncomment to enable clean deletes + scans) ---
      # JELLYFIN_URL: "http://jellyfin:8096"
      # JELLYFIN_API_KEY: "your-api-key"
      # JELLYFIN_USER: "admin"
      # JELLYFIN_PASS: "admin-password"
      # --- yt-dlp reliability (optional) ---
      # YTDLP_COOKIES: "/config/cookies.txt"
      # YTDLP_PROXY: "http://user:pass@host:port"
    volumes:
      - ./library:/library      # shared with Jellyfin (rw for Marquee)
      - marquee-config:/config  # state.db, tmp, cookies

  # Optional: run Jellyfin alongside Marquee, mounting the same library read-only.
  # Configure the "Coming Soon" Movies library per the README (§ Jellyfin setup).
  # jellyfin:
  #   image: jellyfin/jellyfin:latest
  #   container_name: jellyfin
  #   restart: unless-stopped
  #   ports:
  #     - "8096:8096"
  #   environment:
  #     PUID: "1000"   # matches Marquee's appuser so file ownership lines up
  #     PGID: "1000"
  #     TZ: "America/New_York"
  #   volumes:
  #     - ./jellyfin/config:/config
  #     - ./jellyfin/cache:/cache
  #     - ./library:/media/coming-soon:ro

volumes:
  marquee-config:
```

- [ ] **Step 2: Validate the compose file**

Run: `docker compose config >/dev/null && echo "compose OK"`
Expected: prints `compose OK` (with `TMDB_TOKEN` set in the environment or an `.env` file).

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "chore: add docker-compose with Marquee and commented Jellyfin"
```

---

### Task 12: GitHub Actions — multi-arch build & push to GHCR

**Files:**
- Create: `.github/workflows/docker.yml`

**Interfaces:**
- Consumes: repo `Dockerfile`; GHCR at `ghcr.io/atvriders/marquee`; `GITHUB_TOKEN` with `packages: write`.
- Produces: multi-arch (amd64+arm64) image pushed on push to default branch and tags.

- [ ] **Step 1: Write `.github/workflows/docker.yml`**

```yaml
name: docker

on:
  push:
    branches: [master, main]
    tags: ["v*"]
  pull_request:
    branches: [master, main]

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: atvriders/marquee

jobs:
  build-push:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up QEMU
        uses: docker/setup-qemu-action@v3

      - name: Set up Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to GHCR
        if: github.event_name != 'pull_request'
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Docker metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
          tags: |
            type=raw,value=latest,enable={{is_default_branch}}
            type=ref,event=branch
            type=ref,event=pr
            type=semver,pattern={{version}}
            type=semver,pattern={{major}}.{{minor}}
            type=sha,format=short

      - name: Build and push
        uses: docker/build-push-action@v6
        with:
          context: .
          platforms: linux/amd64,linux/arm64
          push: ${{ github.event_name != 'pull_request' }}
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

- [ ] **Step 2: Post-merge one-time step (documented, manual)**

After the first successful push, set the GHCR package **public**: GitHub → your profile/org → Packages → `marquee` → Package settings → Change visibility → Public. (Required by the Global Constraints; cannot be done from the workflow.)

- [ ] **Step 3: Validate workflow YAML locally**

Run: `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/docker.yml')); print('workflow YAML OK')"`
Expected: prints `workflow YAML OK`.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/docker.yml
git commit -m "ci: multi-arch buildx push to ghcr.io/atvriders/marquee"
```

---

### Task 13: README.md

User-facing docs: what it is, quick start, the exact Jellyfin library setup, config table, troubleshooting.

**Files:**
- Create: `README.md`

**Interfaces:**
- Consumes: spec §1, §5, §10, §15; `docker-compose.yml` (Task 11).
- Produces: repository README.

- [ ] **Step 1: Write `README.md`**

````markdown
# Marquee

**Marquee** keeps a self-hosted Jellyfin **"Coming Soon" _Movies_ library** stocked with the
trailers of the top ~50 new & upcoming movies from TMDB. Each film gets its own library
folder where the downloaded **trailer (MKV) is the movie file**, alongside a `movie.nfo` and
poster/backdrop, so Jellyfin shows it as a real, browsable title. When TMDB reports a movie
has reached its **digital (streaming) release**, Marquee **auto-deletes** the entry — folder
_and_ Jellyfin item — so the library always shows "great stuff coming that you can't stream yet."

- **Auto-expiring lifecycle** keyed on TMDB digital release date.
- **Standalone, TMDB-first** — no Radarr/Sonarr or owned media required.
- A **browsable "Coming Soon" Movies library** with real per-title metadata.
- **Bounded + churning** (top-N) so storage stays capped and fresh.
- Full **web control center**: poster grid, countdowns, live activity, scheduler, settings.

Image: `ghcr.io/atvriders/marquee` · Web UI on port **3022**.

---

## Quick start (Docker Compose)

1. Get a **TMDB v4 API Read Access Token** (TMDB → Settings → API → *API Read Access Token*).
2. Create a project folder and add `docker-compose.yml` (from this repo) and an `.env`:

   ```dotenv
   TMDB_TOKEN=eyJhbGciOi...your-v4-read-token...
   ```

3. Start it:

   ```bash
   docker compose up -d
   ```

4. Open **http://localhost:3022**. Go to **Settings**, review sources/schedule, click **Run now**
   to populate the library immediately (otherwise it runs on the `REFRESH_CRON`).

Movies are written under `./library/` as:

```
library/
└── Dune Part Three (2026) [tmdbid-1234567]/
    ├── Dune Part Three (2026) [tmdbid-1234567].mkv
    ├── movie.nfo
    ├── poster.jpg
    └── backdrop.jpg
```

---

## Jellyfin "Coming Soon" library setup (do this exactly)

Marquee writes authoritative local NFO + artwork. Jellyfin must be told to **trust the local
files and not "correct" them** from TMDB/OMDb, or your unreleased entries will get overwritten.

1. In Jellyfin: **Dashboard → Libraries → Add Media Library**.
2. **Content type:** **Movies**.
3. **Folder:** add the shared library path (e.g. `/media/coming-soon`, mounted **read-only** —
   see the commented `jellyfin` service in `docker-compose.yml`). Marquee has it as `/library`.
4. In the library's settings, under **Metadata downloaders (Movies)**:
   - Drag **Nfo** to the **top** of the list (highest priority).
   - **Uncheck** **The Movie Database** and **Open Movie Database (OMDb)** **metadata downloaders**.
5. Under **Image fetchers (Movies)**: **uncheck** **The Movie Database** and any other image fetchers.
6. Leave **Nfo** **metadata _saver_** **off** (do not let Jellyfin rewrite our NFO).
7. Save. **Never run "Refresh metadata → Replace all metadata"** on this library — it would
   re-fetch from TMDB and clobber the coming-soon overrides.

This makes the local `movie.nfo` + `poster.jpg`/`backdrop.jpg` authoritative, and the deterministic
`[tmdbid-N]` folder tag guarantees correct matching.

**Clean deletes (recommended):** set `JELLYFIN_URL`, `JELLYFIN_API_KEY`, and admin
`JELLYFIN_USER`/`JELLYFIN_PASS`. Marquee then triggers library scans after each run and uses an
authenticated `DELETE /Items/{id}` when expiring a title, which avoids **ghost items**. The API
key alone cannot delete items — the admin username/password is required for the delete call.

---

## Configuration

Set via environment variables (compose) and overridable live in the **Settings** page.

| Key | Default | Notes |
|---|---|---|
| `TMDB_TOKEN` | — (required) | TMDB v4 API Read Access Token |
| `SOURCES` | `upcoming,now_playing` | subset of `upcoming,now_playing,popular,trending_day,trending_week` |
| `COUNT` | `50` | top-N titles (10–200) |
| `REGION` | `US` | ISO 3166-1 region for lists + digital-date lookup |
| `LANGUAGE` | `en-US` | TMDB language |
| `CONTAINER` | `mkv` | `mkv` \| `mp4` (mp4 needs H.264/AAC; falls back to mkv otherwise) |
| `MAX_HEIGHT` | `1080` | resolution cap |
| `REFRESH_CRON` | `0 3 * * *` | discover/download job (daily 03:00) |
| `REAPER_CRON` | `0 4 * * *` | expiry job (daily 04:00) |
| `GRACE_DAYS` | `0` | days after digital release before deletion |
| `TZ` | `UTC` | timezone for end-of-day expiry comparison |
| `LIBRARY_DIR` | `/library` | shared with Jellyfin |
| `CONFIG_DIR` | `/config` | state db, tmp, cookies |
| `MAX_SIZE_GB` | `0` (off) | optional total-size cap with LRU eviction |
| `JELLYFIN_URL` | — | optional; enables scans + clean deletes |
| `JELLYFIN_API_KEY` | — | for library scans |
| `JELLYFIN_USER` / `JELLYFIN_PASS` | — | admin login for `DELETE /Items` (ghost-free) |
| `YTDLP_COOKIES` | — | optional `/config/cookies.txt` (bot-check mitigation) |
| `YTDLP_PROXY` | — | optional proxy URL |

---

## How it works

- **Refresh job:** discover (merge configured TMDB lists, dedupe, rank by popularity, top-N) →
  enrich (`append_to_response=videos,release_dates,images`) → pick best YouTube trailer →
  download with yt-dlp (`bv*[height<=1080]+ba/b[height<=1080]/b`, stream-copy remux to MKV) →
  write folder + NFO + artwork → notify Jellyfin.
- **Reaper job:** for each ready title, if the TMDB **digital** date (type 4, with region → US →
  global → physical → TV fallback) plus `GRACE_DAYS` has passed (end-of-day in `TZ`) and it is
  **not pinned**, delete the folder and the Jellyfin item.
- **Pinning:** pinned titles are never auto-expired and never evicted for overflow.

---

## Troubleshooting

**YouTube "Sign in to confirm you're not a bot" / downloads failing.**
Datacenter IPs get bot-checked. Marquee runs `yt-dlp -U` on start and rotates player clients, but
if failures persist:
- Export cookies from a logged-in browser to `./config/cookies.txt` and set
  `YTDLP_COOKIES=/config/cookies.txt`.
- Or route through a residential proxy with `YTDLP_PROXY=http://user:pass@host:port`.
- Failures are logged and **retried next run** — they never crash the app.

**yt-dlp extraction broke after a YouTube change.**
Click **Update yt-dlp** in the status bar (or restart the container; the entrypoint self-updates).

**Ghost items in Jellyfin after a title expired.**
This happens when Jellyfin isn't configured for clean deletes. Set `JELLYFIN_URL` +
`JELLYFIN_API_KEY` + admin `JELLYFIN_USER`/`JELLYFIN_PASS` so Marquee can call
`DELETE /Items/{id}`. To clear an existing ghost manually: Jellyfin → the item → **Delete**, or
remove it from the library and rescan.

**Jellyfin overwrote my coming-soon metadata / wrong poster.**
The library isn't locked to local files. Re-check the **Jellyfin setup** steps above: Nfo reader
first, TMDB/OMDb metadata **and** image fetchers unchecked, Nfo saver off, and never "Replace all
metadata".

**New titles don't appear in Jellyfin.**
Configure `JELLYFIN_URL`/`JELLYFIN_API_KEY` so Marquee triggers a scan after each run, or trigger a
library scan in Jellyfin manually.

---

## Development

```bash
# Backend (Plans 1–2)
cd backend && pip install -e . "yt-dlp[default]" && pytest

# Frontend
cd frontend && npm install && npm run dev   # proxies /api -> :3022
npm run test                                # Vitest + RTL
npm run build                               # outputs into backend/marquee/api/static
```

## License

See repository.
````

- [ ] **Step 2: Sanity-check the README renders as valid Markdown**

Run: `python -c "import pathlib; assert pathlib.Path('README.md').read_text().count('```') % 2 == 0; print('fences balanced')"`
Expected: prints `fences balanced`.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add README with quick start, Jellyfin setup and troubleshooting"
```

---

## Self-Review

### 1. Spec-coverage checklist

| Spec requirement | Task |
|---|---|
| §11 API surface consumed by a typed client | Task 2 (`api.ts` covers all 14 endpoints + SSE URL) |
| §9/§11 JSON shapes mirrored in TS | Task 2 (`types.ts`: Movie, Status, Config, ActivityEntry, StatusSummary, ActivityMessage) |
| §12 Dashboard poster grid, status pill, countdown, pin, per-card menu, filter/sort | Tasks 3–5 |
| §12 status pill `downloading NN%` | Task 3 (StatusPill), Task 4 (via `download_pct`) |
| §12 streaming-countdown badge | Task 3 (CountdownBadge) |
| §12 Activity live log (SSE) + progress bars | Task 6 |
| §12 Status bar: next runs, counts, disk, yt-dlp version + update | Task 7 (StatusBar) |
| §12 Settings: all §10 fields grouped + Test Jellyfin + Run now | Task 7 (SettingsForm) |
| §12/§35 cinema aesthetic via frontend-design skill | Task 8 |
| §13 SPA served by FastAPI + catch-all, `/api` unshadowed | Task 9 (integration test over Plan 2's `create_app`, which owns SPA serving) |
| §13 two-stage image (node build → python runtime), ffmpeg + yt-dlp, non-root UID 1000, volumes, HEALTHCHECK, entrypoint self-updates yt-dlp | Task 10 |
| §13/§242 compose with Marquee + commented Jellyfin sharing library | Task 11 |
| §13/§241 multi-arch CI → GHCR public | Task 12 |
| §5 exact Jellyfin "Coming Soon" library setup steps | Task 13 (README) |
| §10 config table | Task 13 |
| §15 troubleshooting (bot cookies/proxy, stale yt-dlp, ghost items, NFO overwrite) | Task 13 |
| §7 download format string / MKV documented for users | Task 13 (How it works) |

**Gaps:** none for this plan's scope. (Backend pipeline, TMDB, downloader, reaper, scheduler, and the actual `/api` routes belong to Plans 1–2 and are consumed here, not implemented.)

### 2. Placeholder scan

Searched for `TBD`, `TODO`, `implement later`, "add error handling", "similar to Task N", "write tests for the above". **None present.** Every code step contains complete, runnable code; every config/Docker/CI/docs file is shown in full.

### 3. Type-consistency check against the contract

- `Status` string-literal union matches `models.Status` values verbatim (`queued`/`downloading`/`ready`/`failed`/`expired`).
- `Movie` TS interface fields mirror the `Movie` dataclass (spec §9), with datetimes as ISO strings; **three API-added fields** (`poster_url`, `backdrop_url`, `download_pct`) are flagged below as clarifications.
- `Config` TS interface mirrors `config.Config` field-for-field (types: `count:int→number`, `max_size_gb:float→number`, nullable strings → `string|null`).
- `api.ts` method set maps 1:1 to the contract's `/api` routes; `pinMovie` returns `Movie` (pin toggle response), `updateSettings` returns `Config`.
- Frontend component names match the contract's Frontend section: `MovieCard`, `StatusPill`, `CountdownBadge`, `ActivityLog`, `StatusBar`, `SettingsForm`, pages `DashboardPage`/`SettingsPage`/`ActivityPage`.
- Internal cross-task names are consistent: `posterUrlFor`, `daysUntil`, `MovieCardProps` are each defined once and consumed with the same signature.
- SPA serving is owned by Plan 2's `create_app` (auto-discovers `Path(__file__).resolve().parent / "static"`); the Vite `build.outDir` and the Task 10 Dockerfile static copy both target that same dir (`backend/marquee/api/static`) — consistent end-to-end.

**Contract symbols added/clarified by this plan (for orchestrator reconciliation):**
1. ~~`mount_spa`~~ **Reconciled:** SPA serving is owned by Plan 2's `create_app` (single owner; auto-discovers the packaged `static/` dir, mounts `/assets`, `/api`-safe catch-all). Plan 3 adds **no** `mount_spa`; Task 9 is an integration test over `create_app`.
2. API-added JSON fields on the `Movie` payload beyond the persisted dataclass: `poster_url: str|None` (resolved TMDB w500), `backdrop_url: str|None` (resolved w1280), `download_pct: float|None` (live progress). Plan 2's `GET /api/movies` serializer should populate these.
3. SSE payload schema on `GET /api/activity`: a JSON union `{"type":"log","entry":ActivityEntry}` | `{"type":"progress","tmdb_id":int,"pct":float,"speed":str|None,"eta":str|None}`. Plan 2's `Broadcaster` must emit these tagged shapes.
4. `StatusSummary` JSON for `GET /api/status`: `{next_refresh, next_reap, running, counts:{ready,queued,downloading,failed,expired}, disk:{used_gb,free_gb,total_gb}, ytdlp_version}`.
5. `POST /api/ytdlp/update` returns `{"version": str}`; `POST /api/jellyfin/test` returns `{"ok": bool}`; `GET /api/health` returns `{"status": str}`.
````
