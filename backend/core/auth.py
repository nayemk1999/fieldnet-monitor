from core.errors import ApiError
from core.models import Gateway


def gateway_from_request(request) -> Gateway:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise ApiError(401, "unauthorized", "missing bearer token")
    gw = Gateway.objects.filter(token=header[7:].strip()).first()
    if gw is None:
        raise ApiError(401, "unauthorized", "unknown token")
    if gw.status == "retired":
        raise ApiError(403, "forbidden", "gateway is retired")
    return gw
