from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter

from apps.gyms.rest_api.v1.serializers.admin_log_serializers import (
    GymAdminLogSerializer,
    GymAdminLogCreateSerializer,
    GymAdminLogsPaginatedResponseSerializer,
    GymAdminLogsMetricsSerializer,
    AdminLogOptionsResponseSerializer,
)
from apps.gyms.services.admin_log_services import log_admin_action
from apps.gyms.selectors.admin_log_selectors import (
    list_admin_logs,
    get_admin_log_by_id,
    get_admin_logs_metrics,
)
from apps.gyms.rest_api.v1.views.base_views import resolve_gym_context, check_gym_permission
from common.serializers import ErrorDetailSerializer
from common.enums import AdminLogCategory, AdminLogActionType


class GymAdminLogsListView(APIView):
    """
    API endpoint for listing and recording Gym Admin Logs (Alerts & Logs -> Admin Logs).
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Alerts & Logs - Admin Logs"],
        summary="List Admin Logs",
        description="""
### Summary
Retrieves a paginated list of administration audit logs for the specified gym workspace.
Matches the Alerts & Logs sidebar menu UI table:
- **Admin**: Staff member / administrator who executed the action
- **Action**: Human-readable action label (e.g. Updated page information, Published a post, Added an admin)
- **Details**: Change description or item title
- **Date and time**: Timestamp and human-friendly formatted date

### Filtering & Search
- `category`: Filter by module category (e.g. `gym_profile`, `posts`, `access_control`, `visibility`, `members`, `membership_plans`).
- `action_type`: Filter by machine action code (e.g. `update_page_info`, `publish_post`, `add_admin`, `change_page_visibility`).
- `actor_id`: Filter by the UUID of the admin who performed the action.
- `start_date` / `end_date`: Filter by ISO date/datetime range.
- `search`: Full text search matching action, details, or admin name/email.
- `page` / `page_size`: Pagination parameters.
        """,
        parameters=[
            OpenApiParameter(
                name="gym_id",
                description="Target Gym UUID if not using a gym context JWT token.",
                required=False,
                type=str,
            ),
            OpenApiParameter(
                name="category",
                description="Filter by module category.",
                required=False,
                type=str,
            ),
            OpenApiParameter(
                name="action_type",
                description="Filter by action type code.",
                required=False,
                type=str,
            ),
            OpenApiParameter(
                name="actor_id",
                description="Filter by administrator User UUID.",
                required=False,
                type=str,
            ),
            OpenApiParameter(
                name="start_date",
                description="Filter logs created on or after this ISO date/datetime.",
                required=False,
                type=str,
            ),
            OpenApiParameter(
                name="end_date",
                description="Filter logs created on or before this ISO date/datetime.",
                required=False,
                type=str,
            ),
            OpenApiParameter(
                name="search",
                description="Search query matching action, details, admin name or email.",
                required=False,
                type=str,
            ),
            OpenApiParameter(
                name="page",
                description="Page number (default 1).",
                required=False,
                type=int,
            ),
            OpenApiParameter(
                name="page_size",
                description="Number of logs per page (default 20, max 100).",
                required=False,
                type=int,
            ),
        ],
        responses={
            200: OpenApiResponse(response=GymAdminLogsPaginatedResponseSerializer, description="Paginated admin logs."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Permission denied."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Gym not found."),
        },
    )
    def get(self, request):
        gym = resolve_gym_context(request)
        check_gym_permission(request, gym, required_scope="admin_logs:read")

        category = request.query_params.get("category")
        action_type = request.query_params.get("action_type")
        actor_id = request.query_params.get("actor_id")
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")
        search = request.query_params.get("search")

        try:
            raw_page = int(request.query_params.get("page", 1))
        except (ValueError, TypeError, OverflowError):
            raw_page = 1

        try:
            raw_page_size = int(request.query_params.get("page_size", 20))
        except (ValueError, TypeError, OverflowError):
            raw_page_size = 20

        safe_page = max(1, min(raw_page, 100_000))
        safe_page_size = max(1, min(raw_page_size, 100))

        logs, total_count, total_pages = list_admin_logs(
            gym=gym,
            category=category,
            action_type=action_type,
            actor_id=actor_id,
            start_date=start_date,
            end_date=end_date,
            search=search,
            page=safe_page,
            page_size=safe_page_size,
        )

        response_data = {
            "count": total_count,
            "page": safe_page,
            "page_size": safe_page_size,
            "total_pages": total_pages,
            "results": GymAdminLogSerializer(logs, many=True).data,
        }
        return Response(response_data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Alerts & Logs - Admin Logs"],
        summary="Record Admin Log Entry",
        description="""
