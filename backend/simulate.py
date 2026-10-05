"""Gateway simulator: plays failure stories through the fixed API and the test clock.

    python simulate.py            # all stories
    python simulate.py late_reading_correction

Needs a server started with TEST_MODE=1. FIELDNET_URL defaults to http://localhost:8000.
Reuses the test harness (tests/harness.py) over a tiny requests adapter.
"""
import os
import sys

import requests

from tests.harness import Harness, day, iso


class HttpClient:
    """Makes requests look like Django's APIClient, which the harness expects."""

    def __init__(self, base: str):
        self.base, self.s = base.rstrip("/"), requests.Session()

    def _req(self, method, path, data=None, **kw):
        headers = {"Authorization": kw["HTTP_AUTHORIZATION"]} if "HTTP_AUTHORIZATION" in kw else {}
        return self.s.request(method, self.base + path, json=data, headers=headers, timeout=60)

    def get(self, path, **kw):
        return self._req("GET", path, **kw)

    def post(self, path, data=None, format=None, **kw):
        return self._req("POST", path, data, **kw)

    def put(self, path, data=None, format=None, **kw):
        return self._req("PUT", path, data, **kw)


# --- stories -------------------------------------------------------------------


def stale_gateway_recovers_only_on_fresh_evidence(h: Harness):
    """A gateway goes quiet, turns stale at exactly +12h, ignores old late evidence, recovers on fresh."""
    h.clock(day(0))
    h.gateway("G", "North ridge")
    h.sensor("S", "temperature")
    h.cover("S", ["G"])
    h.cycle("G", "c0", day(0), [{"sensor_id": "S", "outcome": "no_readings"}])
    assert h.gw("G")["status"] == "connected"
    h.clock(day(0, 13))
    g = h.gw("G")
    assert g["status"] == "stale", g
    assert g["status_since"] == iso(day(0, 12)), "stale is effective at the due time, not the clock jump"
    assert h.s("S")["coverage"] == "recoverable" and h.s("S")["collection"] == "not_checked"
    h.cycle("G", "late", day(0, 0, 30), [{"sensor_id": "S", "outcome": "no_readings"}])
    assert h.gw("G")["status"] == "stale", "12.5h-old evidence must not reconnect a stale gateway"
    h.cycle("G", "fresh", day(0, 13), [{"sensor_id": "S", "outcome": "no_readings"}])
    g = h.gw("G")
    assert g["status"] == "connected" and g["last_qualifying_at"] == iso(day(0, 13)), g
    assert h.s("S")["coverage"] == "available" and h.s("S")["collection"] == "no_readings"
    return "stale at +12h (effective at due time), old evidence ignored, fresh cycle reconnects"


def ignored_stop_then_collecting_after_stop(h: Harness):
    """The gateway ignores a stop for 10 minutes, acks late, then keeps uploading readings."""
    h.clock(day(0))
    h.gateway("G", "River bend")
    h.sensor("S", "rain")
    h.cover("S", ["G"])
    h.cycle("G", "c0", day(0), [{"sensor_id": "S", "outcome": "no_readings"}])
    h.action("G", "stop")
    stop = h.commands("G")[0]
    h.clock(day(0, 0, 11))
    g = h.gw("G")
    assert g["command_state"] == "stop_failed" and g["coverage_class"] == "available", g
    h.ack("G", stop["command_id"], day(0, 0, 10))
    g = h.gw("G")
    assert g["command_state"] == "stopped" and g["coverage_class"] == "stopped", g
    s = h.s("S")
    assert s["coverage"] == "stopped" and s["collection"] == "collection_stopped", s
    h.clock(day(0, 1))
    h.batch("G", "b1", "S", [h.reading("r1", day(0, 0, 30), value=1.5, unit="mm")])
    h.drain()
    g = h.gw("G")
    assert g["flags"] == ["collecting_after_stop"], g
    assert h.s("S")["lifecycle"] == "active", "readings are facts even from a stopped gateway"
    h.action("G", "resume")
    h.ack("G", h.commands("G")[0]["command_id"], day(0, 1))
    g = h.gw("G")
    assert g["flags"] == [] and g["command_state"] == "running", g
    return "stop_failed at +10m, late ack -> stopped, reading inside stop period raised the flag, resume cleared it"


def late_reading_correction(h: Harness):
    """A sensor goes dormant on day 15; on day 20 a batch arrives with a reading taken on day 9."""
    h.setup_pair()
    h.daily_no_readings("G", "S", range(1, 15))
    h.keepalive("G", 15)
    s = h.s("S")
    assert s["lifecycle"] == "dormant" and s["lifecycle_since"] == iso(day(15)), s
    h.clock(day(15, 12))
    h.cycle("G", "c15", day(15, 12), [{"sensor_id": "S", "outcome": "no_readings"}])
    h.daily_no_readings("G", "S", range(16, 20))
    h.clock(day(20))
    h.batch("G", "b9", "S", [h.reading("r9", day(9, 12))])
    h.drain()
    s = h.s("S")
    assert s["lifecycle"] == "active" and s["quiet_checked_days"] == 10, s
    entries = h.timeline("sensors", "S")
    corrections = [e for e in entries if e["kind"] == "correction"]
    assert len(corrections) == 1 and (corrections[0]["from"], corrections[0]["to"]) == ("dormant", "active")
    assert corrections[0]["evidence_ids"] == ["b9"]
    assert any(e["kind"] == "transition" and e["to"] == "dormant" for e in entries), "earlier entries are never edited"
    return "dormant on day 15; day-9 reading arriving on day 20 -> one correction entry, active with 10 quiet days"


STORIES = {f.__name__: f for f in (stale_gateway_recovers_only_on_fresh_evidence, ignored_stop_then_collecting_after_stop, late_reading_correction)}


def main(argv):
    base = os.environ.get("FIELDNET_URL", "http://localhost:8000")
    names = argv[1:] or list(STORIES)
    failed = 0
    for name in names:
        story = STORIES.get(name)
        if story is None:
            print(f"unknown story {name!r}; choose from: {', '.join(STORIES)}")
            return 2
        h = Harness(HttpClient(base))
        r = h.c.post("/test/reset")
        if r.status_code != 204:
            print(f"cannot reset server at {base} (is TEST_MODE=1?): {r.status_code} {r.text}")
            return 2
        try:
            summary = story(h)
            print(f"PASS  {name}: {summary}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}: {e}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
