import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";

const POLL_MS = 60000;

/**
 * Header banner that surfaces a Jellyfin watchdog failure impossible to miss.
 * Polls GET /api/watchdog (the last persisted result — cheap, no re-run) on
 * mount and every 60s. Renders nothing when the watchdog isn't configured,
 * errors, or every check is passing.
 */
export function WatchdogBanner() {
  const [failCount, setFailCount] = useState(0);

  useEffect(() => {
    let alive = true;
    const poll = () =>
      api
        .getWatchdog()
        .then((r) => {
          if (!alive) return;
          setFailCount(r.checks.filter((c) => c.status === "fail").length);
        })
        .catch(() => {
          if (alive) setFailCount(0);
        });
    poll();
    const t = setInterval(poll, POLL_MS);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  if (failCount === 0) return null;

  return (
    <div className="wd-banner" data-testid="watchdog-banner" role="alert">
      <span>
        Jellyfin watchdog: {failCount} check{failCount === 1 ? "" : "s"} failing.
      </span>
      <Link to="/settings">Review in Settings</Link>
    </div>
  );
}
