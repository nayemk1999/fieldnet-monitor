"""Sensor lifecycle replay.

A sensor's lifecycle is a deterministic function of four inputs: its evidence by
event time, its coverage history, operator actions and the configuration. This
module is that function. It has no database access and no notion of "current
state": every evaluation replays from registration to `now` and returns the whole
transition history. The caller diffs that against what was recorded before
(see core/sensors.py) to append new transitions or a correction.

Same-instant ordering, from the brief: decommission, loss of coverage, readings, timers.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

UTC = timezone.utc
DAY = timedelta(days=1)

# event priorities for same-instant ordering
_P_DECOMMISSION, _P_COVERAGE, _P_READING, _P_DAY, _P_TIMER = 0, 1, 2, 3, 4


@dataclass(frozen=True)
class Reading:
    reading_id: str
    taken_at: datetime


@dataclass(frozen=True)
class Check:
    """One cycle outcome for the sensor."""

    cycle_id: str
    finished_at: datetime
    outcome: str  # readings, no_readings, could_not_read, timed_out
    batch_id: str | None
    counts_as_check: bool  # gateway coverage class was available when applied


@dataclass(frozen=True)
class CoverageChange:
    at: datetime
    coverage: str


@dataclass(frozen=True)
class Decommission:
    at: datetime
    reason: str


@dataclass(frozen=True)
class Config:
    quiet_days: int
    dormant_wait: timedelta
    sampling_window: timedelta
    sampling_cycles: int
    batch_deadline: timedelta


@dataclass
class Result:
    transitions: list[dict]
    lifecycle: str
    lifecycle_reason: str | None
    lifecycle_since: datetime
    quiet_checked_days: int
    sampling_cycles_done: int
    next_evaluation_at: datetime | None


def day_of(t: datetime) -> date:
    return t.astimezone(UTC).date()


def day_start(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


class Availability:
    """Coverage over time, for 'available time' arithmetic."""

    def __init__(self, registered_at: datetime, changes: list[CoverageChange]):
        self.points = [(registered_at, "none")] + [(c.at, c.coverage) for c in sorted(changes, key=lambda c: c.at)]

    def coverage_at(self, t: datetime) -> str:
        cov = "none"
        for at, c in self.points:
            if at <= t:
                cov = c
            else:
                break
        return cov

    def available_until(self, start: datetime, duration: timedelta) -> datetime | None:
        """Instant when `duration` of available time has accrued since `start`,
        assuming the last known coverage persists. None if it never accrues."""
        remaining = duration
        for i, (seg_start, cov) in enumerate(self.points):
            seg_end = self.points[i + 1][0] if i + 1 < len(self.points) else None
            if seg_end is not None and seg_end <= start:
                continue
            if cov != "available":
                continue
            from_ = max(seg_start, start)
            if seg_end is None or seg_end - from_ >= remaining:
                return from_ + remaining
            remaining -= seg_end - from_
        return None


class _Replay:
    def __init__(self, registered_at, now, readings, checks, batch_resolved_at, coverage_changes, decommission, cfg):
        self.now = now
        self.cfg = cfg
        self.readings = sorted(readings, key=lambda r: r.taken_at)
        self.checks = sorted(checks, key=lambda c: c.finished_at)
        self.batch_resolved_at = batch_resolved_at  # batch_id -> datetime | None; absent = never arrived
        self.coverage_changes = sorted((c for c in coverage_changes if c.at <= now), key=lambda c: c.at)
        self.decommission = decommission
        self.avail = Availability(registered_at, self.coverage_changes)
        self.readings_by_day: dict[date, list[Reading]] = {}
        for r in self.readings:
            self.readings_by_day.setdefault(day_of(r.taken_at), []).append(r)
        self.checks_by_day: dict[date, list[Check]] = {}
        for c in self.checks:
            self.checks_by_day.setdefault(day_of(c.finished_at), []).append(c)

        self.state, self.reason, self.since = "pending", None, registered_at
        self.quiet, self.cycles = 0, 0
        self.transitions: list[dict] = []
        self.wait_start: datetime | None = None
        self.window_start: datetime | None = None
        self.day_ptr = day_of(registered_at)
        self.ri = self.ci = 0
        self.decommissioned = False

    # -- helpers ----------------------------------------------------------------

    def _move(self, to, at, rule, evidence_ids=(), reason=None):
        self.transitions.append(
            {
                "effective_at": at.isoformat(),
                "from": self.state,
                "to": to,
                "reason": reason,
                "rule": rule,
                "evidence_ids": list(evidence_ids),
            }
        )
        if to != self.state:
            self.since = at
        self.state, self.reason = to, reason
        if to == "pending":
            self.quiet, self.cycles = 0, 0
        elif to == "active":
            self.cycles = 0

    def _resolution_time(self, check: Check) -> datetime | None:
        """When the batch behind a readings outcome resolved; None if still unresolved."""
        if check.batch_id in self.batch_resolved_at and self.batch_resolved_at[check.batch_id] is not None:
            return self.batch_resolved_at[check.batch_id]
        deadline = check.finished_at + self.cfg.batch_deadline
        return deadline if deadline <= self.now else None

    def _classify_day(self, d: date) -> tuple[str, datetime | None]:
        """(reading|quiet|unchecked|unresolved, time the class became knowable)."""
        boundary = day_start(d) + DAY
        if d in self.readings_by_day:
            return "reading", boundary
        knowable = boundary
        checks = self.checks_by_day.get(d, [])
        for c in checks:
            if c.outcome == "readings":
                r = self._resolution_time(c)
                if r is None:
                    return "unresolved", None
                knowable = max(knowable, r)
        if any(c.outcome == "no_readings" and c.counts_as_check for c in checks):
            return "quiet", knowable
        return "unchecked", knowable

    def _window_end(self) -> tuple[datetime | None, datetime | None]:
        """(window end, time its outcome is knowable). Blocked while a readings outcome inside is unresolved."""
        end = self.avail.available_until(self.window_start, self.cfg.sampling_window)
        if end is None or end > self.now:
            return end, None
        knowable = end
        for c in self.checks:
            if self.window_start <= c.finished_at < end and c.outcome == "readings":
                r = self._resolution_time(c)
                if r is None:
                    return end, None
                knowable = max(knowable, r)
        return end, knowable

    # -- event loop -------------------------------------------------------------

    def _next_event(self):
        c = []
        if self.decommission and not self.decommissioned and self.decommission.at <= self.now:
            c.append((self.decommission.at, _P_DECOMMISSION, "decommission"))
        if self.ci < len(self.coverage_changes):
            c.append((self.coverage_changes[self.ci].at, _P_COVERAGE, "coverage"))
        if self.ri < len(self.readings) and self.readings[self.ri].taken_at <= self.now:
            c.append((self.readings[self.ri].taken_at, _P_READING, "reading"))
        if day_start(self.day_ptr) + DAY <= self.now:
            cls, knowable = self._classify_day(self.day_ptr)
            if cls != "unresolved":
                c.append((knowable, _P_DAY, "day"))
        if self.state == "dormant":
            end = self.avail.available_until(self.wait_start, self.cfg.dormant_wait)
            if end is not None and end <= self.now:
                c.append((end, _P_TIMER, "wait_end"))
        elif self.state == "sampling":
            end, knowable = self._window_end()
            if knowable is not None:
                c.append((knowable, _P_TIMER, "window_end"))
        return min(c) if c else None

    def run(self) -> Result:
        while not self.decommissioned:
            ev = self._next_event()
            if ev is None:
                break
            getattr(self, f"_on_{ev[2]}")()
        return self._result()

    def _on_decommission(self):
        self._move("decommissioned", self.decommission.at, "operator_decommission", reason=self.decommission.reason)
        self.decommissioned = True

    def _on_coverage(self):
        change = self.coverage_changes[self.ci]
        self.ci += 1
        if change.coverage == "none" and self.state not in ("pending", "decommissioned"):
            self._move("retired", change.at, "no_live_coverage", reason="no_live_coverage")
        elif change.coverage != "none" and self.state == "retired" and self.reason == "no_live_coverage":
            self._move("pending", change.at, "coverage_restored")

    def _on_reading(self):
        r = self.readings[self.ri]
        self.ri += 1
        wakes = self.state in ("pending", "dormant", "sampling") or (self.state == "retired" and self.reason == "no_readings")
        if wakes:
            self._move("active", r.taken_at, "reading_taken", [r.reading_id])
            if self.avail.coverage_at(r.taken_at) == "none":
                self._move("retired", r.taken_at, "no_live_coverage", [r.reading_id], reason="no_live_coverage")

    def _on_day(self):
        d = self.day_ptr
        self.day_ptr = d + DAY
        cls, _ = self._classify_day(d)
        if cls == "reading":
            self.quiet = 0
        elif cls == "quiet" and self.state == "active":
            self.quiet += 1
            if self.quiet >= self.cfg.quiet_days:
                boundary = day_start(d) + DAY
                ids = [c.cycle_id for c in self.checks_by_day.get(d, []) if c.outcome == "no_readings"]
                self._move("dormant", boundary, f"{self.cfg.quiet_days}_quiet_days_completed", ids)
                self.wait_start = boundary

    def _on_wait_end(self):
        end = self.avail.available_until(self.wait_start, self.cfg.dormant_wait)
        self._move("sampling", end, "dormant_wait_completed")
        self.window_start = end

    def _on_window_end(self):
        end, _ = self._window_end()
        checked = [
            c.cycle_id
            for c in self.checks
            if self.window_start <= c.finished_at < end and c.outcome == "no_readings" and c.counts_as_check
        ]
        if not checked:
            self._move("sampling", end, "sampling_window_restarted_without_checks")
            self.window_start = end
            return
        self.cycles += 1
        if self.cycles >= self.cfg.sampling_cycles:
            self._move("retired", end, "sampling_cycles_exhausted", checked, reason="no_readings")
        else:
            self._move("dormant", end, "sampling_window_ended_without_reading", checked)
            self.wait_start = end

    def _result(self) -> Result:
        next_eval = None
        if self.state == "dormant":
            next_eval = self.avail.available_until(self.wait_start, self.cfg.dormant_wait)
        elif self.state == "sampling":
            next_eval = self.avail.available_until(self.window_start, self.cfg.sampling_window)
        if self.avail.coverage_at(self.now) != "available":
            next_eval = None  # paused
        return Result(
            transitions=self.transitions,
            lifecycle=self.state,
            lifecycle_reason=self.reason,
            lifecycle_since=self.since,
            quiet_checked_days=self.quiet,
            sampling_cycles_done=self.cycles,
            next_evaluation_at=next_eval,
        )


def replay(
    *,
    registered_at: datetime,
    now: datetime,
    readings: list[Reading],
    checks: list[Check],
    batch_resolved_at: dict[str, datetime | None],
    coverage_changes: list[CoverageChange],
    decommission: Decommission | None,
    cfg: Config,
) -> Result:
    return _Replay(registered_at, now, readings, checks, batch_resolved_at, coverage_changes, decommission, cfg).run()
