"""The worked example and its variations, driven end to end through the fixed API and test clock."""
from tests.harness import day, iso


def test_worked_example_through_api(h):
    h.setup_pair()
    s = h.s("S")
    assert s["lifecycle"] == "active" and s["lifecycle_since"] == iso(day(0, 12))
    h.daily_no_readings("G", "S", range(1, 15))
    assert h.s("S")["quiet_checked_days"] == 13  # day 14 not complete yet
    h.keepalive("G", 15)  # clock -> day 15 00:00
    s = h.s("S")
    assert s["lifecycle"] == "dormant" and s["lifecycle_since"] == iso(day(15))
    assert s["quiet_checked_days"] == 14 and s["next_evaluation_at"] == iso(day(29))
    h.clock(day(15, 12))
    h.cycle("G", "c15", day(15, 12), [{"sensor_id": "S", "outcome": "no_readings"}])
    h.daily_no_readings("G", "S", range(16, 29))
    h.keepalive("G", 29)
    s = h.s("S")
    assert s["lifecycle"] == "sampling" and s["next_evaluation_at"] == iso(day(32))
    h.clock(day(29, 12))
    h.cycle("G", "c29", day(29, 12), [{"sensor_id": "S", "outcome": "no_readings"}])
    h.daily_no_readings("G", "S", range(30, 32))
    h.keepalive("G", 32)
    s = h.s("S")
    assert s["lifecycle"] == "dormant" and s["sampling_cycles_done"] == 1 and s["next_evaluation_at"] == iso(day(46))
    h.clock(day(32, 12))
    h.cycle("G", "c32", day(32, 12), [{"sensor_id": "S", "outcome": "no_readings"}])
    h.daily_no_readings("G", "S", range(33, 46))
    h.keepalive("G", 46)
    assert h.s("S")["lifecycle"] == "sampling"
    h.clock(day(46, 12))
    h.cycle("G", "c46", day(46, 12), [{"sensor_id": "S", "outcome": "no_readings"}])
    h.daily_no_readings("G", "S", range(47, 49))
    h.keepalive("G", 49)
    s = h.s("S")
    assert (s["lifecycle"], s["lifecycle_reason"]) == ("retired", "no_readings")
    lifecycle_entries = [e["to"] for e in h.timeline("sensors", "S") if e["axis"] == "lifecycle" and e["kind"] == "transition"]
    assert lifecycle_entries == ["pending", "active", "dormant", "sampling", "dormant", "sampling", "retired"]
    assert h.gw("G")["status"] == "connected"  # never flapped: timeline has one status change
    assert [e["to"] for e in h.timeline("gateways", "G") if e["axis"] == "status"] == ["new", "connected"]
    # readings wake a retired (no_readings) sensor
    h.clock(day(49, 1))
    h.batch("G", "b49", "S", [h.reading("r49", day(49, 1))])
    h.drain()
    assert h.s("S")["lifecycle"] == "active"


def test_disconnection_mid_window_pauses_the_window(h):
    h.setup_pair()
    h.daily_no_readings("G", "S", range(1, 30))
    assert h.s("S")["lifecycle"] == "sampling"
    h.keepalive("G", 30)
    h.clock(day(30, 12))
    h.cycle("G", "c30", day(30, 12), [{"sensor_id": "S", "outcome": "no_readings"}], session="auth_failed")
    s = h.s("S")
    assert h.gw("G")["status"] == "disconnected"
    assert s["lifecycle"] == "sampling" and s["next_evaluation_at"] is None and s["collection"] == "not_checked"
    h.clock(day(37, 12))
    assert h.s("S")["next_evaluation_at"] is None  # still paused: 36h of the window remain
    h.cycle("G", "c37", day(37, 12), [{"sensor_id": "S", "outcome": "no_readings"}])
    s = h.s("S")
    assert h.gw("G")["status"] == "connected"
    assert s["lifecycle"] == "sampling" and s["next_evaluation_at"] == iso(day(39))
    h.daily_no_readings("G", "S", [38])
    h.clock(day(39))
    s = h.s("S")
    assert s["lifecycle"] == "dormant" and s["lifecycle_since"] == iso(day(39)) and s["sampling_cycles_done"] == 1


def test_late_reading_produces_a_correction(h):
    h.setup_pair()
    h.daily_no_readings("G", "S", range(1, 20))
    assert h.s("S")["lifecycle"] == "dormant"
    h.clock(day(20))
    h.batch("G", "b9", "S", [h.reading("r9", day(9, 12))])
    h.drain()
    s = h.s("S")
    assert s["lifecycle"] == "active" and s["quiet_checked_days"] == 10
    entries = h.timeline("sensors", "S")
    corrections = [e for e in entries if e["kind"] == "correction"]
    assert len(corrections) == 1
    c = corrections[0]
    assert (c["from"], c["to"]) == ("dormant", "active") and c["evidence_ids"] == ["b9"]
    assert any(e["kind"] == "transition" and e["to"] == "dormant" for e in entries)  # earlier entry stays


def test_unresolved_day_waits_then_counts_as_unchecked(h):
    h.setup_pair()
    h.daily_no_readings("G", "S", range(1, 14))
    h.clock(day(14, 12))
    h.cycle("G", "c14", day(14, 12), [{"sensor_id": "S", "outcome": "readings", "batch_id": "never"}])
    h.clock(day(15))
    assert h.s("S")["lifecycle"] == "active"
    h.clock(day(15, 12))
    h.cycle("G", "c15", day(15, 12), [{"sensor_id": "S", "outcome": "no_readings"}])
    h.clock(day(16))
    s = h.s("S")
    assert s["lifecycle"] == "dormant" and s["lifecycle_since"] == iso(day(16))
