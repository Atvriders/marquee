import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { ConnectionStatus } from "./ConnectionStatus";
import { api } from "../api";

vi.mock("../api", () => ({
  api: { getConnections: vi.fn(), activityUrl: () => "/api/activity" },
}));

beforeEach(() => {
  vi.clearAllMocks();
});

test("shows TMDB, Jellyfin and Live connection states", async () => {
  (api.getConnections as ReturnType<typeof vi.fn>).mockResolvedValue({
    tmdb: "ok",
    jellyfin: "not_configured",
  });
  render(<ConnectionStatus />);

  await waitFor(() =>
    expect(screen.getByTestId("conn-tmdb").className).toContain("conn-ok"),
  );
  expect(screen.getByTestId("conn-jellyfin").className).toContain("conn-not_configured");
  // jsdom has no EventSource, so the live indicator stays disconnected.
  expect(screen.getByTestId("conn-live").className).toContain("conn-error");
  expect(screen.getByTestId("connection-status")).toBeInTheDocument();
  expect(screen.getByText("TMDB")).toBeInTheDocument();
  expect(screen.getByText("Jellyfin")).toBeInTheDocument();
});

test("renders 'checking' state before the first response resolves", () => {
  (api.getConnections as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}));
  render(<ConnectionStatus />);
  expect(screen.getByTestId("conn-tmdb").className).toContain("conn-unknown");
});
