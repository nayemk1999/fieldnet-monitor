"""Thresholds from the brief. Each can be overridden by environment variable.

The brief lists them as configuration; they are read once at startup.
Runtime changes with rule_change timeline entries are not implemented (see DECISIONS.md).
"""
import os
from datetime import timedelta


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


QUIET_DAYS_BEFORE_DORMANT = _int("QUIET_DAYS_BEFORE_DORMANT", 14)
DORMANT_WAIT = timedelta(days=_int("DORMANT_WAIT_DAYS", 14))
SAMPLING_WINDOW = timedelta(hours=_int("SAMPLING_WINDOW_HOURS", 72))
SAMPLING_CYCLES_BEFORE_RETIRED = _int("SAMPLING_CYCLES_BEFORE_RETIRED", 2)
STALE_AFTER = timedelta(hours=_int("STALE_AFTER_HOURS", 12))
COMMAND_TIMEOUT = timedelta(minutes=_int("COMMAND_TIMEOUT_MINUTES", 10))
BATCH_DEADLINE = timedelta(hours=_int("BATCH_DEADLINE_HOURS", 24))
MAX_PROCESSING_ATTEMPTS = _int("MAX_PROCESSING_ATTEMPTS", 5)
DEVICE_CLOCK_SKEW = timedelta(minutes=5)
COLLECTION_WINDOW = timedelta(hours=24)
WORKER_POLL_SECONDS = _int("WORKER_POLL_SECONDS", 2)

UNITS_BY_SENSOR_TYPE = {"temperature": "C", "rain": "mm", "wind": "m/s"}
