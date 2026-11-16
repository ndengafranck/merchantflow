import logging

from django.db import DatabaseError, connection
from django.http import HttpRequest, JsonResponse
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


class HealthCheckView(APIView):
    """Liveness and database readiness for load balancers and monitoring."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    @extend_schema(
        responses={
            200: inline_serializer(
                "Health",
                {"status": serializers.CharField(), "database": serializers.CharField()},
            )
        }
    )
    def get(self, request: Request) -> Response:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except DatabaseError:
            logger.exception("Health check could not reach the database")
            return Response({"status": "degraded", "database": "unavailable"}, status=503)
        return Response({"status": "ok", "database": "ok"})


def csrf_failure(request: HttpRequest, reason: str = "") -> JsonResponse:
    """JSON replacement for Django's HTML CSRF failure page."""
    return JsonResponse(
        {"code": "csrf_failed", "detail": "CSRF verification failed. Reload and try again."},
        status=403,
    )
