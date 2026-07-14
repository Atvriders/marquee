import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, test, vi } from "vitest";
import { WatchdogBanner } from "./WatchdogBanner";
import { api } from "../api";

vi.mock("../api", () => ({
  api: { getWatchdog: vi.fn() },
}));

beforeEach(() => {
  vi.clearAllMocks();
});

function renderBanner() {
  return render(
    <MemoryRouter>
      <WatchdogBanner />
    </MemoryRouter>,
  );
}

test("renders a banner with a Settings link when a check is failing", async () => {
  (api.getWatchdog as ReturnType<typeof vi.fn>).mockResolvedValue({
    ok: false,
    checked_at: "2026-07-13T00:00:00Z",
    checks: [
      { id: "jellyfin_reachable", label: "Jellyfin reachable", status: "ok", detail: "fine" },
      { id: "library_found", label: "Library found", status: "fail", detail: "missing" },
      { id: "items_visible", label: "Items visible", status: "fail", detail: "none visible" },
    ],
  });
  renderBanner();

  const banner = await screen.findByTestId("watchdog-banner");
  expect(banner).toHaveTextContent("2 checks failing");
  const link = screen.getByRole("link", { name: /settings/i });
  expect(link).toHaveAttribute("href", "/settings");
});

test("renders nothing when all checks pass", async () => {
  (api.getWatchdog as ReturnType<typeof vi.fn>).mockResolvedValue({
    ok: true,
    checked_at: "2026-07-13T00:00:00Z",
    checks: [{ id: "jellyfin_reachable", label: "Jellyfin reachable", status: "ok", detail: "fine" }],
  });
  renderBanner();

  await waitFor(() => expect(api.getWatchdog).toHaveBeenCalled());
  expect(screen.queryByTestId("watchdog-banner")).not.toBeInTheDocument();
});

test("renders nothing on error (e.g. watchdog not configured)", async () => {
  (api.getWatchdog as ReturnType<typeof vi.fn>).mockRejectedValue(
    new Error("503 Service Unavailable: not configured"),
  );
  renderBanner();

  await waitFor(() => expect(api.getWatchdog).toHaveBeenCalled());
  expect(screen.queryByTestId("watchdog-banner")).not.toBeInTheDocument();
});
