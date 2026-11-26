from django.db import connection
from django.http import JsonResponse
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    """Liveness check: the API is up and can reach PostgreSQL."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(
        operation_id="health_check",
        responses=inline_serializer(
            name="Health",
            fields={
                "status": serializers.ChoiceField(choices=["ok", "degraded"]),
                "database": serializers.ChoiceField(choices=["ok", "unavailable"]),
            },
        ),
    )
    def get(self, request: Request) -> Response:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            database = "ok"
        except Exception:
            database = "unavailable"
        status = "ok" if database == "ok" else "degraded"
        return Response(
            {"status": status, "database": database}, status=200 if status == "ok" else 503
        )


def csrf_failure(request, reason: str = "") -> JsonResponse:
    """Django's CSRF rejections in the API's error shape, so the app can show them plainly."""
    return JsonResponse(
        {
            "code": "csrf_failed",
            "message": "Your session expired. Reload the page and try again.",
        },
        status=403,
    )
