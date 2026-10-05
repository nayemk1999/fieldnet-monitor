# FieldNet Monitor

Server, state engine and operator console for a sensor network whose devices are
unreliable. Django + DRF + PostgreSQL backend, Next.js + TypeScript console,
Python simulator. Design notes are in [DECISIONS.md](DECISIONS.md), tooling notes
in [AI.md](AI.md), the console API in [docs/console-api.md](docs/console-api.md).

- [Run everything](#run-everything)
- [Testing at a glance](#testing-at-a-glance)
- [1. Automated tests (pytest)](#1-automated-tests-pytest)
- [2. Simulator stories (terminal)](#2-simulator-stories-terminal)
- [3. Manual API testing with curl](#3-manual-api-testing-with-curl)
- [4. UI testing (console)](#4-ui-testing-console)
- [API reference](#api-reference)
- [Local development](#local-development)
- [Layout](#layout)

## Run everything

```bash
docker compose up --build
```

| Service | URL | Notes |
|---|---|---|
| API (gateway, operator, console, test endpoints) | http://localhost:8000 | gunicorn, 2 workers |
| Console | http://localhost:3000 | Fleet and Sensors pages, register forms, coverage editor, operator actions, device simulator, timelines |
| Worker | — | background loop; idles when `TEST_MODE=1` |
| Postgres 16 | localhost:5432 inside the compose network | user/db/password `fieldnet` |

Compose starts with `TEST_MODE=1` so `/test/*` exists and the simulator and tests
work out of the box. In that mode time comes from a **test clock** stored in the DB,
and background work runs **only** inside `POST /test/clock` and `POST /test/drain`.
For a live system:

```bash
TEST_MODE=0 docker compose up --build
```

Then the `worker` service processes batches and applies due transitions every 2 s,
and `/test/*` returns 404.

## Testing at a glance

| What | Command | Needs |
|---|---|---|
| Unit + API tests | `docker compose run --rm api pytest -q` | `db` service |
| Simulator stories | `docker compose run --rm api python simulate.py` | running `api` |
| Manual API calls | `curl` against http://localhost:8000 (see below) | running `api`, `TEST_MODE=1` |
| UI walkthrough | open http://localhost:3000 | full compose stack |

## 1. Automated tests (pytest)

```bash
docker compose run --rm api pytest -q                      # all 34 tests
docker compose run --rm api pytest -q tests/test_batches.py
docker compose run --rm api pytest -q -k stale             # by name
docker compose run --rm api pytest -q -x -vv               # stop on first failure, verbose
```

| File | Tests | Covers |
|---|---|---|
| `test_lifecycle_replay.py` | 9 | pure replay engine vs. the brief's worked example and its three variations (no DB) |
| `test_gateway_rules.py` | 7 | connected / stale / disconnected, auth failures, fresh vs. late evidence |
| `test_batches.py` | 5 | batch intake, idempotency, quarantine, retry with backoff (`/test/faults`) |
| `test_sensor_lifecycle_api.py` | 4 | pending → active → dormant → sampling → retired through HTTP, late-data correction |
| `test_commands.py` | 3 | stop / resume, timeout → `stop_failed`, late ack, readings inside a stop period |
| `test_coverage.py` | 3 | sensor coverage = best class among covering gateways |
| `test_console_api.py` | 3 | console listings, `paused` flag, test-mode token endpoint |

All API tests go through `tests/harness.py`, which drives the real HTTP endpoints
and the test clock (the simulator reuses it).

Locally, with Postgres on `localhost`:

```bash
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
createdb fieldnet && .venv/bin/python manage.py migrate
TEST_MODE=1 .venv/bin/python -m pytest -q
```

## 2. Simulator stories (terminal)

```bash
docker compose run --rm api python simulate.py                            # all three stories
docker compose run --rm api python simulate.py late_reading_correction    # one story
```

Each story **resets the server**, plays a failure through the fixed gateway API and
the test clock, and ends in assertions. Exit code 0 means every story passed.

| Story | What it plays |
|---|---|
| `stale_gateway_recovers_only_on_fresh_evidence` | goes quiet, turns stale at +12 h effective at the due time, ignores 12.5 h-old late evidence, reconnects on a fresh cycle |
| `ignored_stop_then_collecting_after_stop` | ignores a stop for 10 min (`stop_failed`), acks late (`stopped`), uploads a reading taken inside the stop period (flag), resume clears it |
| `late_reading_correction` | dormant on day 15; on day 20 a batch arrives with a reading from day 9; one `correction` entry, sensor active with 10 quiet days |

Against a server elsewhere: `FIELDNET_URL=http://host:8000 python simulate.py`.
After a run, open the console to inspect the resulting gateways, sensors and timelines.

## 3. Manual API testing with curl

A full scenario from an empty server. Requires `TEST_MODE=1` (the compose default).
Device timestamps (`sent_at`, `finished_at`, `acked_at`) must be close to the server
clock, so set the clock first and use times near it.

```bash
API=http://localhost:8000
J='Content-Type: application/json'

# 0. start clean and pin the test clock
curl -X POST $API/test/reset                                                   # 204
curl -X POST $API/test/clock -H "$J" -d '{"now":"2026-01-01T00:00:00Z"}'      # {"now": ...}

# 1. register a gateway (token is returned ONCE) and a sensor
TOKEN=$(curl -s -X POST $API/api/v1/gateways -H "$J" \
  -d '{"gateway_id":"G1","name":"North ridge"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -X POST $API/api/v1/sensors -H "$J" -d '{"sensor_id":"S1","type":"temperature"}'

# 2. G1 covers S1
curl -X PUT $API/api/v1/sensors/S1/coverage -H "$J" -d '{"gateway_ids":["G1"]}'

# 3. act as the device (Bearer token)
AUTH="Authorization: Bearer $TOKEN"
curl -X POST $API/gw/v1/heartbeat -H "$J" -H "$AUTH" \
  -d '{"sent_at":"2026-01-01T00:00:00Z","session":"ok"}'                       # 204

curl -X POST $API/gw/v1/cycles -H "$J" -H "$AUTH" -d '{
  "cycle_id":"c1","started_at":"2026-01-01T00:00:00Z","finished_at":"2026-01-01T00:00:00Z",
  "session":"ok",
  "results":[{"sensor_id":"S1","outcome":"readings","batch_id":"b1"}]
}'                                                                             # 202 {"ignored": []}

curl -X PUT $API/gw/v1/batches/b1 -H "$J" -H "$AUTH" -d '{
  "sensor_id":"S1",
  "readings":[{"reading_id":"r1","taken_at":"2026-01-01T00:00:00Z","value":20.5,"unit":"C"}]
}'                                                                             # 202

# 4. process the batch (test mode has no worker) and inspect state
curl -X POST $API/test/drain
curl $API/api/v1/batches/b1          # processing, attempts, accepted_count, quarantined[]
curl $API/api/v1/gateways/G1
curl $API/api/v1/sensors/S1
curl $API/api/v1/sensors/S1/timeline

# 5. operator stop -> device polls and acks
curl -X POST $API/api/v1/gateways/G1/actions -H "$J" -d '{"action":"stop"}'
CMD=$(curl -s $API/gw/v1/commands -H "$AUTH" | python3 -c 'import sys,json;print(json.load(sys.stdin)["commands"][0]["command_id"])')
curl -X POST $API/gw/v1/commands/$CMD/ack -H "$J" -H "$AUTH" -d '{"acked_at":"2026-01-01T00:00:00Z"}'   # 204

# 6. let time pass: +13 h with no evidence -> G1 turns stale
curl -X POST $API/test/clock -H "$J" -d '{"now":"2026-01-01T13:00:00Z"}'
curl "$API/api/v1/console/gateways?status=stale"
curl $API/api/v1/console/summary
```

Useful failure probes:

```bash
curl -X POST $API/gw/v1/heartbeat -H "$J" -H "Authorization: Bearer wrong" -d '{}'                    # 401
curl -X POST $API/gw/v1/heartbeat -H "$J" -H "$AUTH" -d '{"session":"nope"}'                         # 422
curl -X POST $API/test/clock -H "$J" -d '{"now":"2025-01-01T00:00:00Z"}'                             # 409 clock_backwards
curl -X POST $API/test/faults -H "$J" -d '{"processing_failures":2}'   # next 2 batch processing attempts fail, then retry with backoff
```

Error bodies always use `{"error": "<code>", "detail": "<text>"}`.

## 4. UI testing (console)

Open http://localhost:3000 (redirects to `/fleet`). With `TEST_MODE=1` you can test
the whole flow in the browser, no terminal needed.

| Page | Path | What to check |
|---|---|---|
| Fleet | `/fleet` | situation tiles (click to filter by status), gateway table, register-gateway form, operator actions (suspend / unsuspend / stop / resume / mark spare / retire) |
| Sensors | `/sensors` | lifecycle tiles, register-sensor form, coverage editor, decommission, "next evaluation" column (timestamp / striped **paused** / dash) |
| Gateway detail | `/gateways/{id}` | **device simulator** + gateway timeline + timeline of the selected sensor |
| Sensor detail | `/sensors/{id}` | sensor timeline |

Walkthrough:

1. **Fleet → Register gateway** `G1`. The token is shown once and saved in this
   browser (in `TEST_MODE` the simulator can also re-fetch it via `/test/gateways/{id}/token`).
2. **Sensors → Register sensor** `S1` (temperature), then use the **coverage editor**
   to assign `G1`. G1's `sensor_count` on Fleet becomes 1.
3. Open **`/gateways/G1`**. The device simulator acts as the gateway:
   - **Heartbeat** — `POST /gw/v1/heartbeat` with `session: ok | auth_failed`
   - **Cycle** — `POST /gw/v1/cycles` for the selected sensor and outcome
     (`no_readings`, `readings`, `could_not_read`, `timeout`)
   - **Batch** — `PUT /gw/v1/batches/{id}` with a reading (the unit is picked from
     the sensor type; a wrong unit is quarantined)
   - **Commands / Ack** — polls `GET /gw/v1/commands` and acks the pending command
   - **Drain** — `POST /test/drain`, runs due jobs at the current test clock
   - **Clock +1h / +12h / +1d / +14d** — `POST /test/clock`, moves time forward and runs everything that becomes due

   Every call is logged with its request and raw response (status + body), and the
   timelines below reload after each call.
4. Scenarios to try:
   - *Stale gateway:* Heartbeat, then **+12h** twice → G1 becomes `stale`; send a
     Cycle → back to `connected`.
   - *Stop command:* on Fleet click **stop** on G1; in the simulator click
     **Commands / Ack** → command state `stopped`; **resume** clears it.
   - *Sensor lifecycle:* a `readings` Cycle + Batch + Drain → S1 `active`; then
     `no_readings` cycles and **+14d** steps → `dormant` → `sampling`.
   - *Paused timer:* with S1 dormant, send a heartbeat with `session: auth_failed`
     → Sensors shows the striped **paused** badge.
5. Timelines record **state changes only**; a request that changes nothing adds no entry.

To start over, `curl -X POST localhost:8000/test/reset` (or run a simulator story)
and refresh the browser. On a live system (`TEST_MODE=0`) the clock buttons and
token re-fetch are unavailable; paste the token shown at registration.

## API reference

Base URL `http://localhost:8000`. JSON in and out, times ISO 8601 UTC.
Status codes: `201` created, `202` accepted, `204` no content, `401` bad token,
`404` unknown id, `409` conflict, `422` invalid body.

### Gateway API (devices) — `Authorization: Bearer <token>`

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/gw/v1/heartbeat` | `{"sent_at", "session": "ok"\|"auth_failed"}` | 204 |
| POST | `/gw/v1/cycles` | `{"cycle_id", "started_at", "finished_at", "session", "results": [{"sensor_id", "outcome", "batch_id"?}]}` | 202 `{"ignored": [sensor_ids not covered]}`; same body again → 200; different body same id → 409 |
| PUT | `/gw/v1/batches/{batch_id}` | `{"sensor_id", "readings": [{"reading_id", "taken_at", "value", "unit"}]}` | 202 `{"batch_id", "sensor_id"}` |
| GET | `/gw/v1/commands` | — | `{"commands": [{"command_id", "seq", "type", "issued_at"}]}` (latest unacked only) |
| POST | `/gw/v1/commands/{command_id}/ack` | `{"acked_at"}` | 204 |

`batch_id` is required when `outcome` is `readings` and must be absent otherwise.
Bad readings (wrong unit, bad fields) are quarantined, not rejected with 422.

### Operator and state API

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/api/v1/gateways` | `{"gateway_id", "name"}` | 201 `{"token"}` (shown once) |
| GET | `/api/v1/gateways/{id}` | — | gateway state |
| POST | `/api/v1/gateways/{id}/actions` | `{"action": "suspend"\|"unsuspend"\|"mark_spare"\|"retire"\|"stop"\|"resume", "reason"?}` | gateway state (`reason` required for `suspend`) |
| GET | `/api/v1/gateways/{id}/timeline` | — | list of timeline entries |
| POST | `/api/v1/sensors` | `{"sensor_id", "type": "temperature"\|"rain"\|"wind"}` | 201 sensor state |
| GET | `/api/v1/sensors/{id}` | — | sensor state |
| PUT | `/api/v1/sensors/{id}/coverage` | `{"gateway_ids": [...]}` | sensor state (replaces the set; retired gateways → 409) |
| POST | `/api/v1/sensors/{id}/actions` | `{"action": "decommission", "reason"}` | sensor state |
| GET | `/api/v1/sensors/{id}/timeline` | — | list of timeline entries |
| GET | `/api/v1/batches/{id}` | — | `{"processing", "attempts", "accepted_count", "quarantined": [{"reading_id", "reason"}]}` |

Example gateway state:

```json
{
  "gateway_id": "G1", "name": "North ridge",
  "status": "connected", "status_since": "2026-01-01T00:00:00Z",
  "command_state": "running", "coverage_class": "available",
  "last_heartbeat_at": "2026-01-01T00:00:00Z",
  "last_qualifying_at": "2026-01-01T00:00:00Z",
  "disconnected_since": null, "flags": []
}
```

### Console API (read-only)

| Method | Path | Query |
|---|---|---|
| GET | `/api/v1/console/gateways` | `status=stale,disconnected` |
| GET | `/api/v1/console/sensors` | `lifecycle=...`, `coverage=...` |
| GET | `/api/v1/console/summary` | — |

Response shapes and field meanings: [docs/console-api.md](docs/console-api.md).

### Test API (`TEST_MODE=1` only, 404 otherwise)

| Method | Path | Body | Effect |
|---|---|---|---|
| POST | `/test/reset` | — | 204, wipes all data and the test clock |
| POST | `/test/clock` | `{"now"}` | sets the clock (forward only, else 409) and runs every due job |
| POST | `/test/drain` | — | runs due jobs at the current clock |
| POST | `/test/faults` | `{"processing_failures": n}` | next `n` batch processing attempts fail |
| GET | `/test/gateways/{id}/token` | — | `{"gateway_id", "token"}`, used by the console's device simulator |

## Local development

```bash
# backend (needs local Postgres; defaults: db fieldnet, user $USER, no password)
cd backend && TEST_MODE=1 .venv/bin/python manage.py runserver 8000
# frontend
cd frontend && npm install && npm run dev        # http://localhost:3000, talks to :8000
# simulator against the local backend
cd backend && FIELDNET_URL=http://localhost:8000 .venv/bin/python simulate.py
```

Environment variables (backend): `DB_HOST DB_PORT DB_NAME DB_USER DB_PASSWORD`,
`TEST_MODE`, `DEBUG`, `SECRET_KEY`, `WORKER_POLL_SECONDS`, and the thresholds
`QUIET_DAYS_BEFORE_DORMANT DORMANT_WAIT_DAYS SAMPLING_WINDOW_HOURS
SAMPLING_CYCLES_BEFORE_RETIRED STALE_AFTER_HOURS COMMAND_TIMEOUT_MINUTES
BATCH_DEADLINE_HOURS`. Frontend: `NEXT_PUBLIC_API_URL` (build-time).

## Layout

```
backend/
  core/clock.py        the only place time is read (DB-backed in TEST_MODE)
  core/gateways.py     gateway status, command state, coverage class, stop periods
  core/coverage.py     sensor coverage = best class among covering gateways
  core/lifecycle.py    pure sensor lifecycle replay (no DB)
  core/sensors.py      replay inputs, history diff -> transitions or one correction, collection
  core/batches.py      batch intake, validation, quarantine, retry with backoff
  core/jobs.py         run_due(now): due batches and timers in due-time order, then sensors
  core/engine.py       request order: update gateway -> recompute coverage -> apply evidence
  core/api/            gw.py (devices), ops.py (operator/state), console.py, testing.py
  tests/               pytest; tests/harness.py is also used by simulate.py
  simulate.py          gateway simulator CLI
frontend/              Next.js 15 app router, no component library
  components/DeviceSimulator.tsx   acts as a gateway from the browser (gateway detail page)
docs/console-api.md    console API
```
