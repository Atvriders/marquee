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
