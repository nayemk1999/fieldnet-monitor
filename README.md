# FieldNet Monitor

Server, state engine and operator console for a sensor network whose devices are
unreliable. Django + DRF + PostgreSQL backend, Next.js + TypeScript console,
Python simulator. Design notes are in [DECISIONS.md](DECISIONS.md), tooling notes
in [AI.md](AI.md), the console API in [docs/console-api.md](docs/console-api.md).

## Run everything

```bash
docker compose up --build
```

| Service | URL | Notes |
|---|---|---|
| API (gateway, operator, console, test endpoints) | http://localhost:8000 | gunicorn, 2 workers |
| Console | http://localhost:3000 | Fleet and Sensors pages with situation tiles, register forms, coverage editor, operator actions, timelines |
| Worker | — | background loop; idles when `TEST_MODE=1` |
| Postgres 16 | localhost:5432 inside the compose network | user/db/password `fieldnet` |

Compose starts with `TEST_MODE=1` so `/test/*` exists and the simulator and tests
work out of the box. In that mode background work runs **only** inside
`POST /test/clock` and `POST /test/drain`. For a live system:

```bash
TEST_MODE=0 docker compose up --build
```

Then the `worker` service processes batches and applies due transitions every 2 s.

## Run the tests

```bash
docker compose run --rm api pytest -q
```

33 tests: the pure replay engine against the brief's worked example and its three
variations, every gateway / command / coverage / sensor / batch rule through the
fixed HTTP API with the test clock, one late-data correction, and the console API.
Needs the `db` service (compose starts it). Locally, with Postgres on `localhost`:

```bash
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
createdb fieldnet && .venv/bin/python manage.py migrate
.venv/bin/python -m pytest -q
```

## Run the simulator

```bash
docker compose run --rm api python simulate.py            # all three stories
docker compose run --rm api python simulate.py late_reading_correction
```

Each story resets the server, plays a failure through the fixed gateway API and the
test clock, and ends in assertions. Exit code 0 means every story passed.

| Story | What it plays |
|---|---|
| `stale_gateway_recovers_only_on_fresh_evidence` | goes quiet, turns stale at +12 h effective at the due time, ignores 12.5 h-old late evidence, reconnects on a fresh cycle |
| `ignored_stop_then_collecting_after_stop` | ignores a stop for 10 min (`stop_failed`), acks late (`stopped`), uploads a reading taken inside the stop period (flag), resume clears it |
| `late_reading_correction` | dormant on day 15; on day 20 a batch arrives with a reading from day 9; one `correction` entry, sensor active with 10 quiet days |

Against a server elsewhere: `FIELDNET_URL=http://host:8000 python simulate.py`.

## Local development

```bash
# backend (needs local Postgres; defaults: db fieldnet, user $USER, no password)
cd backend && TEST_MODE=1 .venv/bin/python manage.py runserver 8000
# frontend
cd frontend && npm install && npm run dev        # http://localhost:3000, talks to :8000
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
docs/console-api.md    console API
```
