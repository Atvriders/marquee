import { useEffect, useState } from "react";
import { api } from "../api";
import type { ActivityEntry, ActivityMessage } from "../types";

interface Progress {
  pct: number;
  speed: number | null;
  eta: number | null;
}

export function ActivityLog() {
  const [entries, setEntries] = useState<ActivityEntry[]>([]);
  const [progress, setProgress] = useState<Record<number, Progress>>({});

  useEffect(() => {
    const es = new EventSource(api.activityUrl());
    es.onmessage = (e) => {
      let msg: ActivityMessage;
      try {
        msg = JSON.parse(e.data) as ActivityMessage;
      } catch {
        return;
      }
      if (msg.type === "log") {
        setEntries((prev) => [msg.entry, ...prev].slice(0, 500));
      } else if (msg.type === "progress") {
        setProgress((prev) => ({
          ...prev,
          [msg.tmdb_id]: { pct: msg.pct, speed: msg.speed, eta: msg.eta },
        }));
      }
    };
    return () => es.close();
  }, []);

  const active = Object.entries(progress).filter(([, p]) => p.pct < 100);

  return (
    <section className="activity">
      {active.length > 0 && (
        <div className="activity-progress">
          {active.map(([id, p]) => (
            <div key={id} className="activity-progress-row">
              <span className="activity-progress-id">#{id}</span>
              <progress data-testid={`progress-${id}`} max={100} value={p.pct} />
              <span className="activity-progress-pct">{Math.round(p.pct)}%</span>
              {p.speed && <span className="activity-progress-speed">{p.speed}</span>}
              {p.eta && <span className="activity-progress-eta">ETA {p.eta}</span>}
            </div>
          ))}
        </div>
      )}

      <ul className="activity-log">
        {entries.map((en, i) => (
          <li key={en.id ?? `live-${en.ts}-${i}`} className={`activity-line level-${en.level}`}>
            <time>{new Date(en.ts).toLocaleTimeString()}</time>
            <span className="activity-event">{en.event}</span>
            <span className="activity-message">{en.message}</span>
          </li>
        ))}
      </ul>
      {entries.length === 0 && active.length === 0 && (
        <p className="activity-empty">Waiting for activity…</p>
      )}
    </section>
  );
}
