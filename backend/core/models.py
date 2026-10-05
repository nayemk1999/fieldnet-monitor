import uuid

from django.db import models

# --- enums: exact strings the API returns -------------------------------------

GATEWAY_STATUSES = ["new", "spare", "connected", "stale", "disconnected", "suspended", "retired"]
COMMAND_STATES = ["running", "stop_pending", "stopped", "stop_failed", "resume_pending", "resume_failed"]
COVERAGE_CLASSES = ["available", "stopped", "recoverable", "dead"]
SENSOR_COVERAGES = ["available", "stopped", "recoverable", "none"]
LIFECYCLES = ["pending", "active", "dormant", "sampling", "retired", "decommissioned"]
COLLECTIONS = ["readings", "no_readings", "could_not_read", "timed_out", "not_checked", "collection_stopped"]
BATCH_STATES = ["received", "processed", "partially_processed", "retrying", "quarantined"]
SENSOR_TYPES = ["temperature", "rain", "wind"]
CYCLE_OUTCOMES = ["readings", "no_readings", "could_not_read", "timeout"]
TIMELINE_KINDS = ["transition", "correction", "action", "ack", "flag", "rule_change"]


def _choices(values):
    return [(v, v) for v in values]


class TestState(models.Model):
    """Singleton used only in TEST_MODE: the controllable clock and fault injection."""

    id = models.SmallIntegerField(primary_key=True, default=1)
    now = models.DateTimeField(null=True)
    processing_failures = models.IntegerField(default=0)


class Gateway(models.Model):
    gateway_id = models.CharField(primary_key=True, max_length=64)
    name = models.CharField(max_length=200)
    token = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=16, choices=_choices(GATEWAY_STATUSES), default="new")
    status_since = models.DateTimeField()
    command_state = models.CharField(max_length=16, choices=_choices(COMMAND_STATES), default="running")
    command_state_since = models.DateTimeField()
    coverage_class = models.CharField(max_length=16, choices=_choices(COVERAGE_CLASSES), default="recoverable")
    last_heartbeat_at = models.DateTimeField(null=True)
    last_qualifying_at = models.DateTimeField(null=True)
    disconnected_since = models.DateTimeField(null=True)
    last_auth_failure_at = models.DateTimeField(null=True)
    suspend_reason = models.TextField(null=True)
    collecting_after_stop = models.BooleanField(default=False)
    command_seq = models.IntegerField(default=0)
    created_at = models.DateTimeField()


class Sensor(models.Model):
    sensor_id = models.CharField(primary_key=True, max_length=64)
    type = models.CharField(max_length=16, choices=_choices(SENSOR_TYPES))
    lifecycle = models.CharField(max_length=16, choices=_choices(LIFECYCLES), default="pending")
    lifecycle_reason = models.TextField(null=True)
    lifecycle_since = models.DateTimeField()
    coverage = models.CharField(max_length=16, choices=_choices(SENSOR_COVERAGES), default="none")
    collection = models.CharField(max_length=24, choices=_choices(COLLECTIONS), default="not_checked")
    quiet_checked_days = models.IntegerField(default=0)
    sampling_cycles_done = models.IntegerField(default=0)
    next_evaluation_at = models.DateTimeField(null=True)
    decommissioned_at = models.DateTimeField(null=True)
    decommission_reason = models.TextField(null=True)
    # The lifecycle history the server currently believes, as produced by the
    # replay engine. Compared against each new replay to detect corrections.
    history = models.JSONField(default=list)
    gateways = models.ManyToManyField(Gateway, related_name="sensors", blank=True)
    created_at = models.DateTimeField()


class Cycle(models.Model):
    cycle_id = models.CharField(primary_key=True, max_length=64)
    gateway = models.ForeignKey(Gateway, on_delete=models.CASCADE, related_name="cycles")
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField()
    session = models.CharField(max_length=16)
    body_hash = models.CharField(max_length=64)
    ignored = models.JSONField(default=list)
    received_at = models.DateTimeField()


class CycleResult(models.Model):
    cycle = models.ForeignKey(Cycle, on_delete=models.CASCADE, related_name="results")
    gateway = models.ForeignKey(Gateway, on_delete=models.CASCADE)
    sensor = models.ForeignKey(Sensor, on_delete=models.CASCADE, related_name="cycle_results")
    outcome = models.CharField(max_length=16)  # readings, no_readings, could_not_read, timed_out
    batch_id = models.CharField(max_length=64, null=True)
    finished_at = models.DateTimeField()
    # True when the gateway's coverage class was available when this result was applied.
    counts_as_check = models.BooleanField(default=False)

    class Meta:
        indexes = [models.Index(fields=["sensor", "finished_at"])]


class Batch(models.Model):
    batch_id = models.CharField(primary_key=True, max_length=64)
    gateway = models.ForeignKey(Gateway, on_delete=models.CASCADE, related_name="batches")
    sensor_id = models.CharField(max_length=64)
    body = models.JSONField()
    body_hash = models.CharField(max_length=64)
    received_at = models.DateTimeField()
    processing = models.CharField(max_length=24, choices=_choices(BATCH_STATES), default="received")
    attempts = models.IntegerField(default=0)
    next_attempt_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True)
    accepted_count = models.IntegerField(default=0)
    quarantine_reason = models.CharField(max_length=64, null=True)


class Reading(models.Model):
    """An accepted reading. reading_id is globally unique; the first processed version wins."""

    reading_id = models.CharField(primary_key=True, max_length=64)
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name="readings")
    sensor = models.ForeignKey(Sensor, on_delete=models.CASCADE, related_name="readings")
    gateway = models.ForeignKey(Gateway, on_delete=models.CASCADE)
    taken_at = models.DateTimeField()
    value = models.FloatField()
    unit = models.CharField(max_length=8)
    content_hash = models.CharField(max_length=64)

    class Meta:
        indexes = [models.Index(fields=["sensor", "taken_at"])]


class QuarantinedReading(models.Model):
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name="quarantined")
    reading_id = models.CharField(max_length=64, null=True)
    reason = models.CharField(max_length=64)


class Command(models.Model):
    command_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    gateway = models.ForeignKey(Gateway, on_delete=models.CASCADE, related_name="commands")
    seq = models.IntegerField()
    type = models.CharField(max_length=8)  # stop, resume
    issued_at = models.DateTimeField()
    acked_at = models.DateTimeField(null=True)

    class Meta:
        unique_together = [("gateway", "seq")]


class TimelineEntry(models.Model):
    subject_type = models.CharField(max_length=8)  # gateway, sensor
    subject_id = models.CharField(max_length=64)
    seq = models.IntegerField()
    kind = models.CharField(max_length=16, choices=_choices(TIMELINE_KINDS))
    axis = models.CharField(max_length=24)
    from_value = models.CharField(max_length=64, null=True)
    to_value = models.CharField(max_length=64, null=True)
    effective_at = models.DateTimeField()
    recorded_at = models.DateTimeField()
    rule = models.CharField(max_length=64)
    evidence_ids = models.JSONField(default=list)
    detail = models.JSONField(null=True)

    class Meta:
        unique_together = [("subject_type", "subject_id", "seq")]
        indexes = [models.Index(fields=["subject_type", "subject_id", "seq"])]
