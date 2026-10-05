"""Test endpoints. Mounted only when TEST_MODE=1 (see core/api/urls.py)."""
from django.db import transaction
from rest_framework.response import Response
from rest_framework.views import APIView

from core import clock, jobs
from core.api.serializers import ClockIn, FaultsIn, validate
from core.errors import conflict
from core.models import (
    Batch, Command, Cycle, CycleResult, Gateway, QuarantinedReading, Reading, Sensor, TestState, TimelineEntry,
)


class ResetView(APIView):
    def post(self, request):
        with transaction.atomic():
            for model in (TimelineEntry, QuarantinedReading, Reading, CycleResult, Cycle, Batch, Command, Sensor, Gateway, TestState):
                model.objects.all().delete()
        return Response(status=204)


class ClockView(APIView):
    def post(self, request):
        new = validate(ClockIn, request.data)["now"]
        current = TestState.objects.filter(pk=1).values_list("now", flat=True).first()
        if current is not None and new < current:
            raise conflict("clock_backwards", f"clock is at {current.isoformat()}; it only moves forward")
        clock.set_now(new)
        jobs.run_due(new)
        return Response({"now": new})


class DrainView(APIView):
    def post(self, request):
        now = clock.now()
        jobs.run_due(now)
        return Response({"now": now})


class FaultsView(APIView):
    def post(self, request):
        n = validate(FaultsIn, request.data)["processing_failures"]
        TestState.objects.update_or_create(pk=1, defaults={"processing_failures": n})
        return Response({"processing_failures": n})
