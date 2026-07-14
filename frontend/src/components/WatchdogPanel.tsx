import { useEffect, useState } from "react";
import { api } from "../api";
import type { WatchdogResult } from "../types";

function fmt(iso: string): string {
  return new Date(iso).toLocaleString();
}

function isNotConfigured(err: unknown): boolean {
  return err instanceof Error && err.message.startsWith("503");
}

const STATUS_ICON: Record<string, string> = {
  ok: "●",
  warn: "▲",
  fail: "✕",
  skip: "–",
};

/**
 * Jellyfin watchdog panel — shows the last persisted end-to-end health check
 * (jellyfin reachable → library found → items visible → cinema plugin →
 * trailer extras → cinema mode plays trailers → playback evidence) with a
 * manual "Verify now" re-run.
 */
export function WatchdogPanel() {
  const [result, setResult] = useState<WatchdogResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notConfigured, setNotConfigured] = useState(false);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    let alive = true;
    api
      .getWatchdog()
      .then((r) => {
        if (!alive) return;
        setResult(r);
      })
      .catch((err) => {
        if (!alive) return;
        if (isNotConfigured(err)) setNotConfigured(true);
        else setError(String(err));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const verifyNow = async () => {
    setRunning(true);
    setError(null);
    try {
      const r = await api.runWatchdog();
      setResult(r);
      setNotConfigured(false);
    } catch (err) {
      if (isNotConfigured(err)) setNotConfigured(true);
      else setError(String(err));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="wd-panel" data-testid="watchdog-panel">
      <div className="wd-panel-header">
        <button type="button" onClick={verifyNow} disabled={running}>
          {running ? "Checking…" : "Verify now"}
        </button>
        {result && <span className="wd-time">Last checked: {fmt(result.checked_at)}</span>}
      </div>

      {loading && <p className="wd-status">Loading…</p>}

      {!loading && notConfigured && (
        <p className="wd-status wd-not-configured">
          Jellyfin isn't configured. Add your Jellyfin URL and credentials in Settings to enable
          watchdog checks.
        </p>
      )}

      {!loading && !notConfigured && error && <p className="wd-status wd-error">{error}</p>}

      {!loading && !notConfigured && !error && result && result.checks.length === 0 && (
        <p className="wd-status wd-empty">No checks have run yet.</p>
      )}

      {!loading && !notConfigured && !error && result && result.checks.length > 0 && (
        <ul className="wd-rows">
          {result.checks.map((check) => (
            <li
              key={check.id}
              className={`wd-row wd-${check.status}`}
              data-testid={`wd-${check.id}`}
            >
              <span className="wd-icon" aria-hidden="true">
                {STATUS_ICON[check.status] ?? "?"}
              </span>
              <div className="wd-row-body">
                <span className="wd-label">{check.label}</span>
                <span className="wd-detail">{check.detail}</span>
                {(check.status === "fail" || check.status === "warn") && check.hint && (
                  <span className="wd-hint">{check.hint}</span>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
