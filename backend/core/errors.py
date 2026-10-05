"""Uniform error envelope: {"error": "<code>", "detail": "<text>"}."""
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_handler


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


def not_found(what: str, ident: str) -> ApiError:
    return ApiError(404, "not_found", f"{what} {ident!r} not found")


def conflict(code: str, detail: str) -> ApiError:
    return ApiError(409, code, detail)


def _flatten(detail) -> str:
    if isinstance(detail, dict):
        return "; ".join(f"{k}: {_flatten(v)}" for k, v in detail.items())
    if isinstance(detail, list):
        return ", ".join(_flatten(v) for v in detail)
    return str(detail)


def exception_handler(exc, context):
    if isinstance(exc, ApiError):
        return Response({"error": exc.code, "detail": exc.detail}, status=exc.status_code)
    if isinstance(exc, (exceptions.ValidationError, exceptions.ParseError)):
        return Response(
            {"error": "validation_error", "detail": _flatten(exc.detail)},
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    if isinstance(exc, (Http404, exceptions.NotFound)):
        return Response({"error": "not_found", "detail": str(exc)}, status=404)
    if isinstance(exc, exceptions.MethodNotAllowed):
        return Response({"error": "method_not_allowed", "detail": str(exc.detail)}, status=405)
    response = drf_handler(exc, context)
    if response is not None:
        response.data = {"error": "error", "detail": _flatten(response.data)}
    return response
