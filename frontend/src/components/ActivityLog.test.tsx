import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";
import { ActivityLog } from "./ActivityLog";

class MockEventSource {
  static instances: MockEventSource[] = [];
  url: string;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  readyState = 0;
  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }
  close() {
    this.readyState = 2;
  }
  emit(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent);
  }
}

beforeEach(() => {
  MockEventSource.instances = [];
  vi.stubGlobal("EventSource", MockEventSource as unknown as typeof EventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("connects to the SSE activity endpoint", () => {
  render(<ActivityLog />);
  expect(MockEventSource.instances[0].url).toBe("/api/activity");
});

test("appends log entries as they arrive", () => {
  render(<ActivityLog />);
  const es = MockEventSource.instances[0];
  act(() => {
    es.emit({
      type: "log",
      entry: { id: 1, ts: "2026-07-11T00:00:00Z", level: "info", event: "download", tmdb_id: 5, message: "Downloaded Dune" },
    });
  });
  expect(screen.getByText("Downloaded Dune")).toBeInTheDocument();
});

test("renders a progress bar for active downloads", () => {
  render(<ActivityLog />);
  const es = MockEventSource.instances[0];
  act(() => {
    es.emit({ type: "progress", tmdb_id: 5, pct: 62, speed: 3251200, eta: 10 });
  });
  const bar = screen.getByTestId("progress-5");
  expect(bar).toHaveAttribute("value", "62");
  expect(screen.getByText(/62%/)).toBeInTheDocument();
});

test("closes the connection on unmount", () => {
  const { unmount } = render(<ActivityLog />);
  const es = MockEventSource.instances[0];
  unmount();
  expect(es.readyState).toBe(2);
});
