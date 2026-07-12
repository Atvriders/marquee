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
