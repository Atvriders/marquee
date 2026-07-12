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
  const initial = movie.title.trim().charAt(0).toUpperCase() || "?";

  return (
    <article className={`movie-card${movie.pinned ? " is-pinned" : ""}`}>
      <div className="movie-card-poster">
        {poster ? (
          <img src={poster} alt={`${movie.title} poster`} loading="lazy" />
        ) : (
          <div className="movie-card-poster--empty" aria-hidden="true">
            <span className="poster-initial">{initial}</span>
          </div>
        )}
        <button
          type="button"
          className={`pin-toggle${movie.pinned ? " active" : ""}`}
          aria-label={movie.pinned ? "Unpin" : "Pin"}
          aria-pressed={movie.pinned}
          onClick={() => onPin(movie.tmdb_id)}
        >
          {movie.pinned ? "★" : "☆"}
        </button>
        <div className="movie-card-badges">
          <StatusPill status={movie.status} pct={movie.download_pct} />
        </div>
      </div>

      <div className="movie-card-body">
        <h3 className="movie-card-title">{movie.title}</h3>
        <div className="movie-card-meta">
          {movie.year != null && <span className="movie-card-year">{movie.year}</span>}
          {movie.certification && <span className="movie-card-cert">{movie.certification}</span>}
        </div>

        <div className="movie-card-countdown">
          <CountdownBadge digitalDate={movie.digital_date} now={now} />
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
                onClick={() => {
                  setMenuOpen(false);
                  onDownload(movie.tmdb_id);
                }}
              >
                Download
              </button>
              <button
                type="button"
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
