"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  fetchGateways,
  fetchSensors,
  fetchSummary,
  fetchTestGatewayToken,
  loadGatewayToken,
  rawCall,
  saveGatewayToken,
  type GatewayRow,
  type RawResponse,
  type SensorRow,
} from "@/lib/api";

// mirrors CYCLE_OUTCOMES in backend/core/models.py
const OUTCOMES = ["no_readings", "readings", "could_not_read", "timeout"] as const;
type Outcome = (typeof OUTCOMES)[number];

// mirrors UNITS_BY_SENSOR_TYPE in backend/core/config.py; a wrong unit quarantines the reading
const UNITS: Record<string, string> = { temperature: "C", rain: "mm", wind: "m/s" };

const HOUR = 3_600_000;
// test clock only moves forward; each step also runs every job that becomes due
const CLOCK_STEPS = [
  ["+1h", HOUR],
  ["+12h", 12 * HOUR],
  ["+1d", 24 * HOUR],
  ["+14d", 14 * 24 * HOUR],
] as const;

type LogEntry = { label: string; request: string; response: RawResponse | { error: string } };

/** Acts as the gateway device: sends heartbeat / cycle / batch with the gateway's own token. */
export function DeviceSimulator({
  gatewayId,
  onSent,
  onSensorChange,
}: {
  gatewayId: string;
  onSent: () => void;
  onSensorChange: (sensorId: string) => void;
}) {
  const [token, setToken] = useState("");
  const router = useRouter();
  const [gateways, setGateways] = useState<GatewayRow[]>([]);
  const [sensors, setSensors] = useState<SensorRow[]>([]);
  const [sensorId, setSensorId] = useState("");
  const [value, setValue] = useState("25.3");
  const [lastBatch, setLastBatch] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<Outcome>("no_readings");
  const [session, setSession] = useState<"ok" | "auth_failed">("ok");
  const [clockNow, setClockNow] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [log, setLog] = useState<LogEntry[]>([]);

  useEffect(() => {
    const saved = loadGatewayToken(gatewayId);
    setToken(saved);
    if (saved) return;
    // no token in this browser: TEST_MODE can re-show it; on a live system it stays paste-only
    fetchTestGatewayToken(gatewayId)
      .then((t) => {
        saveGatewayToken(gatewayId, t);
        setToken(t);
      })
      .catch(() => {});
  }, [gatewayId]);

  useEffect(() => {
    Promise.all([fetchGateways(), fetchSensors()])
      .then(([g, s]) => {
        setGateways(g.items.filter((x) => x.status !== "retired"));
        const live = s.items.filter((x) => x.lifecycle !== "decommissioned");
        // covered sensors first: those are the ones this gateway's cycles and batches count for
        const covered = (x: SensorRow) => x.gateway_ids.includes(gatewayId);
        const sorted = [...live.filter(covered), ...live.filter((x) => !covered(x))];
        setSensors(sorted);
        setSensorId((cur) => cur || sorted.find(covered)?.sensor_id || "");
      })
      .catch((err) => setLog((cur) => [{ label: "Load lists", request: "GET console", response: { error: (err as Error).message } }, ...cur]));
  }, [gatewayId]);

  // Device time must agree with the server clock (which may be a test clock), so $NOW comes from the API.
  useEffect(() => onSensorChange(sensorId), [sensorId, onSensorChange]);

  const serverNow = async () => {
    const now = (await fetchSummary()).now;
    setClockNow(now);
    return now;
  };

  useEffect(() => {
    serverNow().catch(() => {});
  }, []);
  const uid = () => Date.now().toString(36);

  async function run(label: string, method: string, path: string, build?: (now: string) => unknown, auth = true) {
    setBusy(true);
    const request = `${method} ${path}`;
    try {
      const body = build ? build(await serverNow()) : undefined;
      const response = await rawCall(path, method, auth ? token.trim() : undefined, body);
      setLog((cur) => [{ label, request, response }, ...cur]);
      onSent();
      return response;
    } catch (err) {
      setLog((cur) => [{ label, request, response: { error: (err as Error).message } }, ...cur]);
    } finally {
      setBusy(false);
    }
  }

  const heartbeat = () =>
    run("Heartbeat", "POST", "/gw/v1/heartbeat", (now) => ({ sent_at: now, session }));

  const cycle = () =>
    run("Cycle", "POST", "/gw/v1/cycles", (now) => ({
      cycle_id: `c-${uid()}`,
      started_at: now,
      finished_at: now,
      session,
      // "readings" must point at the batch that carried them: the last one sent with button 3
      results: [
        outcome === "readings"
          ? { sensor_id: sensorId.trim(), outcome, batch_id: lastBatch }
          : { sensor_id: sensorId.trim(), outcome },
      ],
    }));

  async function batch() {
    const batchId = `b-${uid()}`;
    const res = await run("Batch", "PUT", `/gw/v1/batches/${batchId}`, (now) => ({
      sensor_id: sensorId.trim(),
      readings: [{ reading_id: `r-${uid()}`, taken_at: now, value: Number(value), unit: unit }],
    }));
    if (res && res.status < 300) setLastBatch(batchId);
  }

  // a real device polls for its latest unacked command, carries it out, then acks it
  async function ackCommand() {
    const res = await run("Commands", "GET", "/gw/v1/commands");
    const cmd = (res?.body as { commands?: { command_id: string }[] } | undefined)?.commands?.[0];
    if (cmd) await run("Ack", "POST", `/gw/v1/commands/${cmd.command_id}/ack`, (now) => ({ acked_at: now }));
  }

  async function drainAndCheck() {
    await run("Drain", "POST", "/test/drain", undefined, false);
    if (lastBatch) await run("Batch status", "GET", `/api/v1/batches/${lastBatch}`, undefined, false);
  }

  const unit = UNITS[sensors.find((x) => x.sensor_id === sensorId)?.type ?? ""] ?? "C";
  async function advanceClock(label: string, ms: number) {
    const res = await run(`Clock ${label}`, "POST", "/test/clock", (now) => ({
      now: new Date(Date.parse(now) + ms).toISOString(),
    }), false);
    if (res && res.status < 300) setClockNow((res.body as { now: string }).now);
  }

  const noToken = !token.trim();
  const noSensor = !sensorId.trim();

  return (
    <section className="sim">
      <h2>Device simulator</h2>
      <div className="form-row">
        <select
          value={gatewayId}
          onChange={(e) => router.push(`/gateways/${encodeURIComponent(e.target.value)}`)}
          aria-label="gateway"
        >
          {!gateways.some((g) => g.gateway_id === gatewayId) && <option value={gatewayId}>{gatewayId}</option>}
          {gateways.map((g) => (
            <option key={g.gateway_id} value={g.gateway_id}>
              {g.gateway_id} ({g.status})
            </option>
          ))}
        </select>
        <select value={sensorId} onChange={(e) => setSensorId(e.target.value)} aria-label="sensor">
          <option value="">— sensor —</option>
          {sensors.map((s) => (
            <option key={s.sensor_id} value={s.sensor_id}>
              {s.sensor_id} · {s.type}
              {s.gateway_ids.includes(gatewayId) ? "" : " (not covered: will be ignored)"}
            </option>
          ))}
        </select>
        <input
          className="mono sim-token"
          placeholder="gateway token (saved at registration, or paste)"
          value={token}
          onChange={(e) => {
            setToken(e.target.value);
            saveGatewayToken(gatewayId, e.target.value.trim());
          }}
        />
        <input type="number" step="any" placeholder={`value (${unit})`} title={`unit: ${unit}`} value={value} onChange={(e) => setValue(e.target.value)} />
      </div>
      <div className="actions sim-buttons">
        <button onClick={heartbeat} disabled={busy || noToken}>
          1 · Heartbeat
        </button>
        <span className="actions">
          <button onClick={cycle} disabled={busy || noToken || noSensor || (outcome === "readings" && !lastBatch)}>
            2 · Cycle
          </button>
          <select value={outcome} onChange={(e) => setOutcome(e.target.value as Outcome)} aria-label="cycle outcome">
            {OUTCOMES.map((o) => (
              <option key={o} value={o} disabled={o === "readings" && !lastBatch}>
                {o === "readings" ? `readings${lastBatch ? ` (${lastBatch})` : " (send a batch first)"}` : o}
              </option>
            ))}
          </select>
        </span>
        <button onClick={batch} disabled={busy || noToken || noSensor || value === ""}>
          3 · Batch reading
        </button>
        <button onClick={drainAndCheck} disabled={busy}>
          4 · Drain{lastBatch ? ` + check ${lastBatch}` : ""}
        </button>
        <button onClick={ackCommand} disabled={busy || noToken}>
          5 · Ack command
        </button>
        <select value={session} onChange={(e) => setSession(e.target.value as "ok" | "auth_failed")} aria-label="session">
          <option value="ok">session: ok</option>
          <option value="auth_failed">session: auth_failed</option>
        </select>
        {log.length > 0 && <button onClick={() => setLog([])}>Clear log</button>}
      </div>
      <div className="actions sim-clock small">
        <span>
          Server clock <span className="mono">{clockNow ?? "…"}</span>
        </span>
        {CLOCK_STEPS.map(([label, ms]) => (
          <button key={label} onClick={() => advanceClock(label, ms)} disabled={busy}>
            {label}
          </button>
        ))}
      </div>
      {noToken && <p className="muted small">No token for this gateway (not saved here and TEST_MODE is off). Paste the one shown at registration.</p>}
      <div className="sim-log">
        {log.map((e, i) => (
          <div key={log.length - i} className="sim-entry">
            <div className="small">
              <strong>{e.label}</strong> <span className="mono muted">{e.request}</span>{" "}
              {"error" in e.response ? (
                <span className="badge badge-bad">network error</span>
              ) : (
                <span className={`badge ${e.response.status < 300 ? "badge-ok" : "badge-bad"}`}>
                  {e.response.status} {e.response.statusText}
                </span>
              )}
            </div>
            <pre className="mono small">
              {"error" in e.response ? e.response.error : JSON.stringify(e.response.body, null, 2) ?? "(no body)"}
            </pre>
          </div>
        ))}
      </div>
    </section>
  );
}
