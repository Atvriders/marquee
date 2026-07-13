import { useEffect, useState } from "react";
import { api } from "../api";
import type { Connections } from "../types";

function label(state: string): string {
  switch (state) {
    case "ok":
      return "connected";
    case "unauthorized":
      return "bad token";
    case "not_configured":
      return "not set up";
    case "error":
      return "unreachable";
    default:
      return "checking…";
  }
}

/**
 * Header indicator showing whether Marquee can reach its external services:
 * TMDB, Jellyfin, and the live activity stream (SSE). Polls /api/connections
 * every 30s; the "Live" dot reflects the EventSource connection state.
 */
export function ConnectionStatus() {
  const [conn, setConn] = useState<Connections | null>(null);
  const [live, setLive] = useState(false);

  useEffect(() => {
    let alive = true;
    const poll = () =>
      api
        .getConnections()
        .then((c) => {
          if (alive) setConn(c);
        })
        .catch(() => {});
    poll();
    const t = setInterval(poll, 30000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  useEffect(() => {
    if (typeof EventSource === "undefined") return;
    const es = new EventSource(api.activityUrl());
    es.onopen = () => setLive(true);
    es.onerror = () => setLive(false);
    return () => es.close();
  }, []);

  const dot = (key: string, name: string, state: string) => (
    <span
      className={`conn-dot conn-${state}`}
      data-testid={`conn-${key}`}
      title={`${name}: ${label(state)}`}
    >
      <span className="conn-led" aria-hidden="true" />
      {name}
    </span>
  );

  return (
    <div
      className="conn-status"
      data-testid="connection-status"
      role="status"
      aria-label="Service connections"
    >
      {dot("tmdb", "TMDB", conn?.tmdb ?? "unknown")}
      {dot("jellyfin", "Jellyfin", conn?.jellyfin ?? "unknown")}
      {dot("live", "Live", live ? "ok" : "error")}
    </div>
  );
}
