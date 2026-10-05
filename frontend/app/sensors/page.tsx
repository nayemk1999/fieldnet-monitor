"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ApiError, fetchSensors, sensorDecommission, type SensorRow } from "@/lib/api";
import { fmt, relative, title } from "@/lib/format";
import { Badge, CLASS_TONE, COLLECTION_TONE, LIFECYCLE_TONE } from "@/components/Badge";

const LIFECYCLES = ["pending", "active", "dormant", "sampling", "retired", "decommissioned"];

function NextEvaluation({ s, now }: { s: SensorRow; now: string }) {
  const hasTimer = s.lifecycle === "dormant" || s.lifecycle === "sampling";
  if (!hasTimer)
    return (
      <span className="muted" title="No wait or window runs in this lifecycle">
        —
      </span>
    );
  if (s.next_evaluation_at === null)
    return (
      <Badge tone="paused" title="Coverage is not available; the wait or window is paused">
        paused
      </Badge>
    );
  return (
    <>
      <span className="mono">{fmt(s.next_evaluation_at)}</span>
      <div className="muted small">{relative(s.next_evaluation_at, now)}</div>
    </>
  );
}

export default function SensorsPage() {
  const [data, setData] = useState<{ now: string; items: SensorRow[] } | null>(null);
  const [lifecycle, setLifecycle] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    fetchSensors(lifecycle || undefined)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e: ApiError) => setError(`Could not load sensors: ${e.message}`));
  }, [lifecycle]);

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [load]);

  async function decommission(s: SensorRow) {
    const reason = window.prompt(`Decommission ${s.sensor_id}. Reason (required):`);
    if (reason === null) return;
    if (!reason.trim()) {
      setError("Decommission needs a reason.");
      return;
    }
    try {
      await sensorDecommission(s.sensor_id, reason.trim());
      load();
    } catch (e) {
      setError(`Decommission ${s.sensor_id} failed: ${(e as ApiError).message}`);
    }
  }

  return (
    <>
      <h1>Sensors</h1>
      <div className="toolbar">
        <label>
          Lifecycle{" "}
          <select value={lifecycle} onChange={(e) => setLifecycle(e.target.value)}>
            <option value="">all</option>
            {LIFECYCLES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <span className="spacer" />
        {data && (
          <span className="muted small">
            server clock {fmt(data.now)} · {data.items.length} sensors
          </span>
        )}
      </div>
      {error && <p className="error">{error}</p>}
      <table>
        <thead>
          <tr>
            <th>Sensor</th>
            <th>Lifecycle</th>
            <th>Reason</th>
            <th>Collection</th>
            <th>Coverage</th>
            <th>Next evaluation</th>
            <th>Quiet days</th>
            <th>Sampling cycles</th>
            <th>Gateways</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {data?.items.map((s) => (
            <tr key={s.sensor_id}>
              <td>
                <Link href={`/sensors/${encodeURIComponent(s.sensor_id)}`}>
                  <strong>{s.sensor_id}</strong>
                </Link>
                <div className="muted small">{s.type}</div>
              </td>
              <td>
                <Badge tone={LIFECYCLE_TONE[s.lifecycle] ?? "muted"}>{title(s.lifecycle)}</Badge>
                <div className="muted small">since {fmt(s.lifecycle_since)}</div>
              </td>
              <td>{s.lifecycle_reason ? <span className="mono small">{s.lifecycle_reason}</span> : <span className="muted">—</span>}</td>
              <td>
                <Badge tone={COLLECTION_TONE[s.collection] ?? "unknown"}>{title(s.collection)}</Badge>
              </td>
              <td>
                <Badge tone={CLASS_TONE[s.coverage] ?? "muted"}>{title(s.coverage)}</Badge>
              </td>
              <td>
                <NextEvaluation s={s} now={data.now} />
              </td>
              <td className="count">
                {s.lifecycle === "active" ? (
                  <span>{s.quiet_checked_days}</span>
                ) : (
                  <span className="muted" title="Quiet days only count towards dormancy while active">
                    {s.quiet_checked_days}
                  </span>
                )}
              </td>
              <td className="count">{s.sampling_cycles_done} / 2</td>
              <td className="mono small">{s.gateway_ids.length ? s.gateway_ids.join(", ") : <Badge tone="bad">unassigned</Badge>}</td>
              <td>
                {s.lifecycle !== "decommissioned" && (
                  <button className="danger" onClick={() => decommission(s)}>
                    Decommission
                  </button>
                )}
              </td>
            </tr>
          ))}
          {data && data.items.length === 0 && (
            <tr>
              <td colSpan={10} className="muted">
                No sensors{lifecycle ? ` in lifecycle ${lifecycle}` : ""}.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      <div className="legend">
        <Badge tone="ok">healthy</Badge>
        <Badge tone="info">checked, nothing found</Badge>
        <Badge tone="unknown">not checked / unknown</Badge>
        <Badge tone="paused">paused timer</Badge>
        <Badge tone="stopped">stopped by operator</Badge>
        <Badge tone="bad">problem</Badge>
      </div>
    </>
  );
}
