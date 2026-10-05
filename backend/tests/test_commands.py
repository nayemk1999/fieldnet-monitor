from tests.harness import day, iso


def test_stop_timeout_late_ack_and_resume(h):
    h.setup_pair()
    h.action("G", "resume", expect=409)
    g = h.action("G", "stop")
    assert g["command_state"] == "stop_pending" and g["coverage_class"] == "available"
    h.action("G", "stop", expect=409)
    cmds = h.commands("G")
    assert len(cmds) == 1 and cmds[0]["type"] == "stop" and cmds[0]["seq"] == 1
    stop_id = cmds[0]["command_id"]
    h.clock(day(0, 12, 12))
    g = h.gw("G")
    assert g["command_state"] == "stop_failed" and g["coverage_class"] == "available"
    h.ack("G", stop_id, day(0, 12, 11))  # late ack of the latest command
    g = h.gw("G")
    assert g["command_state"] == "stopped" and g["coverage_class"] == "stopped"
    assert h.s("S")["coverage"] == "stopped" and h.s("S")["collection"] == "collection_stopped"
    assert h.commands("G") == []
    h.ack("G", stop_id, day(0, 12, 11))  # idempotent
    g = h.action("G", "resume")
    assert g["command_state"] == "resume_pending"
    resume_id = h.commands("G")[0]["command_id"]
    h.ack("G", stop_id, day(0, 12, 13))  # superseded: accepted, no state change
    assert h.gw("G")["command_state"] == "resume_pending"
    h.ack("G", resume_id, day(0, 12, 13))
    g = h.gw("G")
    assert g["command_state"] == "running" and g["coverage_class"] == "available"
    kinds = [(e["kind"], e["to"]) for e in h.timeline("gateways", "G")]
    assert ("ack", "stop") in kinds and ("ack", "resume") in kinds
    h.ack("G", "00000000-0000-0000-0000-000000000000", day(0, 12, 13), expect=404)


def test_stop_supersedes_resume(h):
    h.setup_pair()
    h.action("G", "stop")
    h.action("G", "resume")
    assert h.gw("G")["command_state"] == "resume_pending"
    assert h.action("G", "stop")["command_state"] == "stop_pending"
    cmds = h.commands("G")
    assert cmds[0]["seq"] == 3 and cmds[0]["type"] == "stop"


def test_collecting_after_stop_flag(h):
    h.setup_pair()
    h.action("G", "stop")
    stop_id = h.commands("G")[0]["command_id"]
    h.clock(day(0, 13))
    h.ack("G", stop_id, day(0, 13))
    h.clock(day(0, 14))
    # a reading taken before the stop was acked never raises the flag
    h.batch("G", "b1", "S", [h.reading("r1", day(0, 12, 30))])
    h.drain()
    assert h.gw("G")["flags"] == []
    h.batch("G", "b2", "S", [h.reading("r2", day(0, 13, 30))])
    h.drain()
    g = h.gw("G")
    assert g["flags"] == ["collecting_after_stop"]
    assert any(e["kind"] == "flag" and e["to"] == "collecting_after_stop" for e in h.timeline("gateways", "G"))
    assert h.s("S")["lifecycle"] == "active"  # readings are kept and counted
    h.action("G", "resume")
    h.ack("G", h.commands("G")[0]["command_id"], day(0, 14))
    assert h.gw("G")["flags"] == []
