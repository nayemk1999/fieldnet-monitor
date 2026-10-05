"""Shared request-processing steps (brief: process every gateway request in this order:
update the gateway, recompute coverage, then apply evidence to sensors)."""
from datetime import datetime

from core import config, coverage, gateways, sensors
from core.errors import ApiError
from core.models import Gateway, Sensor


def check_device_time(value: datetime, at: datetime) -> None:
    if value > at + config.DEVICE_CLOCK_SKEW:
        raise ApiError(422, "invalid_timestamp", "device timestamp is more than 5 minutes after received time")


def refresh_gateway(gw: Gateway, at: datetime) -> list[Sensor]:
    """Save the gateway, re-derive its coverage class and recompute the sensors it covers.
    Returns the sensors whose coverage changed."""
    gw.save()
    if gateways.refresh_coverage_class(gw, at):
        gw.save()
        return coverage.recompute_for_gateway(gw, at)
    return []


def evaluate_sensors(changed: list[Sensor], at: datetime, evidence: dict[str, list[str]] | None = None) -> None:
    """Replay every sensor whose coverage changed or that received evidence."""
    evidence = evidence or {}
    affected = {s.sensor_id: s for s in changed}
    for sensor_id in evidence:
        affected.setdefault(sensor_id, Sensor.objects.get(pk=sensor_id))
    for sensor_id, sensor in affected.items():
        sensors.evaluate(sensor, at, evidence.get(sensor_id, []))


def finish_gateway_request(gw: Gateway, at: datetime, evidence: dict[str, list[str]] | None = None) -> None:
    evaluate_sensors(refresh_gateway(gw, at), at, evidence)
