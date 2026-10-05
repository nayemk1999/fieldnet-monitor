"use client";

import { useEffect, useState } from "react";
import { ApiError, fetchTimeline, type TimelineEntry } from "@/lib/api";
import { fmt, title } from "@/lib/format";

export function Timeline({ kind, id }: { kind: "gateways" | "sensors"; id: string }) {
  const [entries, setEntries] = useState<TimelineEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      fetchTimeline(kind, id)
        .then((e) => {
          if (!alive) return;
          setEntries(e);
          setError(null);
        })
        .catch((e: ApiError) => alive && setError(e.message));
    load();
    const t = setInterval(load, 5000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [kind, id]);

  if (error) return <p className="error">{error}</p>;
  if (!entries) return <p className="muted">Loading…</p>;
  if (entries.length === 0) return <p className="muted">No entries yet.</p>;

  return (
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>Kind</th>
          <th>Axis</th>
          <th>Change</th>
          <th>Effective at</th>
          <th>Recorded at</th>
          <th>Rule</th>
          <th>Evidence</th>
        </tr>
      </thead>
      <tbody>
        {entries.map((e) => (
          <tr key={e.seq} className={e.kind === "correction" ? "row-correction" : undefined}>
            <td className="mono">{e.seq}</td>
            <td>{title(e.kind)}</td>
            <td>{title(e.axis)}</td>
            <td>
              {e.from ?? "∅"} → {e.to ?? "∅"}
              {e.detail && (
                <details>
                  <summary className="muted">detail</summary>
                  <pre>{JSON.stringify(e.detail, null, 2)}</pre>
                </details>
              )}
            </td>
            <td className="mono">{fmt(e.effective_at)}</td>
            <td className="mono">{fmt(e.recorded_at)}</td>
            <td className="mono small">{e.rule}</td>
            <td className="mono small">{e.evidence_ids.join(", ")}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
