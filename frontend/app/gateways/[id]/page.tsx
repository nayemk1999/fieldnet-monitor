"use client";

import { useParams } from "next/navigation";
import { Timeline } from "@/components/Timeline";

export default function GatewayTimelinePage() {
  const { id } = useParams<{ id: string }>();
  return (
    <>
      <h1>
        Gateway <span className="mono">{id}</span> · timeline
      </h1>
      <Timeline kind="gateways" id={id} />
    </>
  );
}
