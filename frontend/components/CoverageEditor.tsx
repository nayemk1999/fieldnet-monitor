"use client";

import { useState } from "react";
import { ApiError, setCoverage, type GatewayRow, type SensorRow } from "@/lib/api";
import { Badge } from "@/components/Badge";

/** Shows the covering gateways; "Edit" opens a checkbox list of every non-retired gateway. */
export function CoverageEditor({
  sensor,
  gateways,
  onDone,
  onError,
}: {
  sensor: SensorRow;
  gateways: GatewayRow[];
  onDone: () => void;
  onError: (msg: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<string[]>(sensor.gateway_ids);
  const [saving, setSaving] = useState(false);
  const editable = sensor.lifecycle !== "decommissioned";

  function toggle(id: string) {
    setSelected((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]));
  }

  async function save() {
    setSaving(true);
    try {
      await setCoverage(sensor.sensor_id, selected);
      setOpen(false);
      onDone();
    } catch (err) {
      onError(`Coverage for ${sensor.sensor_id} failed: ${(err as ApiError).message}`);
    } finally {
      setSaving(false);
    }
  }

  if (!open) {
    return (
      <div className="actions">
        <span className="mono small">
          {sensor.gateway_ids.length ? sensor.gateway_ids.join(", ") : <Badge tone="bad">unassigned</Badge>}
        </span>
        {editable && (
          <button
            onClick={() => {
              setSelected(sensor.gateway_ids);
              setOpen(true);
            }}
          >
            Edit
          </button>
        )}
      </div>
    );
  }

  const candidates = gateways.filter((g) => g.status !== "retired");
  return (
    <div className="checks">
      {candidates.length === 0 && <span className="muted small">No gateways registered.</span>}
      {candidates.map((g) => (
        <label key={g.gateway_id} className="small">
          <input type="checkbox" checked={selected.includes(g.gateway_id)} onChange={() => toggle(g.gateway_id)} />{" "}
          <span className="mono">{g.gateway_id}</span> <span className="muted">({g.status})</span>
        </label>
      ))}
      <div className="actions">
        <button onClick={save} disabled={saving}>
          Save
        </button>
        <button onClick={() => setOpen(false)} disabled={saving}>
          Cancel
        </button>
      </div>
    </div>
  );
}
