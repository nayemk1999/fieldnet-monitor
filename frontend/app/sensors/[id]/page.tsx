"use client";

import { useParams } from "next/navigation";
import { Timeline } from "@/components/Timeline";

export default function SensorTimelinePage() {
  const { id } = useParams<{ id: string }>();
  return (
    <>
      <h1>
        Sensor <span className="mono">{id}</span> · timeline
      </h1>
      <Timeline kind="sensors" id={id} />
    </>
  );
}
