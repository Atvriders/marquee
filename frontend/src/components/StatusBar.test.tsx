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
