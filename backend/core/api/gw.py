"""Gateway API: devices call these with Authorization: Bearer <token>."""
import uuid

from django.db import transaction
from rest_framework.response import Response
from rest_framework.views import APIView

from core import auth, batches, clock, engine, gateways
from core.api.serializers import AckIn, BatchIn, CycleIn, HeartbeatIn, validate
from core.errors import conflict, not_found
from core.models import Command, Cycle, CycleResult, Sensor


class HeartbeatView(APIView):
    def post(self, request):
        gw, at = auth.gateway_from_request(request), clock.now()
        data = validate(HeartbeatIn, request.data)
        engine.check_device_time(data["sent_at"], at)
        with transaction.atomic():
            gateways.apply_due(gw, at)
            gw.last_heartbeat_at = at
            if data["session"] == "auth_failed":
                gateways.record_auth_failure(gw, data["sent_at"], at)
            engine.finish_gateway_request(gw, at)
        return Response(status=204)


class CyclesView(APIView):
    def post(self, request):
        gw, at = auth.gateway_from_request(request), clock.now()
        data = validate(CycleIn, request.data)
        engine.check_device_time(data["finished_at"], at)
        body_hash = batches.body_hash(request.data)
        existing = Cycle.objects.filter(pk=data["cycle_id"]).first()
        if existing is not None:
            if existing.body_hash == body_hash and existing.gateway_id == gw.gateway_id:
                return Response({"ignored": existing.ignored}, status=200)
            raise conflict("cycle_conflict", f"cycle {data['cycle_id']!r} already exists with a different body")

        covered = set(gw.sensors.values_list("sensor_id", flat=True))
        kept = [r for r in data["results"] if r["sensor_id"] in covered]
        ignored = [r["sensor_id"] for r in data["results"] if r["sensor_id"] not in covered]
        auth_failed = data["session"] == "auth_failed"
        finished_at = data["finished_at"]
        with transaction.atomic():
            gateways.apply_due(gw, at)
            if auth_failed:
                gateways.record_auth_failure(gw, finished_at, at, [data["cycle_id"]])
            elif any(r["outcome"] in ("readings", "no_readings") for r in kept):
                gateways.record_qualifying(gw, finished_at, at, [data["cycle_id"]])
            # coverage first, so a stale gateway's first good cycle counts as a check
            changed = engine.refresh_gateway(gw, at)
            cycle = Cycle.objects.create(
                cycle_id=data["cycle_id"], gateway=gw, started_at=data["started_at"], finished_at=finished_at,
                session=data["session"], body_hash=body_hash, ignored=ignored, received_at=at,
            )
            for r in kept:
                outcome = "could_not_read" if auth_failed else ("timed_out" if r["outcome"] == "timeout" else r["outcome"])
                CycleResult.objects.create(
                    cycle=cycle, gateway=gw, sensor_id=r["sensor_id"], outcome=outcome, batch_id=r.get("batch_id"),
                    finished_at=finished_at, counts_as_check=gw.coverage_class == "available",
                )
            evidence = {r["sensor_id"]: [data["cycle_id"]] for r in kept}
            engine.evaluate_sensors(changed, at, evidence)
        return Response({"ignored": ignored}, status=202)


class BatchView(APIView):
    def put(self, request, batch_id):
        gw, at = auth.gateway_from_request(request), clock.now()
        data = validate(BatchIn, request.data)
        status = batches.receive(gw, batch_id, dict(request.data), at)
        return Response({"batch_id": batch_id, "sensor_id": data["sensor_id"]}, status=status)


class CommandsView(APIView):
    def get(self, request):
        gw = auth.gateway_from_request(request)
        latest = gateways.latest_command(gw)
        commands = []
        if latest is not None and latest.acked_at is None:
            commands.append(
                {"command_id": str(latest.command_id), "seq": latest.seq, "type": latest.type, "issued_at": latest.issued_at}
            )
        return Response({"commands": commands})


class AckView(APIView):
    def post(self, request, command_id):
        gw, at = auth.gateway_from_request(request), clock.now()
        try:
            cmd = Command.objects.filter(pk=uuid.UUID(str(command_id)), gateway=gw).first()
        except ValueError:
            cmd = None
        if cmd is None:
            raise not_found("command", command_id)
        data = validate(AckIn, request.data)
        engine.check_device_time(data["acked_at"], at)
        with transaction.atomic():
            gateways.apply_due(gw, at)
            gateways.ack_command(gw, cmd, data["acked_at"])
            engine.finish_gateway_request(gw, at)
        return Response(status=204)
