"""Background work: due batches, due gateway timers, then sensor evaluation.

run_due(now) is the single entry point. The worker loop calls it with the real
clock; in TEST_MODE only /test/clock and /test/drain call it. Events are applied
in due-time order, each effective at its own due time.
"""
from datetime import datetime

from django.db import transaction

from core import batches, coverage, gateways, sensors
from core.models import Batch, Gateway, Sensor


def _next_due(now: datetime):
    candidates = []
    batch = (
        Batch.objects.filter(processing__in=["received", "retrying"], next_attempt_at__lte=now)
        .order_by("next_attempt_at", "received_at")
        .first()
    )
    if batch is not None:
        candidates.append((batch.next_attempt_at, 0, "batch", batch.batch_id))
    # ponytail: scans every gateway per step; index a next_due_at column if the fleet grows.
    for gw in Gateway.objects.exclude(status="retired"):
        for due in (gateways.stale_due_at(gw), gateways.command_timeout_due_at(gw)):
            if due is not None and due < now:
                candidates.append((due, 1, "gateway", gw.gateway_id))
    return min(candidates) if candidates else None


def run_due(now: datetime) -> None:
    touched: dict[str, list[str]] = {}
    while True:
        ev = _next_due(now)
        if ev is None:
            break
        at, _, kind, ident = ev
        with transaction.atomic():
            if kind == "batch":
                batch = Batch.objects.select_for_update().get(pk=ident)
                batches.process(batch, at)
                touched.setdefault(batch.sensor_id, []).append(batch.batch_id)
            else:
                gw = Gateway.objects.select_for_update().get(pk=ident)
                # apply_due applies everything whose due time is before `now`, each
                # effective at its own due time; `at` only orders this step.
                if gateways.apply_due(gw, now):
                    gw.save()
                    if gateways.refresh_coverage_class(gw, at):
                        gw.save()
                        coverage.recompute_for_gateway(gw, at)
    for sensor in Sensor.objects.all():
        with transaction.atomic():
            sensors.evaluate(sensor, now, touched.get(sensor.sensor_id, []))
