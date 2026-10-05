"use client";

import { useState } from "react";
import { ApiError, registerSensor } from "@/lib/api";

const TYPES = ["temperature", "rain", "wind"];

export function RegisterSensor({ onDone, onError }: { onDone: () => void; onError: (msg: string) => void }) {
  const [open, setOpen] = useState(false);
  const [id, setId] = useState("");
  const [type, setType] = useState(TYPES[0]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const sensorId = id.trim();
    if (!sensorId) return onError("Sensor id is required.");
    try {
      await registerSensor(sensorId, type);
      setId("");
      setOpen(false);
      onDone();
    } catch (err) {
      onError(`Register ${sensorId} failed: ${(err as ApiError).message}`);
    }
  }

  if (!open) return <button onClick={() => setOpen(true)}>Register sensor</button>;
  return (
    <form className="form-row" onSubmit={submit}>
      <input placeholder="sensor id" value={id} onChange={(e) => setId(e.target.value)} autoFocus />
      <select value={type} onChange={(e) => setType(e.target.value)}>
        {TYPES.map((t) => (
          <option key={t} value={t}>
            {t}
          </option>
        ))}
      </select>
      <button type="submit">Register</button>
      <button type="button" onClick={() => setOpen(false)}>
        Cancel
      </button>
    </form>
  );
}
