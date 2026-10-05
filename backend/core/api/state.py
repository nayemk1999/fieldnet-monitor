"""Response shapes for the state API (brief: Operator and state API)."""
from core.models import Gateway, Sensor, TimelineEntry


def gateway_state(gw: Gateway) -> dict:
    return {
        "gateway_id": gw.gateway_id,
        "name": gw.name,
        "status": gw.status,
        "status_since": gw.status_since,
        "command_state": gw.command_state,
        "coverage_class": gw.coverage_class,
        "last_heartbeat_at": gw.last_heartbeat_at,
        "last_qualifying_at": gw.last_qualifying_at,
        "disconnected_since": gw.disconnected_since,
        "flags": ["collecting_after_stop"] if gw.collecting_after_stop else [],
    }


def sensor_state(s: Sensor) -> dict:
    return {
        "sensor_id": s.sensor_id,
        "type": s.type,
        "lifecycle": s.lifecycle,
        "lifecycle_reason": s.lifecycle_reason,
        "lifecycle_since": s.lifecycle_since,
        "collection": s.collection,
        "coverage": s.coverage,
        "quiet_checked_days": s.quiet_checked_days,
        "sampling_cycles_done": s.sampling_cycles_done,
        "next_evaluation_at": s.next_evaluation_at,
    }


def timeline_entry(e: TimelineEntry) -> dict:
    return {
        "seq": e.seq,
        "kind": e.kind,
        "axis": e.axis,
        "from": e.from_value,
        "to": e.to_value,
        "effective_at": e.effective_at,
        "recorded_at": e.recorded_at,
        "rule": e.rule,
        "evidence_ids": e.evidence_ids,
        "detail": e.detail,
    }
