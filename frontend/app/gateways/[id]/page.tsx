"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { DeviceSimulator } from "@/components/DeviceSimulator";
import { Timeline } from "@/components/Timeline";

export default function GatewayTimelinePage() {
  const { id } = useParams<{ id: string }>();
  const [rev, setRev] = useState(0);
  const [sensorId, setSensorId] = useState("");
  return (
    <>
      <h1>
        Gateway <span className="mono">{id}</span> · timeline
      </h1>
      <DeviceSimulator gatewayId={id} onSent={() => setRev((r) => r + 1)} onSensorChange={setSensorId} />
      <p className="muted small">Timelines record state changes only; a request that changes nothing adds no entry.</p>
      {/* remount reloads the timelines after each simulated device call */}
      <Timeline key={`g-${rev}`} kind="gateways" id={id} />
      {sensorId && (
        <>
          <h2>
            Sensor <span className="mono">{sensorId}</span> · timeline
          </h2>
          <Timeline key={`s-${sensorId}-${rev}`} kind="sensors" id={sensorId} />
        </>
      )}
    </>
  );
}
