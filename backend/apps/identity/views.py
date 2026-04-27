"""Identity context views.

Real auth views (registration, login, organization create/list, SSO) land here as
Phase 1 progresses. The ``ping`` endpoint exists so the API surface and CI smoke
tests have something to hit.
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny])
def ping(_request: Request) -> Response:
    return Response({"context": "identity", "status": "ok"})
