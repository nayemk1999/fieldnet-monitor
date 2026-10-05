"""Thin client over the fixed API for tests and stories."""
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def day(n, hour=0, minute=0):
    return T0 + timedelta(days=n, hours=hour, minutes=minute)


def iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


class Harness:
    def __init__(self, client):
        self.c = client
        self.tokens = {}

    # -- test endpoints
    def clock(self, t):
        r = self.c.post("/test/clock", {"now": iso(t)}, format="json")
        assert r.status_code == 200, r.content
        return r

    def drain(self):
        assert self.c.post("/test/drain").status_code == 200

    def faults(self, n):
        assert self.c.post("/test/faults", {"processing_failures": n}, format="json").status_code == 200

    # -- operator API
    def gateway(self, gid, name=None):
        r = self.c.post("/api/v1/gateways", {"gateway_id": gid, "name": name or gid}, format="json")
        assert r.status_code == 201, r.content
        self.tokens[gid] = r.json()["token"]
        return r.json()["token"]

    def sensor(self, sid, type_="temperature"):
        r = self.c.post("/api/v1/sensors", {"sensor_id": sid, "type": type_}, format="json")
        assert r.status_code == 201, r.content
        return r.json()

    def cover(self, sid, gids):
        r = self.c.put(f"/api/v1/sensors/{sid}/coverage", {"gateway_ids": gids}, format="json")
        assert r.status_code == 200, r.content
        return r.json()

    def action(self, gid, action, reason=None, expect=200):
        body = {"action": action}
        if reason is not None:
            body["reason"] = reason
        r = self.c.post(f"/api/v1/gateways/{gid}/actions", body, format="json")
        assert r.status_code == expect, r.content
        return r.json()

    def sensor_action(self, sid, action, reason, expect=200):
        r = self.c.post(f"/api/v1/sensors/{sid}/actions", {"action": action, "reason": reason}, format="json")
        assert r.status_code == expect, r.content
        return r.json()

    def gw(self, gid):
        r = self.c.get(f"/api/v1/gateways/{gid}")
        assert r.status_code == 200, r.content
        return r.json()

    def s(self, sid):
        r = self.c.get(f"/api/v1/sensors/{sid}")
        assert r.status_code == 200, r.content
        return r.json()

    def timeline(self, kind, ident):
        r = self.c.get(f"/api/v1/{kind}/{ident}/timeline")
        assert r.status_code == 200, r.content
        return r.json()

    def batch_state(self, bid):
        r = self.c.get(f"/api/v1/batches/{bid}")
        assert r.status_code == 200, r.content
        return r.json()

    # -- gateway API
    def _auth(self, gid):
        return {"HTTP_AUTHORIZATION": f"Bearer {self.tokens[gid]}"}

    def heartbeat(self, gid, sent_at, session="ok", expect=204):
        r = self.c.post("/gw/v1/heartbeat", {"sent_at": iso(sent_at), "session": session}, format="json", **self._auth(gid))
        assert r.status_code == expect, r.content
        return r

    def cycle(self, gid, cycle_id, finished_at, results, session="ok", expect=202, started_at=None):
        body = {
            "cycle_id": cycle_id,
            "started_at": iso(started_at or finished_at - timedelta(minutes=1)),
            "finished_at": iso(finished_at),
            "session": session,
            "results": results,
        }
        r = self.c.post("/gw/v1/cycles", body, format="json", **self._auth(gid))
        assert r.status_code == expect, r.content
        return r

    def batch(self, gid, batch_id, sensor_id, readings, expect=202):
        r = self.c.put(f"/gw/v1/batches/{batch_id}", {"sensor_id": sensor_id, "readings": readings}, format="json", **self._auth(gid))
        assert r.status_code == expect, r.content
        return r

    def commands(self, gid):
        r = self.c.get("/gw/v1/commands", **self._auth(gid))
        assert r.status_code == 200
        return r.json()["commands"]

    def ack(self, gid, command_id, acked_at, expect=204):
        r = self.c.post(f"/gw/v1/commands/{command_id}/ack", {"acked_at": iso(acked_at)}, format="json", **self._auth(gid))
        assert r.status_code == expect, r.content
        return r

    # -- scenario helpers
    def reading(self, rid, taken_at, value=20.5, unit="C"):
        return {"reading_id": rid, "taken_at": iso(taken_at), "value": value, "unit": unit}

    def keepalive(self, gid, n, sid="T"):
        """A 00:00 cycle for a second sensor so the gateway never crosses the 12h stale threshold
        between its daily 12:00 reports (the worked example assumes G stays connected)."""
        self.clock(day(n, 0))
        self.cycle(gid, f"k{n}", day(n, 0), [{"sensor_id": sid, "outcome": "no_readings"}])

    def daily_no_readings(self, gid, sid, days, prefix="c", keepalive=True):
        """One no_readings cycle at 12:00 on each day in `days`, moving the clock along."""
        for n in days:
            if keepalive:
                self.keepalive(gid, n)
            self.clock(day(n, 12))
            self.cycle(gid, f"{prefix}{n}", day(n, 12), [{"sensor_id": sid, "outcome": "no_readings"}])

    def setup_pair(self, gid="G", sid="S", start=day(0)):
        """Gateway G covering sensor S (and keepalive sensor T), connected via a readings cycle + batch at day 0 12:00."""
        self.clock(start)
        self.gateway(gid)
        self.sensor(sid)
        self.sensor("T")
        self.cover(sid, [gid])
        self.cover("T", [gid])
        self.clock(day(0, 12))
        self.cycle(gid, "c0", day(0, 12), [{"sensor_id": sid, "outcome": "readings", "batch_id": "b0"}])
        self.batch(gid, "b0", sid, [self.reading("r0", day(0, 12))])
        self.clock(day(0, 12, 1))
