"""Gateway status, command state and coverage class rules (brief: Gateway transitions, Stop and resume, Coverage)."""
from datetime import datetime

from core import config, timeline
from core.errors import conflict
from core.models import Command, Gateway

_AVAILABLE_COMMAND_STATES = {"running", "stop_pending", "stop_failed"}
_RECOVERABLE_STATUSES = {"new", "spare", "stale", "disconnected"}


def coverage_class(status: str, command_state: str) -> str:
    if status == "connected":
        return "available" if command_state in _AVAILABLE_COMMAND_STATES else "stopped"
    if status in _RECOVERABLE_STATUSES:
        return "recoverable"
    return "dead"


# --- low-level setters: every change appends a timeline entry ------------------


def set_status(gw: Gateway, new: str, at: datetime, rule: str, evidence_ids=()) -> bool:
    if gw.status == new:
        return False
    timeline.for_gateway(
        gw.gateway_id, kind="transition", axis="status", from_value=gw.status, to_value=new,
        effective_at=at, rule=rule, evidence_ids=evidence_ids,
    )
    gw.status, gw.status_since = new, at
    if new != "disconnected":
        gw.disconnected_since = None
    return True


def set_command_state(gw: Gateway, new: str, at: datetime, rule: str, evidence_ids=()) -> bool:
    if gw.command_state == new:
        return False
    timeline.for_gateway(
        gw.gateway_id, kind="transition", axis="command_state", from_value=gw.command_state, to_value=new,
        effective_at=at, rule=rule, evidence_ids=evidence_ids,
    )
    gw.command_state, gw.command_state_since = new, at
    return True


def refresh_coverage_class(gw: Gateway, at: datetime) -> bool:
    new = coverage_class(gw.status, gw.command_state)
    if new == gw.coverage_class:
        return False
    timeline.for_gateway(
        gw.gateway_id, kind="transition", axis="coverage_class", from_value=gw.coverage_class, to_value=new,
        effective_at=at, rule="coverage_class_derived",
    )
    gw.coverage_class = new
    return True


# --- due (timer) transitions ---------------------------------------------------


def stale_due_at(gw: Gateway):
    if gw.status == "connected" and gw.last_qualifying_at is not None:
        return gw.last_qualifying_at + config.STALE_AFTER
    return None


def latest_command(gw: Gateway):
    return Command.objects.filter(gateway=gw).order_by("-seq").first()


def command_timeout_due_at(gw: Gateway):
    if gw.command_state not in ("stop_pending", "resume_pending"):
        return None
    cmd = latest_command(gw)
    if cmd is None or cmd.acked_at is not None:
        return None
    return cmd.issued_at + config.COMMAND_TIMEOUT


def apply_due(gw: Gateway, now: datetime) -> bool:
    """Apply timer transitions due at or before `now`, each effective at its own due time."""
    changed = False
    due = stale_due_at(gw)
    if due is not None and now >= due:
        changed |= set_status(gw, "stale", due, "stale_after_12h_without_qualifying_evidence")
    due = command_timeout_due_at(gw)
    if due is not None and now >= due:
        cmd = latest_command(gw)
        failed = "stop_failed" if gw.command_state == "stop_pending" else "resume_failed"
        changed |= set_command_state(gw, failed, due, "command_not_acknowledged_in_10m", [str(cmd.command_id)])
    return changed


# --- evidence ------------------------------------------------------------------


def record_qualifying(gw: Gateway, event_time: datetime, at: datetime, evidence_ids=()) -> bool:
    """Qualifying evidence at `event_time`, received at `at`. Returns True if the status changed."""
    if gw.last_qualifying_at is None or event_time > gw.last_qualifying_at:
        gw.last_qualifying_at = event_time
    if gw.status == "new":
        return set_status(gw, "connected", at, "qualifying_evidence", evidence_ids)
    if gw.status == "stale" and at - event_time <= config.STALE_AFTER:
        return set_status(gw, "connected", at, "fresh_qualifying_evidence", evidence_ids)
    if gw.status == "disconnected" and gw.disconnected_since is not None and event_time > gw.disconnected_since:
        return set_status(gw, "connected", at, "qualifying_evidence_after_disconnection", evidence_ids)
    return False


def record_auth_failure(gw: Gateway, event_time: datetime, at: datetime, evidence_ids=()) -> bool:
    if gw.last_auth_failure_at is None or event_time > gw.last_auth_failure_at:
        gw.last_auth_failure_at = event_time
    if gw.status in ("new", "connected", "stale"):
        set_status(gw, "disconnected", at, "auth_failed", evidence_ids)
        gw.disconnected_since = event_time
        return True
    return False  # disconnected keeps its first time; suspended/spare/retired unchanged


