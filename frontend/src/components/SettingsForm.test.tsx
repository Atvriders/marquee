import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, vi } from "vitest";
import { SettingsForm } from "./SettingsForm";
import { api } from "../api";
import type { Config } from "../types";

vi.mock("../api", () => ({
  api: {
    getSettings: vi.fn(),
    updateSettings: vi.fn(),
    testJellyfin: vi.fn(),
    runNow: vi.fn(),
  },
}));

const cfg: Config = {
  tmdb_token: "tok",
  sources: ["upcoming", "now_playing"],
  count: 50,
  region: "US",
  language: "en-US",
  container: "mkv",
  max_height: 1080,
  refresh_cron: "0 3 * * *",
  reaper_cron: "0 4 * * *",
  grace_days: 0,
  tz: "UTC",
  library_dir: "/library",
  config_dir: "/config",
  max_size_gb: 0,
  jellyfin_url: null,
  jellyfin_api_key: null,
  jellyfin_user: null,
  jellyfin_pass: null,
  ytdlp_cookies: null,
  ytdlp_proxy: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  (api.getSettings as ReturnType<typeof vi.fn>).mockResolvedValue(cfg);
  (api.updateSettings as ReturnType<typeof vi.fn>).mockResolvedValue(cfg);
});

test("loads settings and round-trips an edit on save", async () => {
  render(<SettingsForm />);
  const region = (await screen.findByLabelText("region")) as HTMLInputElement;
  expect(region.value).toBe("US");
  await userEvent.clear(region);
  await userEvent.type(region, "GB");
  await userEvent.click(screen.getByRole("button", { name: /save/i }));
  await waitFor(() => expect(api.updateSettings).toHaveBeenCalled());
  const sent = (api.updateSettings as ReturnType<typeof vi.fn>).mock.calls[0][0] as Config;
  expect(sent.region).toBe("GB");
  expect(sent.sources).toEqual(["upcoming", "now_playing"]);
});

test("sources round-trip through comma text", async () => {
  render(<SettingsForm />);
  const sources = (await screen.findByLabelText("sources")) as HTMLInputElement;
  await userEvent.clear(sources);
  await userEvent.type(sources, "upcoming, popular");
  await userEvent.click(screen.getByRole("button", { name: /save/i }));
  const sent = (api.updateSettings as ReturnType<typeof vi.fn>).mock.calls[0][0] as Config;
  expect(sent.sources).toEqual(["upcoming", "popular"]);
});

test("Test Jellyfin button fires testJellyfin", async () => {
  (api.testJellyfin as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true });
  render(<SettingsForm />);
  await screen.findByLabelText("region");
  await userEvent.click(screen.getByRole("button", { name: /test jellyfin/i }));
  expect(api.testJellyfin).toHaveBeenCalled();
});

test("Run now button fires runNow", async () => {
  (api.runNow as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
  render(<SettingsForm />);
  await screen.findByLabelText("region");
  await userEvent.click(screen.getByRole("button", { name: /run now/i }));
  expect(api.runNow).toHaveBeenCalled();
});
