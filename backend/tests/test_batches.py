from tests.harness import day, iso


def test_batch_idempotency_conflict_and_cross_gateway(h):
    h.setup_pair()
    h.gateway("H")
    h.batch("G", "b0", "S", [h.reading("r0", day(0, 12))], expect=200)
    r = h.batch("G", "b0", "S", [h.reading("r0", day(0, 12), value=1)], expect=409)
    assert r.json()["error"] == "batch_conflict"
    h.batch("H", "b0", "S", [h.reading("r0", day(0, 12))], expect=409)
    assert h.c.get("/api/v1/batches/nope").status_code == 404


def test_partial_processing_and_quarantine_reasons(h):
    h.setup_pair()
    h.clock(day(0, 13))
    readings = [
        h.reading("ok", day(0, 12, 30)),
        h.reading("unit", day(0, 12, 30), unit="mm"),
        h.reading("nan", day(0, 12, 30), value="hot"),
        h.reading("future", day(0, 13, 10)),
        {"reading_id": "missing", "taken_at": iso(day(0, 12))},
        h.reading("r0", day(0, 12), value=99),  # same id as an accepted reading, different content
        h.reading("r0", day(0, 12)),  # same id, same content: ignored
    ]
    h.batch("G", "b1", "S", readings)
    assert h.batch_state("b1")["processing"] == "received"
    h.drain()
    b = h.batch_state("b1")
    assert b["processing"] == "partially_processed" and b["accepted_count"] == 1 and b["attempts"] == 1
    reasons = {q["reading_id"]: q["reason"] for q in b["quarantined"]}
    assert reasons == {
        "unit": "wrong_unit", "nan": "value_not_a_number", "future": "taken_at_in_future",
        "missing": "missing_value", "r0": "conflicting_duplicate",
    }
    h.batch("G", "b2", "S", [h.reading("bad", day(0, 12), unit="mm")])
    h.batch("G", "b3", "ghost", [h.reading("x", day(0, 12))])
    h.drain()
    assert h.batch_state("b2")["processing"] == "quarantined"
    b3 = h.batch_state("b3")
    assert b3["processing"] == "quarantined" and b3["quarantined"][0]["reason"] == "unknown_sensor"


def test_processing_failures_retry_with_backoff_then_quarantine(h):
    h.setup_pair()
    h.clock(day(1))
    h.faults(2)
    h.batch("G", "b1", "S", [h.reading("r1", day(1))])
    h.drain()
    b = h.batch_state("b1")
    assert b["processing"] == "retrying" and b["attempts"] == 1
    h.clock(day(1, 0, 1))  # attempt 2 due after 1 minute, fails too
    assert h.batch_state("b1")["attempts"] == 2 and h.batch_state("b1")["processing"] == "retrying"
    h.clock(day(1, 0, 2))  # attempt 3 due at +1+2 minutes
    assert h.batch_state("b1")["attempts"] == 2
    h.clock(day(1, 0, 3))
    b = h.batch_state("b1")
    assert b["processing"] == "processed" and b["attempts"] == 3 and b["accepted_count"] == 1
    h.faults(5)
    h.batch("G", "b2", "S", [h.reading("r2", day(1))])
    h.clock(day(2))
    b = h.batch_state("b2")
    assert b["processing"] == "quarantined" and b["attempts"] == 5
    assert b["quarantined"] == [{"reading_id": None, "reason": "processing_failed"}]


def test_batch_before_cycle_qualifies_gateway(h):
    h.clock(day(0))
    h.gateway("G")
    h.sensor("S")
    h.cover("S", ["G"])
    h.batch("G", "b0", "S", [h.reading("r0", day(0))])
    assert h.gw("G")["status"] == "new"  # not processed yet
    h.drain()
    g = h.gw("G")
    assert g["status"] == "connected" and g["last_qualifying_at"] == iso(day(0))
    assert h.s("S")["lifecycle"] == "active" and h.s("S")["collection"] == "readings"


def test_clock_only_moves_forward_and_test_routes_hidden_without_test_mode(h, settings):
    h.clock(day(1))
    r = h.c.post("/test/clock", {"now": iso(day(0))}, format="json")
    assert r.status_code == 409 and r.json()["error"] == "clock_backwards"
