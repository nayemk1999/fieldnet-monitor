"""The brief's worked example and its three variations, run through the pure replay engine."""
from datetime import datetime, timedelta, timezone

import pytest

from core.lifecycle import Check, Config, CoverageChange, Decommission, Reading, replay

UTC = timezone.utc
T0 = datetime(2026, 1, 1, tzinfo=UTC)
CFG = Config(
    quiet_days=14,
    dormant_wait=timedelta(days=14),
    sampling_window=timedelta(hours=72),
    sampling_cycles=2,
    batch_deadline=timedelta(hours=24),
)


def day(n, hour=0, minute=0):
    return T0 + timedelta(days=n, hours=hour, minutes=minute)


def check(n, outcome="no_readings", batch_id=None, counts=True):
    return Check(f"c{n}", day(n, 12), outcome, batch_id, counts)


def run(now, readings, checks, batches=None, coverage=None, decommission=None):
    return replay(
        registered_at=day(-1),
        now=now,
        readings=readings,
        checks=checks,
        batch_resolved_at=batches or {},
        coverage_changes=coverage or [CoverageChange(day(-1), "available")],
        decommission=decommission,
        cfg=CFG,
    )


def states(result):
    return [(t["from"], t["to"], t["effective_at"]) for t in result.transitions]


BASE_READING = [Reading("r0", day(0, 12))]
BASE_BATCHES = {"b0": day(0, 12, 1)}


def test_worked_example_days_0_to_49():
    checks = [check(0, "readings", "b0")] + [check(n) for n in range(1, 49)]
    r = run(day(15), BASE_READING, checks, BASE_BATCHES)
    assert r.lifecycle == "dormant"
    assert r.quiet_checked_days == 14
    assert r.next_evaluation_at == day(29)
    assert states(r)[-1] == ("active", "dormant", day(15).isoformat())

    r = run(day(29), BASE_READING, checks, BASE_BATCHES)
    assert r.lifecycle == "sampling" and r.next_evaluation_at == day(32)

    r = run(day(32), BASE_READING, checks, BASE_BATCHES)
    assert r.lifecycle == "dormant" and r.sampling_cycles_done == 1

    r = run(day(46), BASE_READING, checks, BASE_BATCHES)
    assert r.lifecycle == "sampling"

    r = run(day(49), BASE_READING, checks, BASE_BATCHES)
    assert (r.lifecycle, r.lifecycle_reason) == ("retired", "no_readings")
    assert r.lifecycle_since == day(49)
    assert [t["to"] for t in r.transitions] == [
        "active", "dormant", "sampling", "dormant", "sampling", "retired",
    ]


def test_pending_to_active_is_effective_at_taken_at():
    r = run(day(1), BASE_READING, [], BASE_BATCHES)
    assert r.lifecycle == "active" and r.lifecycle_since == day(0, 12)
    assert r.quiet_checked_days == 0  # the reading day itself does not count


def test_disconnection_mid_window_pauses_available_time():
    # G loses auth on day 30 12:00 (coverage recoverable) and recovers on day 37 12:00.
    checks = [check(0, "readings", "b0")] + [check(n) for n in range(1, 30)]
    checks += [check(n, "could_not_read", counts=False) for n in range(30, 37)]
    checks += [check(n) for n in range(37, 40)]
    coverage = [
        CoverageChange(day(-1), "available"),
        CoverageChange(day(30, 12), "recoverable"),
        CoverageChange(day(37, 12), "available"),
    ]
    r = run(day(33), BASE_READING, checks, BASE_BATCHES, coverage)
    assert r.lifecycle == "sampling" and r.next_evaluation_at is None  # paused

    r = run(day(38), BASE_READING, checks, BASE_BATCHES, coverage)
    assert r.lifecycle == "sampling" and r.next_evaluation_at == day(39)

    r = run(day(39), BASE_READING, checks, BASE_BATCHES, coverage)
    assert r.lifecycle == "dormant" and r.sampling_cycles_done == 1
    assert states(r)[-1] == ("sampling", "dormant", day(39).isoformat())


def test_late_reading_rewrites_history():
    checks = [check(0, "readings", "b0")] + [check(n) for n in range(1, 20)]
    before = run(day(20), BASE_READING, checks, BASE_BATCHES)
    assert before.lifecycle == "dormant"
    late = BASE_READING + [Reading("r9", day(9, 12))]
    after = run(day(20), late, checks, {**BASE_BATCHES, "b9": day(20)})
    assert after.lifecycle == "active"
    assert after.quiet_checked_days == 10  # days 10-19
    assert [t["to"] for t in after.transitions] == ["active"]


def test_unresolved_day_delays_dormant_by_one_day():
    # Day 14 reports readings but the batch never arrives: unresolved until day 15 12:00.
    checks = [check(0, "readings", "b0")] + [check(n) for n in range(1, 14)]
    checks += [check(14, "readings", "missing"), check(15), check(16)]
    r = run(day(15), BASE_READING, checks, BASE_BATCHES)
    assert r.lifecycle == "active" and r.quiet_checked_days == 13
    r = run(day(15, 12), BASE_READING, checks, BASE_BATCHES)
    assert r.lifecycle == "active"  # day 14 resolved as unchecked; day 15 not complete
    r = run(day(16), BASE_READING, checks, BASE_BATCHES)
    assert r.lifecycle == "dormant" and states(r)[-1][2] == day(16).isoformat()


def test_window_without_checks_restarts_and_does_not_count():
    checks = [check(0, "readings", "b0")] + [check(n) for n in range(1, 29)]
    r = run(day(34), BASE_READING, checks, BASE_BATCHES)
    assert r.lifecycle == "sampling" and r.sampling_cycles_done == 0
    assert r.lifecycle_since == day(29)  # restarts do not move lifecycle_since
    assert r.next_evaluation_at == day(35)  # second window: day 32 to day 35
    assert [t["rule"] for t in r.transitions][-1] == "sampling_window_restarted_without_checks"


def test_reading_in_sampling_window_wakes_sensor():
    checks = [check(0, "readings", "b0")] + [check(n) for n in range(1, 31)]
    readings = BASE_READING + [Reading("r30", day(30, 6))]
    r = run(day(31), readings, checks, {**BASE_BATCHES, "b30": day(30, 7)})
    assert r.lifecycle == "active" and r.lifecycle_since == day(30, 6)
    assert r.sampling_cycles_done == 0


def test_loss_of_coverage_retires_and_restoration_resets_to_pending():
    coverage = [
        CoverageChange(day(-1), "available"),
        CoverageChange(day(3), "none"),
        CoverageChange(day(5), "recoverable"),
    ]
    r = run(day(4), BASE_READING, [], BASE_BATCHES, coverage)
    assert (r.lifecycle, r.lifecycle_reason) == ("retired", "no_live_coverage")
    r = run(day(6), BASE_READING, [], BASE_BATCHES, coverage)
    assert r.lifecycle == "pending" and r.quiet_checked_days == 0 and r.lifecycle_since == day(5)


def test_decommission_is_terminal_and_first_at_same_instant():
    coverage = [CoverageChange(day(-1), "available"), CoverageChange(day(3), "none")]
    r = run(day(10), BASE_READING, [], BASE_BATCHES, coverage, Decommission(day(3), "broken"))
    assert (r.lifecycle, r.lifecycle_reason) == ("decommissioned", "broken")
    assert [t["to"] for t in r.transitions] == ["active", "decommissioned"]