### Summary
Creates a new administrative audit log entry within the target gym workspace.
Useful for custom administrative actions, integrations, or client-side administrative event tracking.
        """,
        parameters=[
            OpenApiParameter(
                name="gym_id",
                description="Target Gym UUID if not using a gym context JWT token.",
                required=False,
                type=str,
            ),
        ],
        request=GymAdminLogCreateSerializer,
        responses={
            201: OpenApiResponse(response=GymAdminLogSerializer, description="Admin log entry created successfully."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Permission denied."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Gym not found."),
        },
    )
    def post(self, request):
        gym = resolve_gym_context(request)
        check_gym_permission(request, gym, required_scope="gym_profile:edit")

        serializer = GymAdminLogCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        log_entry = log_admin_action(
            gym=gym,
            actor=request.user,
            action=data["action"],
            action_type=data.get("action_type", AdminLogActionType.CUSTOM_ACTION),
            details=data.get("details", ""),
            category=data.get("category", AdminLogCategory.GENERAL),
            target_type=data.get("target_type"),
            target_id=data.get("target_id"),
            metadata=data.get("metadata", {}),
            ip_address=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT"),
            raise_on_error=True,
        )

        return Response(GymAdminLogSerializer(log_entry).data, status=status.HTTP_201_CREATED)


class GymAdminLogDetailView(APIView):
    """
    API endpoint for retrieving a single Gym Admin Log entry by ID.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Alerts & Logs - Admin Logs"],
        summary="Retrieve Admin Log Detail",
        description="Retrieves a specific administrative log record by UUID.",
        parameters=[
            OpenApiParameter(
                name="gym_id",
                description="Target Gym UUID if not using a gym context JWT token.",
                required=False,
                type=str,
            ),
        ],
        responses={
            200: OpenApiResponse(response=GymAdminLogSerializer, description="Admin log detail retrieved successfully."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Permission denied."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Log entry not found."),
        },
    )
    def get(self, request, log_id):
        gym = resolve_gym_context(request)
        check_gym_permission(request, gym, required_scope="admin_logs:read")

        log_entry = get_admin_log_by_id(gym=gym, log_id=str(log_id))
        return Response(GymAdminLogSerializer(log_entry).data, status=status.HTTP_200_OK)


class GymAdminLogsMetricsView(APIView):
    """
    API endpoint for retrieving metrics and activity summary for Gym Admin Logs.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Alerts & Logs - Admin Logs"],
        summary="Retrieve Admin Logs Metrics",
        description="""
