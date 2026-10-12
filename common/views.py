from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.db import connection
from django.core.cache import cache
from drf_spectacular.utils import extend_schema, OpenApiResponse
import time


class HealthCheckView(APIView):
    """
    Infrastructure healthcheck verifying database, cache, and service availability.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        summary="Service Health Check",
        description="Verifies the operational status of the Web API, PostgreSQL database, and Redis cache.",
        responses={
            200: OpenApiResponse(description="All infrastructure components healthy"),
            503: OpenApiResponse(description="One or more infrastructure services unavailable"),
        },
    )
    def get(self, request):
        start_time = time.time()
        status_data = {
            "status": "healthy",
            "service": "Many Gym Web API",
            "timestamp": time.time(),
            "components": {
                "database": "unknown",
                "redis_cache": "unknown",
            },
        }

        is_healthy = True

        # Database Check
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1;")
                cursor.fetchone()
            status_data["components"]["database"] = "healthy"
        except Exception as e:
            status_data["components"]["database"] = f"unhealthy: {str(e)}"
            is_healthy = False

        # Redis Cache Check
        try:
            cache_key = "_health_check_ping"
            cache.set(cache_key, "pong", timeout=10)
            val = cache.get(cache_key)
            if val == "pong":
                status_data["components"]["redis_cache"] = "healthy"
            else:
                status_data["components"]["redis_cache"] = "unhealthy: cache value mismatch"
                is_healthy = False
        except Exception as e:
            status_data["components"]["redis_cache"] = f"unhealthy: {str(e)}"
            is_healthy = False

        status_data["latency_ms"] = round((time.time() - start_time) * 1000, 2)

        if not is_healthy:
            status_data["status"] = "degraded"
            return Response(status_data, status=503)

        return Response(status_data, status=200)
