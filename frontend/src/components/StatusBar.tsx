import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { StatusSummary } from "../types";

function fmt(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

export function StatusBar() {
  const [status, setStatus] = useState<StatusSummary | null>(null);
  const [updating, setUpdating] = useState(false);

  const reload = useCallback(() => {
    api.getStatus().then(setStatus).catch(() => undefined);
  }, []);

  useEffect(() => {
    reload();
    const t = setInterval(reload, 10000);
    return () => clearInterval(t);
  }, [reload]);

  const onUpdate = async () => {
    setUpdating(true);
    try {
      await api.updateYtdlp();
      reload();
    } finally {
      setUpdating(false);
    }
  };

  if (!status) return <div className="status-bar" data-testid="status-bar" />;

  return (
    <div className="status-bar" data-testid="status-bar">
      <span className="sb-item">
        <b>{status.counts.ready}</b> ready
      </span>
      <span className="sb-item">{status.counts.queued} queued</span>
      <span className="sb-item">{status.counts.downloading} downloading</span>
      <span className="sb-item">{status.counts.failed} failed</span>
      <span className="sb-item">Next refresh: {fmt(status.next_refresh)}</span>
      <span className="sb-item">Next reap: {fmt(status.next_reap)}</span>
      <span className="sb-item">{status.disk.free_gb.toFixed(1)} GB free</span>
      <span className="sb-item">
        yt-dlp {status.ytdlp_version}
        <button type="button" onClick={onUpdate} disabled={updating}>
          {updating ? "Updating…" : "Update yt-dlp"}
        </button>
      </span>
    </div>
  );
}
