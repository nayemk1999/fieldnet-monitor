"""Batch intake and background processing (brief: Batch processing)."""
import hashlib
import json
import logging
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import F
from django.utils.dateparse import parse_datetime

from core import config, coverage, gateways, timeline
from core.errors import conflict
from core.models import Batch, Gateway, QuarantinedReading, Reading, Sensor, TestState

log = logging.getLogger(__name__)


def body_hash(body) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def receive(gw: Gateway, batch_id: str, body: dict, at: datetime) -> int:
    """Store the batch for background processing. Returns the HTTP status to answer with."""
    h = body_hash(body)
    existing = Batch.objects.filter(pk=batch_id).first()
    if existing is not None:
        if existing.body_hash == h and existing.gateway_id == gw.gateway_id:
            return 200
        raise conflict("batch_conflict", f"batch {batch_id!r} already exists with a different body or gateway")
    Batch.objects.create(
        batch_id=batch_id, gateway=gw, sensor_id=body["sensor_id"], body=body, body_hash=h,
        received_at=at, next_attempt_at=at,
    )
    return 202


# --- processing ----------------------------------------------------------------


def _consume_fault() -> bool:
    """TEST_MODE fault injection: the next n attempts fail."""
    return TestState.objects.filter(pk=1, processing_failures__gt=0).update(
        processing_failures=F("processing_failures") - 1
    ) > 0


def _record_failure(batch_id: str, attempts: int, at: datetime) -> None:
    batch = Batch.objects.get(pk=batch_id)
    batch.attempts = attempts
    if attempts >= config.MAX_PROCESSING_ATTEMPTS:
        batch.processing, batch.quarantine_reason, batch.resolved_at = "quarantined", "processing_failed", at
        QuarantinedReading.objects.create(batch=batch, reading_id=None, reason="processing_failed")
    else:
        batch.processing = "retrying"
        batch.next_attempt_at = at + timedelta(minutes=2 ** (attempts - 1))
    batch.save()


def process(batch: Batch, at: datetime) -> None:
    """One processing attempt at server time `at`. Safe to repeat: a failed attempt rolls back."""
    attempts = batch.attempts + 1
    if _consume_fault():
        _record_failure(batch.batch_id, attempts, at)
        return
    try:
        with transaction.atomic():
            batch.attempts = attempts
            _apply(batch, at)
    except Exception:  # processing itself failed: retry with backoff
        log.exception("batch %s attempt %d failed", batch.batch_id, attempts)
        _record_failure(batch.batch_id, attempts, at)


def _validate_reading(item, expected_unit: str, received_at: datetime):
    """Returns (taken_at, value, unit) or raises ValueError(reason)."""
    if not isinstance(item, dict):
        raise ValueError("invalid_reading")
    for field in ("reading_id", "taken_at", "value", "unit"):
        if field not in item or item[field] is None:
            raise ValueError(f"missing_{field}")
    value = item["value"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("value_not_a_number")
    if item["unit"] != expected_unit:
        raise ValueError("wrong_unit")
    taken_at = parse_datetime(str(item["taken_at"]))
    if taken_at is None or taken_at.tzinfo is None:
        raise ValueError("invalid_taken_at")
    if taken_at > received_at + config.DEVICE_CLOCK_SKEW:
        raise ValueError("taken_at_in_future")
    return taken_at, float(value), item["unit"]


def _apply(batch: Batch, at: datetime) -> None:
    sensor = Sensor.objects.filter(pk=batch.sensor_id).first()
    if sensor is None:
        QuarantinedReading.objects.create(batch=batch, reading_id=None, reason="unknown_sensor")
        batch.processing, batch.quarantine_reason, batch.resolved_at = "quarantined", "unknown_sensor", at
        batch.save()
        return
    expected_unit = config.UNITS_BY_SENSOR_TYPE[sensor.type]
    accepted: list[tuple[str, datetime]] = []
    quarantined = 0
    for item in batch.body.get("readings", []):
        rid = str(item.get("reading_id")) if isinstance(item, dict) and item.get("reading_id") is not None else None
        try:
            taken_at, value, unit = _validate_reading(item, expected_unit, batch.received_at)
        except ValueError as e:
            QuarantinedReading.objects.create(batch=batch, reading_id=rid, reason=str(e))
            quarantined += 1
            continue
        content = body_hash({"taken_at": taken_at.isoformat(), "value": value, "unit": unit})
        existing = Reading.objects.filter(pk=rid).first()
        if existing is not None:
            if existing.content_hash != content:
                QuarantinedReading.objects.create(batch=batch, reading_id=rid, reason="conflicting_duplicate")
                quarantined += 1
            continue  # same id, same content: ignored
        Reading.objects.create(
            reading_id=rid, batch=batch, sensor=sensor, gateway=batch.gateway, taken_at=taken_at,
            value=value, unit=unit, content_hash=content,
        )
        accepted.append((rid, taken_at))

    if accepted:
        batch.processing = "processed" if quarantined == 0 else "partially_processed"
    elif quarantined or not batch.body.get("readings"):
        batch.processing, batch.quarantine_reason = "quarantined", "all_readings_invalid"
    else:
        batch.processing = "processed"  # only already-known duplicates: nothing new, nothing wrong
    batch.accepted_count = len(accepted)
    batch.resolved_at = at
    batch.save()
    if accepted:
        _apply_to_gateway(batch, accepted, at)


def _apply_to_gateway(batch: Batch, accepted: list[tuple[str, datetime]], at: datetime) -> None:
    gw = Gateway.objects.select_for_update().get(pk=batch.gateway_id)
    gateways.apply_due(gw, at)
    gateways.record_qualifying(gw, max(t for _, t in accepted), at, [batch.batch_id])
    periods = gateways.stop_periods(gw)
    inside = [rid for rid, t in accepted if gateways.in_any_stop_period(periods, t)]
    if inside:
        timeline.for_gateway(
            gw.gateway_id, kind="flag", axis="flags", from_value=None, to_value="collecting_after_stop",
            effective_at=at, rule="readings_taken_inside_stop_period", evidence_ids=inside,
        )
        if any(gateways.in_open_stop_period(periods, t) for rid, t in accepted if rid in inside):
            gw.collecting_after_stop = True
    gw.save()
    if gateways.refresh_coverage_class(gw, at):
        gw.save()
        coverage.recompute_for_gateway(gw, at)
