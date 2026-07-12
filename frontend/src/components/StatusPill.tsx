import type { Status } from "../types";

export function StatusPill({
  status,
  pct,
}: {
  status: Status;
  pct?: number | null;
}) {
  let label: string;
  switch (status) {
    case "queued":
      label = "queued";
      break;
    case "downloading":
      label = pct != null ? `downloading ${Math.round(pct)}%` : "downloading";
      break;
    case "ready":
      label = "ready";
      break;
    case "failed":
      label = "failed";
      break;
    case "expired":
      label = "expired";
      break;
    default:
      label = status;
  }
  return (
    <span className={`status-pill status-${status}`} data-testid="status-pill">
      {label}
    </span>
  );
}
