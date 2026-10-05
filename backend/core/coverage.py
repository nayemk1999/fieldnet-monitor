"""Sensor coverage: the best class among covering gateways (brief: Coverage)."""
from datetime import datetime

from core import timeline
from core.models import Gateway, Sensor

_ORDER = ["available", "stopped", "recoverable"]


def sensor_coverage(sensor: Sensor) -> str:
    classes = set(sensor.gateways.values_list("coverage_class", flat=True))
    for c in _ORDER:
        if c in classes:
            return c
    return "none"


def recompute_sensor(sensor: Sensor, at: datetime) -> bool:
    new = sensor_coverage(sensor)
    if new == sensor.coverage:
        return False
    timeline.for_sensor(
        sensor.sensor_id, kind="transition", axis="coverage", from_value=sensor.coverage, to_value=new,
        effective_at=at, rule="coverage_recomputed",
    )
    sensor.coverage = new
    sensor.save(update_fields=["coverage"])
    return True


def recompute_for_gateway(gw: Gateway, at: datetime) -> list[Sensor]:
    """Recompute every sensor the gateway covers. Returns the sensors whose coverage changed."""
    return [s for s in gw.sensors.all() if recompute_sensor(s, at)]
