from tests.harness import day


def test_console_listings_and_summary(h):
    h.setup_pair()
    h.gateway("H", "spare one")
    h.clock(day(0, 14))
    r = h.c.get("/api/v1/console/gateways").json()
    assert r["now"] == "2026-01-01T14:00:00Z"
    by_id = {g["gateway_id"]: g for g in r["items"]}
    assert by_id["G"]["status_held_seconds"] == 2 * 3600 and by_id["G"]["sensor_count"] == 2
    assert by_id["H"]["status"] == "new" and by_id["H"]["sensor_count"] == 0
    assert [g["gateway_id"] for g in h.c.get("/api/v1/console/gateways?status=new").json()["items"]] == ["H"]

    r = h.c.get("/api/v1/console/sensors").json()
    s = {x["sensor_id"]: x for x in r["items"]}
    assert s["S"]["gateway_ids"] == ["G"] and s["S"]["paused"] is False and s["S"]["lifecycle"] == "active"
    assert h.c.get("/api/v1/console/sensors?lifecycle=dormant").json()["items"] == []

    summary = h.c.get("/api/v1/console/summary").json()
    assert summary["gateways"]["connected"] == 1 and summary["gateways"]["new"] == 1
    assert summary["sensors"]["active"] == 1 and summary["sensors"]["pending"] == 1


def test_paused_flag_marks_a_timer_that_is_not_running(h):
    h.setup_pair()
    h.daily_no_readings("G", "S", range(1, 15))
    h.keepalive("G", 15)
    assert h.s("S")["lifecycle"] == "dormant"
    h.clock(day(15, 1))
    h.heartbeat("G", day(15, 1), "auth_failed")
    row = [x for x in h.c.get("/api/v1/console/sensors").json()["items"] if x["sensor_id"] == "S"][0]
    assert row["paused"] is True and row["next_evaluation_at"] is None and row["coverage"] == "recoverable"


def test_test_mode_returns_a_registered_gateways_token(h):
    token = h.gateway("G")
    assert h.c.get("/test/gateways/G/token").json() == {"gateway_id": "G", "token": token}
    assert h.c.get("/test/gateways/nope/token").status_code == 404