### Summary
Returns aggregate statistics for gym administration logs:
- `total_logs`: Total number of administrative actions recorded.
- `logs_today`: Number of actions executed today.
- `by_category`: Count breakdown by category.
- `recent_logs`: 5 most recent administrative actions.
        """,
        parameters=[
            OpenApiParameter(
                name="gym_id",
                description="Target Gym UUID if not using a gym context JWT token.",
                required=False,
                type=str,
            ),
        ],
        responses={
            200: OpenApiResponse(response=GymAdminLogsMetricsSerializer, description="Admin log metrics retrieved successfully."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Permission denied."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Gym not found."),
        },
    )
    def get(self, request):
        gym = resolve_gym_context(request)
        check_gym_permission(request, gym, required_scope="admin_logs:read")

        metrics_data = get_admin_logs_metrics(gym=gym)
        serialized_recent = GymAdminLogSerializer(metrics_data["recent_logs"], many=True).data

        payload = {
            "total_logs": metrics_data["total_logs"],
            "logs_today": metrics_data["logs_today"],
            "by_category": metrics_data["by_category"],
            "recent_logs": serialized_recent,
        }
        return Response(payload, status=status.HTTP_200_OK)


class GymAdminLogsActionTypesView(APIView):
    """
    API endpoint for listing available log categories and action types for filter dropdowns.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Alerts & Logs - Admin Logs"],
        summary="List Admin Log Categories & Action Types",
        description="Returns predefined categories and action types for UI dropdown filters.",
        responses={
            200: OpenApiResponse(response=AdminLogOptionsResponseSerializer, description="Available options."),
        },
    )
    def get(self, request):
        categories = [{"value": choice[0], "label": choice[1]} for choice in AdminLogCategory.choices]
        action_types = [{"value": choice[0], "label": choice[1]} for choice in AdminLogActionType.choices]
        return Response({"categories": categories, "action_types": action_types}, status=status.HTTP_200_OK)


class GymAdminLogsExportView(APIView):
    """
    API endpoint for exporting Gym Admin Logs as CSV or JSON format.
    """
    permission_classes = [IsAuthenticated]

    def perform_content_negotiation(self, request, force=False):
        """Bypasses default content negotiation so format=csv does not trigger 404."""
        renderers = self.get_renderers()
        return renderers[0], renderers[0].media_type

    @extend_schema(
        tags=["Alerts & Logs - Admin Logs"],
        summary="Export Admin Logs",
        description="""
### Summary
Exports administration audit logs as a downloadable CSV or JSON file.
Accepts the same filtering parameters as the list endpoint.
        """,
        parameters=[
            OpenApiParameter(name="gym_id", type=str, required=False),
            OpenApiParameter(name="format", type=str, required=False, description="Export format: 'csv' (default) or 'json'"),
            OpenApiParameter(name="category", type=str, required=False),
            OpenApiParameter(name="action_type", type=str, required=False),
            OpenApiParameter(name="actor_id", type=str, required=False),
            OpenApiParameter(name="start_date", type=str, required=False),
            OpenApiParameter(name="end_date", type=str, required=False),
            OpenApiParameter(name="search", type=str, required=False),
        ],
        responses={
            200: OpenApiResponse(description="File download attachment or JSON array."),
        },
    )
    def get(self, request):
        import csv
        from django.http import HttpResponse
        from django.utils import timezone

        gym = resolve_gym_context(request)
        check_gym_permission(request, gym, required_scope="admin_logs:read")

        category = request.query_params.get("category")
        action_type = request.query_params.get("action_type")
        actor_id = request.query_params.get("actor_id")
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")
        search = request.query_params.get("search")
        export_format = (request.query_params.get("format") or "csv").strip().lower()
        if export_format not in ["csv", "json"]:
            from common.exceptions import DomainValidationError
            raise DomainValidationError(f"Unsupported export format '{export_format}'. Supported formats: 'csv', 'json'.")

        logs, _, _ = list_admin_logs(
            gym=gym,
            category=category,
            action_type=action_type,
            actor_id=actor_id,
            start_date=start_date,
            end_date=end_date,
            search=search,
            page=1,
            page_size=1000,
        )

        if export_format == "json":
            data = GymAdminLogSerializer(logs, many=True).data
            return Response(data, status=status.HTTP_200_OK)

        response = HttpResponse(content_type="text/csv; charset=utf-8")
        filename = f"admin_logs_{gym.id}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.csv"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'

        writer = csv.writer(response)
        writer.writerow(["Admin", "Action", "Details", "Date and Time", "Category", "Action Type", "Target Type", "Target ID"])
        for item in logs:
            admin_name = item.actor_name or (item.actor.email if item.actor else "System")
            writer.writerow([
                admin_name,
                item.action,
                item.details,
                item.formatted_date_time,
                item.get_category_display(),
                item.action_type,
                item.target_type or "",
                item.target_id or "",
            ])

        return response
