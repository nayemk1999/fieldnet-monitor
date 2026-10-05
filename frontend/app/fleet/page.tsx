"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ApiError, fetchGateways, gatewayAction, type GatewayRow } from "@/lib/api";
import { fmt, held, relative, title } from "@/lib/format";
import { Badge, CLASS_TONE, COMMAND_TONE, STATUS_TONE } from "@/components/Badge";

const STATUSES = ["new", "spare", "connected", "stale", "disconnected", "suspended", "retired"];

function allowedActions(g: GatewayRow): string[] {
  if (g.status === "retired") return [];
  const out: string[] = [g.status === "suspended" ? "unsuspend" : "suspend"];
  if (g.status === "new" && g.sensor_count === 0) out.push("mark_spare");
  if (!["stop_pending", "stopped"].includes(g.command_state)) out.push("stop");
  if (g.command_state !== "running") out.push("resume");
  out.push("retire");
  return out;
}

function Evidence({ label, ts, now }: { label: string; ts: string | null; now: string }) {
  return (
    <span>
      <span className="label">{label}</span>
      {ts ? (
        <>
          <span className="mono">{fmt(ts)}</span>
          <div className="muted small">{relative(ts, now)}</div>
        </>
      ) : (
        <Badge tone="unknown">never</Badge>
      )}
    </span>
  );
}

export default function FleetPage() {
  const [data, setData] = useState<{ now: string; items: GatewayRow[] } | null>(null);
  const [status, setStatus] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(() => {
    fetchGateways(status || undefined)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e: ApiError) => setError(`Could not load fleet: ${e.message}`));
  }, [status]);

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [load]);

  async function act(g: GatewayRow, action: string) {
    let reason: string | undefined;
    if (action === "suspend" || action === "retire") {
      const answer = window.prompt(`${title(action)} ${g.gateway_id}. Reason${action === "suspend" ? " (required)" : ""}:`);
      if (answer === null) return;
      if (action === "suspend" && !answer.trim()) {
        setError("Suspend needs a reason.");
        return;
      }
      reason = answer.trim() || undefined;
    }
    setBusy(g.gateway_id);
    try {
      await gatewayAction(g.gateway_id, action, reason);
      setError(null);
      load();
    } catch (e) {
      setError(`${title(action)} ${g.gateway_id} failed: ${(e as ApiError).message}`);
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <h1>Fleet</h1>
      <div className="toolbar">
        <label>
          Status{" "}
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">all</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <span className="spacer" />
        {data && (
          <span className="muted small">
            server clock {fmt(data.now)} · {data.items.length} gateways
          </span>
        )}
      </div>
      {error && <p className="error">{error}</p>}
      <table>
        <thead>
          <tr>
            <th>Gateway</th>
            <th>Status · held</th>
            <th>Evidence</th>
            <th>Command</th>
            <th>Coverage class</th>
            <th>Flags</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {data?.items.map((g) => (
            <tr key={g.gateway_id}>
              <td>
                <Link href={`/gateways/${encodeURIComponent(g.gateway_id)}`}>
                  <strong>{g.gateway_id}</strong>
                </Link>
                <div className="muted small">
                  {g.name} · {g.sensor_count} sensor{g.sensor_count === 1 ? "" : "s"}
                </div>
              </td>
              <td>
                <Badge tone={STATUS_TONE[g.status] ?? "muted"}>{title(g.status)}</Badge>
                <span className="held">· {held(g.status_held_seconds)}</span>
                {g.status === "disconnected" && g.disconnected_since && (
                  <div className="muted small">auth failed since {fmt(g.disconnected_since)}</div>
                )}
                {g.status === "suspended" && g.suspend_reason && <div className="muted small">“{g.suspend_reason}”</div>}
              </td>
              <td>
                <div className="pair">
                  <Evidence label="Last heartbeat" ts={g.last_heartbeat_at} now={data.now} />
                  <Evidence label="Last qualifying" ts={g.last_qualifying_at} now={data.now} />
                </div>
              </td>
              <td>
                <Badge tone={COMMAND_TONE[g.command_state] ?? "muted"}>{title(g.command_state)}</Badge>
              </td>
              <td>
                <Badge tone={CLASS_TONE[g.coverage_class] ?? "muted"}>{title(g.coverage_class)}</Badge>
              </td>
              <td>
                {g.flags.length === 0 ? (
                  <span className="muted">none</span>
                ) : (
                  g.flags.map((f) => (
                    <Badge key={f} tone="bad">
                      {title(f)}
                    </Badge>
                  ))
                )}
              </td>
              <td>
                <div className="actions">
                  {allowedActions(g).map((a) => (
                    <button
                      key={a}
                      className={a === "retire" ? "danger" : undefined}
                      disabled={busy === g.gateway_id}
                      onClick={() => act(g, a)}
                    >
                      {title(a)}
                    </button>
                  ))}
                  {g.status === "retired" && <span className="muted small">terminal</span>}
                </div>
              </td>
            </tr>
          ))}
          {data && data.items.length === 0 && (
            <tr>
              <td colSpan={7} className="muted">
                No gateways{status ? ` with status ${status}` : ""}.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </>
  );
}
