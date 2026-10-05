export function held(seconds: number): string {
  if (seconds < 60) return "<1m";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return h > 0 ? `${d}d ${h}h` : `${d}d`;
  if (h > 0) return m > 0 ? `${h}h ${m}m` : `${h}h`;
  return `${m}m`;
}

/** "2026-01-15T00:00:00Z" -> "2026-01-15 00:00Z" */
export function fmt(ts: string | null | undefined): string {
  if (!ts) return "—";
  return ts.slice(0, 16).replace("T", " ") + "Z";
}

export function relative(ts: string | null, now: string): string {
  if (!ts) return "";
  const diff = (new Date(ts).getTime() - new Date(now).getTime()) / 1000;
  const text = held(Math.abs(diff));
  return diff >= 0 ? `in ${text}` : `${text} ago`;
}

export function title(s: string | null | undefined): string {
  if (!s) return "";
  return s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}
