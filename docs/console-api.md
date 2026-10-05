# Console API

Read-only list endpoints shaped for the two console pages, plus a summary. They sit
beside the fixed state API under `/api/v1/console/`. All times are ISO 8601 UTC. Each
listing carries the **server clock** as `now` so the UI computes "held for" and
"in 3d 2h" against the clock the rules used, which matters in `TEST_MODE`.

Errors use the shared envelope `{"error": "<code>", "detail": "<text>"}`.

Operator actions reuse the fixed endpoints: `POST /api/v1/gateways/{id}/actions`
and `POST /api/v1/sensors/{id}/actions`. Timelines reuse `GET /api/v1/{gateways|sensors}/{id}/timeline`.

## GET /api/v1/console/gateways

Query: `status` (optional, comma separated: `stale,disconnected`).

```json
{
  "now": "2026-01-15T00:00:00Z",
  "items": [
    {
      "gateway_id": "G", "name": "North ridge",
      "status": "disconnected", "status_since": "2026-01-14T22:00:00Z",
      "status_held_seconds": 7200,
      "command_state": "running", "coverage_class": "recoverable",
      "last_heartbeat_at": "2026-01-14T23:58:00Z",
      "last_qualifying_at": "2026-01-14T12:00:00Z",
      "disconnected_since": "2026-01-14T22:00:00Z",
      "flags": [],
      "sensor_count": 2,
      "suspend_reason": null
    }
  ]
}
```

Everything from `GET /api/v1/gateways/{id}` plus:

| Field | Meaning |
|---|---|
| `status_held_seconds` | `now - status_since`, for "Disconnected · 2h" |
| `sensor_count` | sensors this gateway covers (drives whether `mark_spare` is offered) |
| `suspend_reason` | operator text while suspended, else null |

Sorted by `gateway_id`. No pagination (documented compromise).

## GET /api/v1/console/sensors

Query: `lifecycle` and `coverage` (optional, comma separated).

```json
{
  "now": "2026-01-15T00:00:00Z",
  "items": [
    {
      "sensor_id": "S", "type": "temperature",
      "lifecycle": "sampling", "lifecycle_reason": null,
      "lifecycle_since": "2026-01-30T00:00:00Z",
      "collection": "not_checked", "coverage": "recoverable",
      "quiet_checked_days": 14, "sampling_cycles_done": 0,
      "next_evaluation_at": null,
      "gateway_ids": ["G"],
      "paused": true
    }
  ]
}
```

Everything from `GET /api/v1/sensors/{id}` plus:

| Field | Meaning |
|---|---|
| `gateway_ids` | covering gateways |
| `paused` | true when a dormant wait or sampling window exists but coverage is not available (`next_evaluation_at` is null for that reason, not because there is no timer) |

The UI renders three different things for the "next evaluation" column: a timestamp, a
striped **paused** badge (`paused: true`), and a muted dash when the lifecycle has no
timer at all. `collection: not_checked` renders as a dashed "unknown" badge, distinct
from `no_readings` (checked, nothing found) and from `readings`.

## GET /api/v1/console/summary

```json
{
  "now": "...",
  "gateways": {"new": 0, "spare": 0, "connected": 3, "stale": 1, "disconnected": 0, "suspended": 0, "retired": 0},
  "sensors": {"pending": 0, "active": 5, "dormant": 1, "sampling": 0, "retired": 0, "decommissioned": 0}
}
```

Situation counts. The console renders them as clickable tiles above each table; every value is present, zero included.

## Writes the console makes

All through the fixed operator API: `POST /api/v1/gateways` (register, the token is shown once),
`POST /api/v1/sensors`, `PUT /api/v1/sensors/{id}/coverage` (the coverage editor offers every
non-retired gateway), `POST /api/v1/gateways/{id}/actions`, `POST /api/v1/sensors/{id}/actions`.
