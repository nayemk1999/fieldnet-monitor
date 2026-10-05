export type Tone = "ok" | "warn" | "bad" | "info" | "muted" | "unknown" | "stopped" | "paused";

export function Badge({ tone, children, title }: { tone: Tone; children: React.ReactNode; title?: string }) {
  return (
    <span className={`badge badge-${tone}`} title={title}>
      {children}
    </span>
  );
}

// Each value gets a tone so that unknown, paused and not-checked never look like zero or healthy.
export const STATUS_TONE: Record<string, Tone> = {
  connected: "ok",
  new: "muted",
  spare: "muted",
  stale: "warn",
  disconnected: "bad",
  suspended: "stopped",
  retired: "muted",
};

export const COMMAND_TONE: Record<string, Tone> = {
  running: "ok",
  stop_pending: "warn",
  stopped: "stopped",
  stop_failed: "bad",
  resume_pending: "warn",
  resume_failed: "bad",
};

export const CLASS_TONE: Record<string, Tone> = {
  available: "ok",
  stopped: "stopped",
  recoverable: "warn",
  dead: "bad",
  none: "bad",
};

export const LIFECYCLE_TONE: Record<string, Tone> = {
  pending: "muted",
  active: "ok",
  dormant: "warn",
  sampling: "info",
  retired: "bad",
  decommissioned: "muted",
};

export const COLLECTION_TONE: Record<string, Tone> = {
  readings: "ok",
  no_readings: "info",
  could_not_read: "bad",
  timed_out: "bad",
  not_checked: "unknown",
  collection_stopped: "stopped",
};
