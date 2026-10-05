from datetime import timedelta

from tests.harness import day, iso


def test_register_and_unknown_token(h):
    h.clock(day(0))
    h.gateway("G")
    r = h.c.post("/api/v1/gateways", {"gateway_id": "G", "name": "dup"}, format="json")
    assert r.status_code == 409 and r.json()["error"] == "duplicate_gateway"
    r = h.c.post("/gw/v1/heartbeat", {"sent_at": iso(day(0)), "session": "ok"}, format="json", HTTP_AUTHORIZATION="Bearer nope")
    assert r.status_code == 401 and r.json() == {"error": "unauthorized", "detail": "unknown token"}
    r = h.c.post("/gw/v1/heartbeat", {"sent_at": "garbage", "session": "ok"}, format="json", HTTP_AUTHORIZATION=f"Bearer {h.tokens['G']}")
    assert r.status_code == 422 and r.json()["error"] == "validation_error"
    assert h.c.get("/api/v1/gateways/nope").status_code == 404


def test_heartbeat_never_qualifies_but_updates_last_heartbeat(h):
    h.clock(day(0))
    h.gateway("G")
    h.heartbeat("G", day(0))
    g = h.gw("G")
    assert g["status"] == "new" and g["last_qualifying_at"] is None
    assert g["last_heartbeat_at"] == iso(day(0))


def test_new_to_connected_to_stale_and_back_only_with_fresh_evidence(h):
    h.setup_pair()
    g = h.gw("G")
    assert g["status"] == "connected" and g["last_qualifying_at"] == iso(day(0, 12))
    h.clock(day(1, 0, 1))
    g = h.gw("G")
    assert g["status"] == "stale" and g["status_since"] == iso(day(1, 0))  # effective at due time, not jump time
    # old late evidence (13h old) updates nothing
    h.cycle("G", "old", day(0, 11), [{"sensor_id": "S", "outcome": "no_readings"}])
    assert h.gw("G")["status"] == "stale"
    h.cycle("G", "fresh", day(1, 0), [{"sensor_id": "S", "outcome": "no_readings"}])
    g = h.gw("G")
    assert g["status"] == "connected" and g["last_qualifying_at"] == iso(day(1, 0))


def test_auth_failed_disconnects_and_only_newer_qualifying_evidence_recovers(h):
    h.setup_pair()
    h.clock(day(0, 13))
    h.heartbeat("G", day(0, 13), "auth_failed")
    g = h.gw("G")
    assert g["status"] == "disconnected" and g["disconnected_since"] == iso(day(0, 13))
    h.clock(day(0, 13, 6))
    h.heartbeat("G", day(0, 13, 5), "auth_failed")
    assert h.gw("G")["disconnected_since"] == iso(day(0, 13))  # first time kept
    h.heartbeat("G", day(0, 13, 6), "ok")
    assert h.gw("G")["status"] == "disconnected"  # heartbeat ok is not enough
    # an old batch re-sent after the failure does not recover it
    h.batch("G", "b0", "S", [h.reading("r0", day(0, 12))], expect=200)
    h.drain()
    assert h.gw("G")["status"] == "disconnected"
    h.clock(day(0, 14))
    h.cycle("G", "c1", day(0, 14), [{"sensor_id": "S", "outcome": "no_readings"}])
    assert h.gw("G")["status"] == "connected"


def test_cycle_idempotency_and_conflict_and_ignored(h):
    h.setup_pair()
    h.sensor("X")
    r = h.cycle("G", "c1", day(0, 12), [{"sensor_id": "S", "outcome": "no_readings"}, {"sensor_id": "X", "outcome": "no_readings"}])
    assert r.json() == {"ignored": ["X"]}
    r = h.cycle("G", "c1", day(0, 12), [{"sensor_id": "S", "outcome": "no_readings"}, {"sensor_id": "X", "outcome": "no_readings"}], expect=200)
    assert r.json() == {"ignored": ["X"]}
    r = h.cycle("G", "c1", day(0, 12), [{"sensor_id": "S", "outcome": "could_not_read"}], expect=409)
    assert r.json()["error"] == "cycle_conflict"
    h.cycle("G", "bad", day(0, 12), [{"sensor_id": "S", "outcome": "readings"}], expect=422)
    h.cycle("G", "bad2", day(0, 12), [{"sensor_id": "S", "outcome": "no_readings", "batch_id": "b"}], expect=422)
    h.cycle("G", "future", day(0, 12) + timedelta(minutes=7), [{"sensor_id": "S", "outcome": "no_readings"}], expect=422)


def test_suspend_unsuspend_derivation_and_retire(h):
    h.setup_pair()
    h.action("G", "suspend", expect=422)
    g = h.action("G", "suspend", reason="maintenance")
    assert g["status"] == "suspended" and g["coverage_class"] == "dead"
    assert h.s("S")["coverage"] == "none"
    assert (h.s("S")["lifecycle"], h.s("S")["lifecycle_reason"]) == ("retired", "no_live_coverage")
    h.clock(day(2))  # automatic rules never change status while suspended
    h.heartbeat("G", day(2), "auth_failed")
    assert h.gw("G")["status"] == "suspended"
    g = h.action("G", "unsuspend")
    assert g["status"] == "disconnected"  # latest auth failure newer than last qualifying
    assert h.s("S")["lifecycle"] == "pending"  # coverage restored resets the sensor
    h.cycle("G", "c2", day(2), [{"sensor_id": "S", "outcome": "no_readings"}])
    h.action("G", "suspend", reason="again")
    h.clock(day(2, 13))
    assert h.action("G", "unsuspend")["status"] == "stale"
    h.action("G", "retire")
    assert h.gw("G")["status"] == "retired"
    h.heartbeat("G", day(2, 13), expect=403)
    h.action("G", "suspend", reason="x", expect=409)


def test_mark_spare_rules(h):
    h.clock(day(0))
    h.gateway("G")
    h.sensor("S")
    h.cover("S", ["G"])
    h.action("G", "mark_spare", expect=409)
    h.cover("S", [])
    assert h.action("G", "mark_spare")["status"] == "spare"
    h.cover("S", ["G"])
    assert h.gw("G")["status"] == "new"
    r = h.c.put("/api/v1/sensors/S/coverage", {"gateway_ids": ["nope"]}, format="json")
    assert r.status_code == 404
