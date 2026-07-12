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
  // Live download progress (tmdb_id -> pct) merged from the SSE stream so cards
  // show "downloading NN%". Keyed by tmdb_id to match movies.
  const [progress, setProgress] = useState<Record<number, number>>({});

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

  // Subscribe to live download progress. Guarded because jsdom (tests) has no
  // EventSource; a download reaching 100% or a full reload clears it.
  useEffect(() => {
    if (typeof EventSource === "undefined") return;
    const es = new EventSource(api.activityUrl());
    es.onmessage = (e) => {
      let msg: { type: string; tmdb_id?: number; pct?: number };
      try {
        msg = JSON.parse(e.data);
      } catch {
        return;
      }
      if (msg.type === "progress" && typeof msg.tmdb_id === "number") {
        setProgress((prev) => ({ ...prev, [msg.tmdb_id as number]: msg.pct ?? 0 }));
      }
    };
    return () => es.close();
  }, []);

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

      {loading && <p className="dashboard-status">Dimming the lights…</p>}
      {error && <p className="dashboard-error">{error}</p>}
      {!loading && !error && shown.length === 0 && (
        <p className="dashboard-status dashboard-empty">
          No coming attractions yet. Run a refresh from Settings to pull the latest trailers.
        </p>
      )}

      <div className="poster-grid">
        {shown.map((m) => (
          <MovieCard
            key={m.tmdb_id}
            movie={
              progress[m.tmdb_id] != null ? { ...m, download_pct: progress[m.tmdb_id] } : m
            }
            onPin={onPin}
            onDownload={onDownload}
            onDelete={onDelete}
          />
        ))}
      </div>
    </section>
  );
}
