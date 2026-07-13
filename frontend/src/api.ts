import type { Config, Connections, Movie, StatusSummary } from "./types";

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
  getConnections: () => req<Connections>("/connections"),
  getHealth: () => req<{ status: string }>("/health"),
  updateYtdlp: () => req<{ version: string }>("/ytdlp/update", { method: "POST" }),
  testJellyfin: () => req<{ ok: boolean }>("/jellyfin/test", { method: "POST" }),
  activityUrl: () => `${BASE}/activity`,
};
