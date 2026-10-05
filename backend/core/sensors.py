"""Database side of the sensor engine.

Gathers the replay inputs for one sensor, runs core.lifecycle.replay, and diffs
the result against the history recorded so far: new transitions are appended,
a diverging history becomes one correction entry. Also derives the sensor's
collection (brief: Latest collection).
"""
from datetime import datetime

from django.utils.dateparse import parse_datetime

from core import config, lifecycle, timeline
from core.models import Batch, CycleResult, Reading, Sensor, TimelineEntry

CFG = lifecycle.Config(
    quiet_days=config.QUIET_DAYS_BEFORE_DORMANT,
    dormant_wait=config.DORMANT_WAIT,
    sampling_window=config.SAMPLING_WINDOW,
    sampling_cycles=config.SAMPLING_CYCLES_BEFORE_RETIRED,
    batch_deadline=config.BATCH_DEADLINE,
)

_PRECEDENCE = ["readings", "no_readings", "could_not_read", "timed_out"]


def _inputs(sensor: Sensor) -> dict:
    results = list(CycleResult.objects.filter(sensor=sensor))
    batch_ids = {r.batch_id for r in results if r.batch_id}
    coverage_entries = TimelineEntry.objects.filter(
        subject_type="sensor", subject_id=sensor.sensor_id, kind="transition", axis="coverage"
    ).order_by("seq")
    return {
        "readings": [lifecycle.Reading(r.reading_id, r.taken_at) for r in Reading.objects.filter(sensor=sensor)],
        "checks": [
            lifecycle.Check(r.cycle_id, r.finished_at, r.outcome, r.batch_id, r.counts_as_check) for r in results
        ],
        "batch_resolved_at": {
            b.batch_id: b.resolved_at for b in Batch.objects.filter(batch_id__in=batch_ids)
        },
        "coverage_changes": [lifecycle.CoverageChange(e.effective_at, e.to_value) for e in coverage_entries],
        "decommission": (
            lifecycle.Decommission(sensor.decommissioned_at, sensor.decommission_reason)
            if sensor.decommissioned_at
            else None
        ),
    }


def _record_transition(sensor: Sensor, t: dict) -> None:
    timeline.for_sensor(
        sensor.sensor_id, kind="transition", axis="lifecycle", from_value=t["from"], to_value=t["to"],
        effective_at=parse_datetime(t["effective_at"]), rule=t["rule"], evidence_ids=t["evidence_ids"],
        detail={"reason": t["reason"]} if t["reason"] else None,
    )


def evaluate(sensor: Sensor, now: datetime, evidence_ids=()) -> Sensor:
    """Replay the sensor to `now` and reconcile the recorded history with the result."""
    result = lifecycle.replay(registered_at=sensor.created_at, now=now, cfg=CFG, **_inputs(sensor))
    new, old = result.transitions, sensor.history
    if new != old:
        if new[: len(old)] == old:
            for t in new[len(old):]:
                _record_transition(sensor, t)
        else:
            i = next(k for k in range(min(len(new), len(old)) + 1) if k >= len(new) or k >= len(old) or new[k] != old[k])
            timeline.for_sensor(
                sensor.sensor_id, kind="correction", axis="lifecycle", from_value=sensor.lifecycle,
                to_value=result.lifecycle, effective_at=result.lifecycle_since, rule="late_evidence_recompute",
                evidence_ids=evidence_ids,
                detail={"recomputed_transitions": new[i:], "superseded_transitions": old[i:]},
            )
    sensor.lifecycle = result.lifecycle
    sensor.lifecycle_reason = result.lifecycle_reason
    sensor.lifecycle_since = result.lifecycle_since
    sensor.quiet_checked_days = result.quiet_checked_days
    sensor.sampling_cycles_done = result.sampling_cycles_done
    sensor.next_evaluation_at = result.next_evaluation_at
    sensor.history = new
    _refresh_collection(sensor, now)
    sensor.save()
    return sensor


def _readings_outcome(result: CycleResult, now: datetime) -> str:
    """A readings outcome whose batch was quarantined or never arrived is could_not_read."""
    batch = Batch.objects.filter(pk=result.batch_id).first()
    if batch is None:
        return "could_not_read" if now >= result.finished_at + config.BATCH_DEADLINE else "readings"
    return "could_not_read" if batch.processing == "quarantined" else "readings"


def compute_collection(sensor: Sensor, now: datetime) -> str:
    since = now - config.COLLECTION_WINDOW
    mentioned = CycleResult.objects.filter(sensor=sensor, batch_id__isnull=False).values_list("batch_id", flat=True)
    outcomes = []
    for gw in sensor.gateways.filter(coverage_class="available"):
        latest = CycleResult.objects.filter(sensor=sensor, gateway=gw).order_by("-finished_at").first()
        candidate = None
        if latest is not None and latest.finished_at >= since:
            outcome = _readings_outcome(latest, now) if latest.outcome == "readings" else latest.outcome
            candidate = (latest.finished_at, outcome)
        # A reading from a batch no cycle mentions counts as a readings outcome at its taken_at.
        loose = (
            Reading.objects.filter(sensor=sensor, gateway=gw, taken_at__gte=since)
            .exclude(batch_id__in=mentioned)
            .order_by("-taken_at")
            .first()
        )
        if loose is not None and (candidate is None or loose.taken_at > candidate[0]):
            candidate = (loose.taken_at, "readings")
        if candidate is not None:
            outcomes.append(candidate[1])
    for o in _PRECEDENCE:
        if o in outcomes:
            return o
    return "collection_stopped" if sensor.coverage == "stopped" else "not_checked"


def _refresh_collection(sensor: Sensor, now: datetime) -> None:
    new = compute_collection(sensor, now)
    if new != sensor.collection:
        timeline.for_sensor(
            sensor.sensor_id, kind="transition", axis="collection", from_value=sensor.collection, to_value=new,
            effective_at=now, rule="latest_collection",
        )
        sensor.collection = new
