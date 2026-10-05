"""Append-only timeline. Entries are never edited or deleted."""
from datetime import datetime

from django.db.models import Max

from core import clock
from core.models import TimelineEntry


def append(
    subject_type: str,
    subject_id: str,
    *,
    kind: str,
    axis: str,
    from_value,
    to_value,
    effective_at: datetime,
    rule: str,
    evidence_ids=None,
    detail=None,
) -> TimelineEntry:
    last = (
        TimelineEntry.objects.filter(subject_type=subject_type, subject_id=subject_id)
        .aggregate(m=Max("seq"))["m"]
        or 0
    )
    return TimelineEntry.objects.create(
        subject_type=subject_type,
        subject_id=subject_id,
        seq=last + 1,
        kind=kind,
        axis=axis,
        from_value=from_value,
        to_value=to_value,
        effective_at=effective_at,
        recorded_at=clock.now(),
        rule=rule,
        evidence_ids=list(evidence_ids or []),
        detail=detail,
    )


def for_gateway(gateway_id: str, **kw) -> TimelineEntry:
    return append("gateway", gateway_id, **kw)


def for_sensor(sensor_id: str, **kw) -> TimelineEntry:
    return append("sensor", sensor_id, **kw)
