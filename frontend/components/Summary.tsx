"use client";

import { useEffect, useState } from "react";
import { fetchSummary, type Summary as SummaryData } from "@/lib/api";
import { title } from "@/lib/format";
import { LIFECYCLE_TONE, STATUS_TONE } from "@/components/Badge";

const ORDER = {
  gateways: ["connected", "stale", "disconnected", "suspended", "new", "spare", "retired"],
  sensors: ["active", "dormant", "sampling", "retired", "pending", "decommissioned"],
};

/** Situation counts as clickable tiles. Clicking a tile filters the table below; clicking again clears. */
export function Summary({
  kind,
  selected,
  onSelect,
  refreshKey,
}: {
  kind: "gateways" | "sensors";
  selected: string;
  onSelect: (value: string) => void;
  refreshKey: unknown;
}) {
  const [data, setData] = useState<SummaryData | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () => fetchSummary().then((d) => alive && setData(d)).catch(() => undefined);
    load();
    const t = setInterval(load, 5000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [refreshKey]);

  const tones = kind === "gateways" ? STATUS_TONE : LIFECYCLE_TONE;
  return (
    <div className="tiles">
      {ORDER[kind].map((key) => (
        <button
          key={key}
          className={`tile ${selected === key ? "tile-active" : ""}`}
          onClick={() => onSelect(selected === key ? "" : key)}
          title={`Show only ${key}`}
        >
          <span className={`tile-count badge-${tones[key] ?? "muted"}`}>{data ? data[kind][key] ?? 0 : "…"}</span>
          <span className="tile-label">{title(key)}</span>
        </button>
      ))}
    </div>
  );
}
