export function daysUntil(iso: string | null, now: Date = new Date()): number | null {
  if (!iso) return null;
  const target = new Date(iso);
  if (Number.isNaN(target.getTime())) return null;
  const ms = target.getTime() - now.getTime();
  return Math.ceil(ms / (1000 * 60 * 60 * 24));
}

// SIGNATURE: the streaming countdown rendered as a lit marquee readout.
// The visible text is split into decorative parts so the day count can glow
// like an incandescent theater sign, but the concatenated text content is
// preserved exactly ("streams in 42d" / "streams today" / "streaming now" /
// "date TBA") — tests assert on those substrings.
export function CountdownBadge({
  digitalDate,
  now,
}: {
  digitalDate: string | null;
  now?: Date;
}) {
  const d = daysUntil(digitalDate, now ?? new Date());

  // Imminent titles (<= 7 days) warm the glow toward ticket-red: "gone soon".
  const soon = d !== null && d > 0 && d <= 7;
  const state = d === null ? "tba" : d > 0 ? "counting" : d === 0 ? "today" : "now";

  return (
    <span
      className="countdown-badge"
      data-testid="countdown-badge"
      data-state={state}
      data-soon={soon ? "true" : undefined}
    >
      {d !== null && d > 0 ? (
        <>
          <span className="cd-lead">streams in </span>
          <span className="cd-num">{d}</span>
          <span className="cd-unit">d</span>
        </>
      ) : (
        <span className="cd-text">
          {d === null ? "date TBA" : d === 0 ? "streams today" : "streaming now"}
        </span>
      )}
    </span>
  );
}
