from tests.harness import day, iso


def test_sensor_coverage_is_best_class_and_none_retires(h):
    h.clock(day(0))
    h.gateway("A")
    h.gateway("B")
    h.sensor("S")
    h.cover("S", ["A", "B"])
    s = h.s("S")
    assert s["coverage"] == "recoverable" and s["collection"] == "not_checked" and s["lifecycle"] == "pending"
    h.cycle("A", "a0", day(0), [{"sensor_id": "S", "outcome": "readings", "batch_id": "ba"}])
    h.batch("A", "ba", "S", [h.reading("ra", day(0))])
    h.drain()
    s = h.s("S")
    assert s["coverage"] == "available" and s["lifecycle"] == "active" and s["collection"] == "readings"
    h.clock(day(0, 1))
    h.action("A", "suspend", reason="x")
    assert h.s("S")["coverage"] == "recoverable"  # B is new
    assert h.s("S")["lifecycle"] == "active"  # unchanged while recoverable
    h.clock(day(0, 2))
    h.action("B", "retire")
    s = h.s("S")
    assert s["coverage"] == "none" and (s["lifecycle"], s["lifecycle_reason"]) == ("retired", "no_live_coverage")
    assert s["lifecycle_since"] == iso(day(0, 2))
    h.clock(day(0, 3))
    h.action("A", "unsuspend")
    s = h.s("S")
    assert s["coverage"] == "available" and s["lifecycle"] == "pending" and s["lifecycle_since"] == iso(day(0, 3))
    r = h.c.put("/api/v1/sensors/S/coverage", {"gateway_ids": ["B"]}, format="json")
    assert r.status_code == 409 and r.json()["error"] == "retired_gateway"


def test_collection_precedence_and_24h_window(h):
    h.clock(day(0))
    h.gateway("A")
    h.gateway("B")
    h.sensor("S")
    h.cover("S", ["A", "B"])
    h.cycle("A", "a0", day(0), [{"sensor_id": "S", "outcome": "no_readings"}])
    h.cycle("B", "b0", day(0), [{"sensor_id": "S", "outcome": "timeout"}])
    assert h.s("S")["collection"] == "no_readings"
    h.clock(day(0, 1))
    h.cycle("A", "a1", day(0, 1), [{"sensor_id": "S", "outcome": "could_not_read"}])
    assert h.s("S")["collection"] == "could_not_read"  # A's latest wins over B's timed_out by precedence
    h.clock(day(0, 2))
    h.cycle("B", "b1", day(0, 2), [{"sensor_id": "S", "outcome": "timeout"}])
    h.cycle("A", "a2", day(0, 2), [{"sensor_id": "S", "outcome": "no_readings"}])
    assert h.s("S")["collection"] == "no_readings"
    h.clock(day(1, 3))  # both gateways stale by now, nothing available
    assert h.s("S")["collection"] == "not_checked" and h.s("S")["coverage"] == "recoverable"


def test_decommission_is_terminal(h):
    h.setup_pair()
    s = h.sensor_action("S", "decommission", "flooded")
    assert (s["lifecycle"], s["lifecycle_reason"]) == ("decommissioned", "flooded")
    h.sensor_action("S", "decommission", "again", expect=409)
    h.action("G", "suspend", reason="x")
    assert h.s("S")["lifecycle"] == "decommissioned"
