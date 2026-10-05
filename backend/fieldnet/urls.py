from django.http import JsonResponse
from django.urls import include, path

urlpatterns = [
    path("", include("core.api.urls")),
]


def handler404(request, exception=None):
    return JsonResponse({"error": "not_found", "detail": f"no route for {request.path}"}, status=404)


def handler500(request):
    return JsonResponse({"error": "internal_error", "detail": "unexpected server error"}, status=500)
