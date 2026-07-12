import { afterEach, expect, test, vi } from "vitest";
import { api } from "./api";
import type { Movie } from "./types";

afterEach(() => {
  vi.restoreAllMocks();
});

function mockFetch(body: unknown, init: Partial<Response> = {}) {
  const res = {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    statusText: init.statusText ?? "OK",
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
  return vi.spyOn(globalThis, "fetch").mockResolvedValue(res);
}

test("getMovies GETs /api/movies and returns parsed JSON", async () => {
  const movies = [{ tmdb_id: 1, title: "X" }] as unknown as Movie[];
  const spy = mockFetch(movies);
  const out = await api.getMovies();
  expect(spy).toHaveBeenCalledWith("/api/movies", expect.objectContaining({}));
  expect(out).toEqual(movies);
});

test("pinMovie POSTs to /api/movies/:id/pin", async () => {
  const spy = mockFetch({ tmdb_id: 7 });
  await api.pinMovie(7);
  expect(spy).toHaveBeenCalledWith(
    "/api/movies/7/pin",
    expect.objectContaining({ method: "POST" }),
  );
});

test("updateSettings PUTs JSON body to /api/settings", async () => {
  const spy = mockFetch({ region: "GB" });
  await api.updateSettings({ region: "GB" } as never);
  const [url, init] = spy.mock.calls[0];
  expect(url).toBe("/api/settings");
  expect((init as RequestInit).method).toBe("PUT");
  expect((init as RequestInit).body).toBe(JSON.stringify({ region: "GB" }));
});

test("throws on non-ok response", async () => {
  mockFetch({ detail: "nope" }, { ok: false, status: 500, statusText: "Server Error" });
  await expect(api.getStatus()).rejects.toThrow(/500/);
});

test("activityUrl returns the SSE endpoint", () => {
  expect(api.activityUrl()).toBe("/api/activity");
});
