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
    getConnections: vi.fn().mockResolvedValue({ tmdb: "ok", jellyfin: "not_configured" }),
    activityUrl: () => "/api/activity",
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
