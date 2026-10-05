// Console API client. Shapes mirror docs/console-api.md.

export type GatewayRow = {
  gateway_id: string;
  name: string;
  status: string;
  status_since: string;
  command_state: string;
  coverage_class: string;
  last_heartbeat_at: string | null;
  last_qualifying_at: string | null;
  disconnected_since: string | null;
  flags: string[];
  status_held_seconds: number;
  sensor_count: number;
  suspend_reason: string | null;
};

export type SensorRow = {
  sensor_id: string;
  type: string;
  lifecycle: string;
  lifecycle_reason: string | null;
  lifecycle_since: string;
  collection: string;
  coverage: string;
  quiet_checked_days: number;
  sampling_cycles_done: number;
  next_evaluation_at: string | null;
  gateway_ids: string[];
  paused: boolean;
};

export type TimelineEntry = {
  seq: number;
  kind: string;
  axis: string;
  from: string | null;
  to: string | null;
  effective_at: string;
  recorded_at: string;
  rule: string;
  evidence_ids: string[];
  detail: Record<string, unknown> | null;
};

export type Listing<T> = { now: string; items: T[] };

export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    detail: string,
  ) {
    super(detail);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    let code = "error";
    let detail = res.statusText;
    try {
      const body = await res.json();
      code = body.error ?? code;
      detail = body.detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, code, detail);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export const fetchGateways = (status?: string) =>
  api<Listing<GatewayRow>>(`/api/v1/console/gateways${status ? `?status=${status}` : ""}`);

export const fetchSensors = (lifecycle?: string) =>
  api<Listing<SensorRow>>(`/api/v1/console/sensors${lifecycle ? `?lifecycle=${lifecycle}` : ""}`);

export const fetchTimeline = (kind: "gateways" | "sensors", id: string) =>
  api<TimelineEntry[]>(`/api/v1/${kind}/${encodeURIComponent(id)}/timeline`);

export const gatewayAction = (id: string, action: string, reason?: string) =>
  api<GatewayRow>(`/api/v1/gateways/${encodeURIComponent(id)}/actions`, {
    method: "POST",
    body: JSON.stringify(reason ? { action, reason } : { action }),
  });

export const sensorDecommission = (id: string, reason: string) =>
  api<SensorRow>(`/api/v1/sensors/${encodeURIComponent(id)}/actions`, {
    method: "POST",
    body: JSON.stringify({ action: "decommission", reason }),
  });

export type Summary = { now: string; gateways: Record<string, number>; sensors: Record<string, number> };

export const fetchSummary = () => api<Summary>("/api/v1/console/summary");

export const registerGateway = (gateway_id: string, name: string) =>
  api<{ token: string }>("/api/v1/gateways", { method: "POST", body: JSON.stringify({ gateway_id, name }) });

export const registerSensor = (sensor_id: string, type: string) =>
  api<SensorRow>("/api/v1/sensors", { method: "POST", body: JSON.stringify({ sensor_id, type }) });

export const setCoverage = (sensor_id: string, gateway_ids: string[]) =>
  api<SensorRow>(`/api/v1/sensors/${encodeURIComponent(sensor_id)}/coverage`, {
    method: "PUT",
    body: JSON.stringify({ gateway_ids }),
  });

// Gateway tokens are shown once at registration; the console keeps them in this browser
// so the device simulator can act as the gateway.
// ponytail: localStorage only, so another browser has to paste the token in.
const tokenKey = (gatewayId: string) => `gw-token:${gatewayId}`;

export function saveGatewayToken(gatewayId: string, token: string) {
  try {
    localStorage.setItem(tokenKey(gatewayId), token);
  } catch {
    /* storage blocked: the token can still be pasted into the simulator */
  }
}

export function loadGatewayToken(gatewayId: string): string {
  try {
    return localStorage.getItem(tokenKey(gatewayId)) ?? "";
  } catch {
    return "";
  }
}

/** TEST_MODE only (404 on a live system): re-reads a registered gateway's token. */
export const fetchTestGatewayToken = (gatewayId: string) =>
  api<{ token: string }>(`/test/gateways/${encodeURIComponent(gatewayId)}/token`).then((r) => r.token);

export type RawResponse = { status: number; statusText: string; body: unknown };

/** Like `curl -i`: never throws on HTTP errors, returns status + parsed body for display. */
export async function rawCall(path: string, method: string, token?: string, body?: unknown): Promise<RawResponse> {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  const text = await res.text();
  let parsed: unknown = text;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    /* non-JSON body: show raw text */
  }
  return { status: res.status, statusText: res.statusText, body: parsed };
}
