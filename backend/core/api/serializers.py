"""Request body validation. Invalid bodies become 422 via core.errors."""
from rest_framework import serializers

from core.models import CYCLE_OUTCOMES, SENSOR_TYPES


class HeartbeatIn(serializers.Serializer):
    sent_at = serializers.DateTimeField()
    session = serializers.ChoiceField(["ok", "auth_failed"])


class CycleResultIn(serializers.Serializer):
    sensor_id = serializers.CharField()
    outcome = serializers.ChoiceField(CYCLE_OUTCOMES)
    batch_id = serializers.CharField(required=False, allow_null=True)

    def validate(self, data):
        has_batch = data.get("batch_id") is not None
        if data["outcome"] == "readings" and not has_batch:
            raise serializers.ValidationError("batch_id is required when outcome is readings")
        if data["outcome"] != "readings" and has_batch:
            raise serializers.ValidationError("batch_id must be absent unless outcome is readings")
        return data


class CycleIn(serializers.Serializer):
    cycle_id = serializers.CharField()
    started_at = serializers.DateTimeField()
    finished_at = serializers.DateTimeField()
    session = serializers.ChoiceField(["ok", "auth_failed"])
    results = CycleResultIn(many=True)


class BatchIn(serializers.Serializer):
    # Per-reading validity is a processing concern (quarantine), not a 422.
    sensor_id = serializers.CharField()
    readings = serializers.ListField(child=serializers.DictField(), allow_empty=True)


class AckIn(serializers.Serializer):
    acked_at = serializers.DateTimeField()


class GatewayRegisterIn(serializers.Serializer):
    gateway_id = serializers.CharField(max_length=64)
    name = serializers.CharField(max_length=200)


class SensorRegisterIn(serializers.Serializer):
    sensor_id = serializers.CharField(max_length=64)
    type = serializers.ChoiceField(SENSOR_TYPES)


class CoverageIn(serializers.Serializer):
    gateway_ids = serializers.ListField(child=serializers.CharField(), allow_empty=True)


class GatewayActionIn(serializers.Serializer):
    action = serializers.ChoiceField(["suspend", "unsuspend", "mark_spare", "retire", "stop", "resume"])
    reason = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def validate(self, data):
        if data["action"] == "suspend" and not data.get("reason"):
            raise serializers.ValidationError("reason is required for suspend")
        return data


class SensorActionIn(serializers.Serializer):
    action = serializers.ChoiceField(["decommission"])
    reason = serializers.CharField()


class ClockIn(serializers.Serializer):
    now = serializers.DateTimeField()


class FaultsIn(serializers.Serializer):
    processing_failures = serializers.IntegerField(min_value=0)


def validate(serializer_class, data):
    s = serializer_class(data=data)
    s.is_valid(raise_exception=True)
    return s.validated_data
