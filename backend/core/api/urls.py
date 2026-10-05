from django.conf import settings
from django.urls import path

from core.api import console, gw, ops, testing

urlpatterns = [
    # gateway API
    path("gw/v1/heartbeat", gw.HeartbeatView.as_view()),
    path("gw/v1/cycles", gw.CyclesView.as_view()),
    path("gw/v1/batches/<str:batch_id>", gw.BatchView.as_view()),
    path("gw/v1/commands", gw.CommandsView.as_view()),
    path("gw/v1/commands/<str:command_id>/ack", gw.AckView.as_view()),
    # operator and state API
    path("api/v1/gateways", ops.GatewaysView.as_view()),
    path("api/v1/gateways/<str:gateway_id>", ops.GatewayDetailView.as_view()),
    path("api/v1/gateways/<str:gateway_id>/actions", ops.GatewayActionsView.as_view()),
    path("api/v1/gateways/<str:subject_id>/timeline", ops.GatewayTimelineView.as_view()),
    path("api/v1/sensors", ops.SensorsView.as_view()),
    path("api/v1/sensors/<str:sensor_id>", ops.SensorDetailView.as_view()),
    path("api/v1/sensors/<str:sensor_id>/coverage", ops.SensorCoverageView.as_view()),
    path("api/v1/sensors/<str:sensor_id>/actions", ops.SensorActionsView.as_view()),
    path("api/v1/sensors/<str:subject_id>/timeline", ops.SensorTimelineView.as_view()),
    path("api/v1/batches/<str:batch_id>", ops.BatchDetailView.as_view()),
    # console API
    path("api/v1/console/gateways", console.ConsoleGatewaysView.as_view()),
    path("api/v1/console/sensors", console.ConsoleSensorsView.as_view()),
    path("api/v1/console/summary", console.ConsoleSummaryView.as_view()),
]

if settings.TEST_MODE:
    urlpatterns += [
        path("test/reset", testing.ResetView.as_view()),
        path("test/clock", testing.ClockView.as_view()),
        path("test/drain", testing.DrainView.as_view()),
        path("test/faults", testing.FaultsView.as_view()),
        path("test/gateways/<str:gateway_id>/token", testing.GatewayTokenView.as_view()),
    ]
