import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import { WatchdogPanel } from "./WatchdogPanel";
import { api } from "../api";
import type { WatchdogResult } from "../types";

vi.mock("../api", () => ({
  api: { getWatchdog: vi.fn(), runWatchdog: vi.fn() },
}));

const result: WatchdogResult = {
  ok: false,
  checked_at: "2026-07-12T03:00:00Z",
  checks: [
    {
      id: "jellyfin_reachable",
      label: "Jellyfin reachable",
      status: "ok",
      detail: "Responded in 12ms",
    },
    {
      id: "library_found",
      label: "Library found",
      status: "warn",
      detail: "Library has few items",
      hint: "Add more trailers to the library",
    },
    {
      id: "cinema_mode_plays_trailers",
      label: "Cinema mode plays trailers",
      status: "fail",
      detail: "No trailer played during last cinema session",
      hint: "Check the Cinema Mode plugin configuration",
    },
    {
      id: "playback_evidence",
      label: "Playback evidence",
      status: "skip",
      detail: "Skipped: previous check failed",
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
});

test("renders ok, warn and fail rows, and shows the hint on failing/warning checks", async () => {
  (api.getWatchdog as ReturnType<typeof vi.fn>).mockResolvedValue(result);
  render(<WatchdogPanel />);

  expect(await screen.findByTestId("wd-jellyfin_reachable")).toHaveClass("wd-ok");
  expect(screen.getByTestId("wd-library_found")).toHaveClass("wd-warn");
  expect(screen.getByTestId("wd-cinema_mode_plays_trailers")).toHaveClass("wd-fail");
  expect(screen.getByTestId("wd-playback_evidence")).toHaveClass("wd-skip");

  expect(screen.getByText("Add more trailers to the library")).toBeInTheDocument();
  expect(screen.getByText("Check the Cinema Mode plugin configuration")).toBeInTheDocument();

  expect(screen.getByText(/Last checked:/)).toBeInTheDocument();
  expect(screen.getByTestId("watchdog-panel")).toBeInTheDocument();
});

test("does not show a hint for an ok check even if hint is present", async () => {
  (api.getWatchdog as ReturnType<typeof vi.fn>).mockResolvedValue({
    ok: true,
    checked_at: "2026-07-12T03:00:00Z",
    checks: [
      { id: "jellyfin_reachable", label: "Jellyfin reachable", status: "ok", detail: "fine", hint: "unused" },
    ],
  });
  render(<WatchdogPanel />);
  await screen.findByTestId("wd-jellyfin_reachable");
  expect(screen.queryByText("unused")).not.toBeInTheDocument();
});

test("Verify now calls api.runWatchdog and replaces the result", async () => {
  (api.getWatchdog as ReturnType<typeof vi.fn>).mockResolvedValue(result);
  (api.runWatchdog as ReturnType<typeof vi.fn>).mockResolvedValue({
    ok: true,
    checked_at: "2026-07-13T09:00:00Z",
    checks: [
      { id: "jellyfin_reachable", label: "Jellyfin reachable", status: "ok", detail: "Responded in 8ms" },
    ],
  });
  render(<WatchdogPanel />);
  await screen.findByTestId("wd-jellyfin_reachable");

  const btn = screen.getByRole("button", { name: /verify now/i });
  await userEvent.click(btn);

  expect(api.runWatchdog).toHaveBeenCalled();
  await waitFor(() => expect(screen.getByText("Responded in 8ms")).toBeInTheDocument());
  expect(screen.queryByTestId("wd-cinema_mode_plays_trailers")).not.toBeInTheDocument();
});

test("shows 'Checking…' and disables the button while running", async () => {
  (api.getWatchdog as ReturnType<typeof vi.fn>).mockResolvedValue(result);
  let resolveRun: (v: WatchdogResult) => void = () => {};
  (api.runWatchdog as ReturnType<typeof vi.fn>).mockReturnValue(
    new Promise((resolve) => {
      resolveRun = resolve;
    }),
  );
  render(<WatchdogPanel />);
  await screen.findByTestId("wd-jellyfin_reachable");

  await userEvent.click(screen.getByRole("button", { name: /verify now/i }));
  const btn = screen.getByRole("button", { name: /checking/i });
  expect(btn).toBeDisabled();

  resolveRun(result);
  await waitFor(() => expect(screen.getByRole("button", { name: /verify now/i })).toBeEnabled());
});

test("renders a friendly message on a 503 'not configured' response", async () => {
  (api.getWatchdog as ReturnType<typeof vi.fn>).mockRejectedValue(
    new Error("503 Service Unavailable: watchdog not configured"),
  );
  render(<WatchdogPanel />);
  expect(await screen.findByText(/jellyfin isn't configured/i)).toBeInTheDocument();
});

test("renders a generic error state for other failures", async () => {
  (api.getWatchdog as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("500 boom"));
  render(<WatchdogPanel />);
  expect(await screen.findByText(/500 boom/)).toBeInTheDocument();
});

test("renders an empty state when checks is []", async () => {
  (api.getWatchdog as ReturnType<typeof vi.fn>).mockResolvedValue({
    ok: true,
    checked_at: "2026-07-12T03:00:00Z",
    checks: [],
  });
  render(<WatchdogPanel />);
  expect(await screen.findByText(/no checks have run yet/i)).toBeInTheDocument();
});