# --- operator actions ----------------------------------------------------------


def suspend(gw: Gateway, reason: str, at: datetime) -> None:
    if gw.status in ("retired", "suspended"):
        raise conflict("illegal_action", f"cannot suspend a {gw.status} gateway")
    gw.suspend_reason = reason
    set_status(gw, "suspended", at, "operator_suspend")


def unsuspend(gw: Gateway, at: datetime) -> None:
    if gw.status != "suspended":
        raise conflict("illegal_action", "gateway is not suspended")
    gw.suspend_reason = None
    lq, la = gw.last_qualifying_at, gw.last_auth_failure_at
    if la is not None and (lq is None or la > lq):
        set_status(gw, "disconnected", at, "operator_unsuspend_derived")
        gw.disconnected_since = la
    elif lq is not None and at - lq <= config.STALE_AFTER:
        set_status(gw, "connected", at, "operator_unsuspend_derived")
    elif lq is not None:
        set_status(gw, "stale", at, "operator_unsuspend_derived")
    else:
        set_status(gw, "new", at, "operator_unsuspend_derived")


def mark_spare(gw: Gateway, at: datetime) -> None:
    if gw.status != "new":
        raise conflict("illegal_action", "only a new gateway can be marked spare")
    if gw.sensors.exists():
        raise conflict("illegal_action", "gateway covers sensors")
    set_status(gw, "spare", at, "operator_mark_spare")


def retire(gw: Gateway, at: datetime) -> None:
    if gw.status == "retired":
        raise conflict("illegal_action", "gateway already retired")
    set_status(gw, "retired", at, "operator_retire")


def issue_command(gw: Gateway, type_: str, at: datetime) -> Command:
    if type_ == "stop" and gw.command_state in ("stop_pending", "stopped"):
        raise conflict("illegal_action", f"stop while {gw.command_state}")
    if type_ == "resume" and gw.command_state == "running":
        raise conflict("illegal_action", "resume while running")
    gw.command_seq += 1
    cmd = Command.objects.create(gateway=gw, seq=gw.command_seq, type=type_, issued_at=at)
    set_command_state(gw, f"{type_}_pending", at, f"operator_{type_}", [str(cmd.command_id)])
    return cmd


def ack_command(gw: Gateway, cmd: Command, acked_at: datetime) -> None:
    """Idempotent. Acks of superseded commands are recorded but never change state."""
    if cmd.acked_at is not None:
        return
    cmd.acked_at = acked_at
    cmd.save(update_fields=["acked_at"])
    timeline.for_gateway(
        gw.gateway_id, kind="ack", axis="command", from_value=None, to_value=cmd.type,
        effective_at=acked_at, rule="gateway_acknowledged_command", evidence_ids=[str(cmd.command_id)],
    )
    if cmd.seq != gw.command_seq:
        return
    if cmd.type == "stop" and gw.command_state in ("stop_pending", "stop_failed"):
        set_command_state(gw, "stopped", acked_at, "stop_acknowledged", [str(cmd.command_id)])
    elif cmd.type == "resume" and gw.command_state in ("resume_pending", "resume_failed"):
        set_command_state(gw, "running", acked_at, "resume_acknowledged", [str(cmd.command_id)])
        if gw.collecting_after_stop:
            timeline.for_gateway(
                gw.gateway_id, kind="flag", axis="flags", from_value="collecting_after_stop", to_value=None,
                effective_at=acked_at, rule="resume_acknowledged_clears_flag", evidence_ids=[str(cmd.command_id)],
            )
            gw.collecting_after_stop = False


# --- stop periods --------------------------------------------------------------


def stop_periods(gw: Gateway) -> list[tuple[datetime, datetime | None]]:
    """[(stop acked_at, resume acked_at or None)] in order. The last may be open-ended."""
    periods, open_start = [], None
    for cmd in Command.objects.filter(gateway=gw, acked_at__isnull=False).order_by("seq"):
        if cmd.type == "stop" and open_start is None:
            open_start = cmd.acked_at
        elif cmd.type == "resume" and open_start is not None and cmd.acked_at >= open_start:
            periods.append((open_start, cmd.acked_at))
            open_start = None
    if open_start is not None:
        periods.append((open_start, None))
    return periods


def in_open_stop_period(periods, taken_at: datetime) -> bool:
    return bool(periods) and periods[-1][1] is None and taken_at >= periods[-1][0]


def in_any_stop_period(periods, taken_at: datetime) -> bool:
    return any(start <= taken_at and (end is None or taken_at < end) for start, end in periods)
