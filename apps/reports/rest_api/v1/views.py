import uuid
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiParameter

from apps.gyms.models import Gym
from apps.access_control.models import GymStaffAssignment
from apps.reports.selectors import (
    parse_and_validate_date_range,
    get_dashboard_summary,
    get_revenue_report,
    get_membership_growth_report,
    get_lead_funnel_report,
    get_trainer_workload_report,
)
from apps.reports.rest_api.v1.serializers import (
    DashboardSummarySerializer,
    RevenueReportSerializer,
    MembershipGrowthReportSerializer,
    LeadFunnelReportSerializer,
    TrainerWorkloadReportSerializer,
)
from common.enums import StaffStatus
from common.exceptions import (
    DomainValidationError,
    ResourceNotFoundError,
    PermissionDeniedError,
)
from common.serializers import ErrorDetailSerializer


def resolve_report_gym(request) -> Gym:
    """Helper to determine target gym from query param, active JWT context, or request body."""
    cached = getattr(request, "_resolved_gym", None)
    if cached is not None:
        return cached

    gym_id = (
        request.query_params.get("gym_id")
        or getattr(request, "gym_id", None)
        or (request.data.get("gym_id") if isinstance(request.data, dict) else None)
    )
    if not gym_id:
        raise DomainValidationError("An active Gym context token or 'gym_id' parameter is required.")
    try:
        uuid.UUID(str(gym_id))
        gym = Gym.objects.only("id", "owner_user_id", "name", "timezone").get(id=gym_id)
    except (Gym.DoesNotExist, ValueError, AttributeError):
        raise ResourceNotFoundError("Gym not found.")
    request._resolved_gym = gym
    return gym


def check_report_permission(request, gym: Gym) -> None:
    """Enforces that only gym owner, superuser, or staff with 'reports:read' scope can view reports."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        raise PermissionDeniedError("Authentication credentials were not provided.")

    if gym.owner_user_id == user.id or user.is_superuser:
        return

    assignment = GymStaffAssignment.objects.filter(
        gym=gym,
        user=user,
        status=StaffStatus.ACTIVE,
    ).first()

    if not assignment:
        raise PermissionDeniedError("You are not an active staff member of this gym.")

    if not assignment.role:
        raise PermissionDeniedError("You do not have permission to view gym reports.")

    has_perm = assignment.role.permissions.filter(scope_code="reports:read").exists()
    if not has_perm:
        raise PermissionDeniedError("Missing required permission scope 'reports:read'.")


# ==============================================================================
# 1. DASHBOARD SUMMARY VIEW
# ==============================================================================

class DashboardSummaryView(APIView):
    """
    Management overview summary cards: active members, expiring memberships,
    new leads, pending actions, and headline revenue.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Dashboard & Reports"],
        summary="Executive Dashboard Summary",
        description="Retrieves management headline metrics including active members, expiring memberships, leads, pending tasks, and revenue.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=True),
        ],
        responses={
            200: DashboardSummarySerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def get(self, request):
        gym = resolve_report_gym(request)
        check_report_permission(request, gym)

        summary_data = get_dashboard_summary(gym=gym)
        serializer = DashboardSummarySerializer(summary_data)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ==============================================================================
# 2. REVENUE REPORT VIEW
# ==============================================================================

class RevenueReportView(APIView):
    """
    Financial collections report with payment method breakdown, membership plan
    revenue distribution, and daily time-series collections.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Dashboard & Reports"],
        summary="Revenue & Collections Report",
        description="Aggregates total payments, breakdown by payment method, plan distribution, and daily revenue collections over a date range.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=True),
            OpenApiParameter(name="start_date", type=str, location=OpenApiParameter.QUERY, required=False, description="YYYY-MM-DD"),
            OpenApiParameter(name="end_date", type=str, location=OpenApiParameter.QUERY, required=False, description="YYYY-MM-DD"),
        ],
        responses={
            200: RevenueReportSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def get(self, request):
        gym = resolve_report_gym(request)
        check_report_permission(request, gym)

        start_date, end_date = parse_and_validate_date_range(request.query_params)
        report_data = get_revenue_report(gym=gym, start_date=start_date, end_date=end_date)
        serializer = RevenueReportSerializer(report_data)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ==============================================================================
# 3. MEMBERSHIP GROWTH VIEW
# ==============================================================================

class MembershipGrowthReportView(APIView):
    """
    Member acquisition, subscription churn rate, plan distribution, and status metrics.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Dashboard & Reports"],
        summary="Membership Growth & Churn Report",
        description="Analyzes member acquisition, new subscriptions, cancellations, net growth, and churn rate over a date range.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=True),
            OpenApiParameter(name="start_date", type=str, location=OpenApiParameter.QUERY, required=False, description="YYYY-MM-DD"),
            OpenApiParameter(name="end_date", type=str, location=OpenApiParameter.QUERY, required=False, description="YYYY-MM-DD"),
        ],
        responses={
            200: MembershipGrowthReportSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def get(self, request):
        gym = resolve_report_gym(request)
        check_report_permission(request, gym)

        start_date, end_date = parse_and_validate_date_range(request.query_params)
        report_data = get_membership_growth_report(gym=gym, start_date=start_date, end_date=end_date)
        serializer = MembershipGrowthReportSerializer(report_data)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ==============================================================================
# 4. LEAD FUNNEL VIEW
# ==============================================================================

class LeadFunnelReportView(APIView):
    """
    Sales pipeline conversion analytics: stages, booking rates, conversion rates,
    drop-off percentages, and lost-reason distributions.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Dashboard & Reports"],
        summary="Lead Conversion Funnel Report",
        description="Computes sales funnel conversion rates from New to Joined, drop-off percentages, acquisition sources, and lost reasons.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=True),
            OpenApiParameter(name="start_date", type=str, location=OpenApiParameter.QUERY, required=False, description="YYYY-MM-DD"),
            OpenApiParameter(name="end_date", type=str, location=OpenApiParameter.QUERY, required=False, description="YYYY-MM-DD"),
        ],
        responses={
            200: LeadFunnelReportSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def get(self, request):
        gym = resolve_report_gym(request)
        check_report_permission(request, gym)

        start_date, end_date = parse_and_validate_date_range(request.query_params)
        report_data = get_lead_funnel_report(gym=gym, start_date=start_date, end_date=end_date)
        serializer = LeadFunnelReportSerializer(report_data)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ==============================================================================
# 5. TRAINER WORKLOAD VIEW
# ==============================================================================

class TrainerWorkloadReportView(APIView):
    """
    Staff and trainer allocation: active member client load and prescribed routine workload.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Dashboard & Reports"],
        summary="Trainer Workload & Allocation Report",
        description="Reports active member counts, routine assignments, and workload breakdown per gym trainer and staff member.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=True),
        ],
        responses={
            200: TrainerWorkloadReportSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def get(self, request):
        gym = resolve_report_gym(request)
        check_report_permission(request, gym)

        report_data = get_trainer_workload_report(gym=gym)
        serializer = TrainerWorkloadReportSerializer(report_data)
        return Response(serializer.data, status=status.HTTP_200_OK)
