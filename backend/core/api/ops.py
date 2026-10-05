"""Operator and state API (brief: Operator and state API)."""
import secrets

from django.db import transaction
from rest_framework.response import Response
from rest_framework.views import APIView

from core import clock, coverage, engine, gateways, sensors, timeline
from core.api.serializers import (
    CoverageIn, GatewayActionIn, GatewayRegisterIn, SensorActionIn, SensorRegisterIn, validate,
)
from core.api.state import gateway_state, sensor_state, timeline_entry
from core.errors import conflict, not_found
from core.models import Batch, Gateway, Sensor, TimelineEntry


def _gateway(gateway_id) -> Gateway:
    gw = Gateway.objects.filter(pk=gateway_id).first()
    if gw is None:
        raise not_found("gateway", gateway_id)
    return gw


def _sensor(sensor_id) -> Sensor:
    s = Sensor.objects.filter(pk=sensor_id).first()
    if s is None:
        raise not_found("sensor", sensor_id)
    return s


class GatewaysView(APIView):
    def post(self, request):
        data, at = validate(GatewayRegisterIn, request.data), clock.now()
        if Gateway.objects.filter(pk=data["gateway_id"]).exists():
            raise conflict("duplicate_gateway", f"gateway {data['gateway_id']!r} already registered")
        gw = Gateway.objects.create(
            gateway_id=data["gateway_id"], name=data["name"], token=secrets.token_urlsafe(32),
            status_since=at, command_state_since=at, coverage_class=gateways.coverage_class("new", "running"),
            created_at=at,
        )
        timeline.for_gateway(gw.gateway_id, kind="transition", axis="status", from_value=None, to_value="new",
                             effective_at=at, rule="registered")
        return Response({"token": gw.token}, status=201)


class GatewayDetailView(APIView):
    def get(self, request, gateway_id):
        return Response(gateway_state(_gateway(gateway_id)))


class GatewayActionsView(APIView):
    def post(self, request, gateway_id):
        data, at = validate(GatewayActionIn, request.data), clock.now()
        action, reason = data["action"], data.get("reason") or None
        with transaction.atomic():
            gw = Gateway.objects.select_for_update().filter(pk=gateway_id).first()
            if gw is None:
                raise not_found("gateway", gateway_id)
            if gw.status == "retired":
                raise conflict("illegal_action", "gateway is retired")
            gateways.apply_due(gw, at)
            timeline.for_gateway(gw.gateway_id, kind="action", axis="operator", from_value=None, to_value=action,
                                 effective_at=at, rule="operator_action", detail={"reason": reason} if reason else None)
            if action == "suspend":
                gateways.suspend(gw, reason, at)
            elif action == "unsuspend":
                gateways.unsuspend(gw, at)
            elif action == "mark_spare":
                gateways.mark_spare(gw, at)
            elif action == "retire":
                gateways.retire(gw, at)
            else:
                gateways.issue_command(gw, action, at)
            engine.finish_gateway_request(gw, at)
        return Response(gateway_state(gw))


class SensorsView(APIView):
    def post(self, request):
        data, at = validate(SensorRegisterIn, request.data), clock.now()
        if Sensor.objects.filter(pk=data["sensor_id"]).exists():
            raise conflict("duplicate_sensor", f"sensor {data['sensor_id']!r} already registered")
        s = Sensor.objects.create(sensor_id=data["sensor_id"], type=data["type"], lifecycle_since=at, created_at=at)
        timeline.for_sensor(s.sensor_id, kind="transition", axis="lifecycle", from_value=None, to_value="pending",
                            effective_at=at, rule="registered")
        return Response(sensor_state(s), status=201)


class SensorDetailView(APIView):
    def get(self, request, sensor_id):
        return Response(sensor_state(_sensor(sensor_id)))


class SensorCoverageView(APIView):
    def put(self, request, sensor_id):
        data, at = validate(CoverageIn, request.data), clock.now()
        with transaction.atomic():
            s = _sensor(sensor_id)
            if s.lifecycle == "decommissioned":
                raise conflict("illegal_action", "sensor is decommissioned")
            gws = []
            for gid in dict.fromkeys(data["gateway_ids"]):
                gw = _gateway(gid)
                if gw.status == "retired":
                    raise conflict("retired_gateway", f"gateway {gid!r} is retired")
                gws.append(gw)
            s.gateways.set(gws)
            timeline.for_sensor(s.sensor_id, kind="action", axis="operator", from_value=None, to_value="set_coverage",
                                effective_at=at, rule="operator_action", detail={"gateway_ids": [g.gateway_id for g in gws]})
            for gw in gws:
                if gw.status == "spare":
                    gateways.set_status(gw, "new", at, "sensor_assigned")
                    engine.finish_gateway_request(gw, at)
            coverage.recompute_sensor(s, at)
            sensors.evaluate(s, at)
        return Response(sensor_state(s))


class SensorActionsView(APIView):
    def post(self, request, sensor_id):
        data, at = validate(SensorActionIn, request.data), clock.now()
        with transaction.atomic():
            s = _sensor(sensor_id)
            if s.lifecycle == "decommissioned":
                raise conflict("illegal_action", "sensor is decommissioned")
            s.decommissioned_at, s.decommission_reason = at, data["reason"]
            s.save(update_fields=["decommissioned_at", "decommission_reason"])
            timeline.for_sensor(s.sensor_id, kind="action", axis="operator", from_value=None, to_value="decommission",
                                effective_at=at, rule="operator_action", detail={"reason": data["reason"]})
            sensors.evaluate(s, at)
        return Response(sensor_state(s))


class TimelineView(APIView):
    subject_type = ""

    def get(self, request, subject_id):
        (_gateway if self.subject_type == "gateway" else _sensor)(subject_id)
        entries = TimelineEntry.objects.filter(subject_type=self.subject_type, subject_id=subject_id).order_by("seq")
        return Response([timeline_entry(e) for e in entries])


class GatewayTimelineView(TimelineView):
    subject_type = "gateway"


class SensorTimelineView(TimelineView):
    subject_type = "sensor"


class BatchDetailView(APIView):
    def get(self, request, batch_id):
        b = Batch.objects.filter(pk=batch_id).first()
        if b is None:
            raise not_found("batch", batch_id)
        return Response(
            {
                "processing": b.processing,
                "attempts": b.attempts,
                "accepted_count": b.accepted_count,
                "quarantined": [{"reading_id": q.reading_id, "reason": q.reason} for q in b.quarantined.all()],
            }
        )
