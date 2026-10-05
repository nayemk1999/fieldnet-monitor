"""Console API: list endpoints shaped for the Fleet and Sensors pages. See docs/console-api.md."""
from django.db.models import Count
from rest_framework.response import Response
from rest_framework.views import APIView

from core import clock
from core.api.state import gateway_state, sensor_state
from core.models import GATEWAY_STATUSES, LIFECYCLES, Gateway, Sensor


class ConsoleGatewaysView(APIView):
    def get(self, request):
        now = clock.now()
        qs = Gateway.objects.annotate(sensor_count=Count("sensors")).order_by("gateway_id")
        if status := request.query_params.get("status"):
            qs = qs.filter(status__in=status.split(","))
        rows = []
        for gw in qs:
            row = gateway_state(gw)
            row["status_held_seconds"] = int((now - gw.status_since).total_seconds())
            row["sensor_count"] = gw.sensor_count
            row["suspend_reason"] = gw.suspend_reason
            rows.append(row)
        return Response({"now": now, "items": rows})


class ConsoleSensorsView(APIView):
    def get(self, request):
        now = clock.now()
        qs = Sensor.objects.prefetch_related("gateways").order_by("sensor_id")
        if lifecycle := request.query_params.get("lifecycle"):
            qs = qs.filter(lifecycle__in=lifecycle.split(","))
        if coverage := request.query_params.get("coverage"):
            qs = qs.filter(coverage__in=coverage.split(","))
        rows = []
        for s in qs:
            row = sensor_state(s)
            row["gateway_ids"] = [g.gateway_id for g in s.gateways.all()]
            row["paused"] = s.lifecycle in ("dormant", "sampling") and s.next_evaluation_at is None
            rows.append(row)
        return Response({"now": now, "items": rows})


class ConsoleSummaryView(APIView):
    def get(self, request):
        by_status = {k: 0 for k in GATEWAY_STATUSES}
        by_status.update({r["status"]: r["n"] for r in Gateway.objects.values("status").annotate(n=Count("pk"))})
        by_lifecycle = {k: 0 for k in LIFECYCLES}
        by_lifecycle.update({r["lifecycle"]: r["n"] for r in Sensor.objects.values("lifecycle").annotate(n=Count("pk"))})
        return Response({"now": clock.now(), "gateways": by_status, "sensors": by_lifecycle})
