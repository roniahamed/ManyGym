import uuid
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter, OpenApiExample

from apps.gyms.models import Gym
from apps.gyms.rest_api.v1.views import check_gym_permission
from apps.memberships.models import MembershipPlan
from apps.memberships.rest_api.v1.serializers import (
    MembershipPlanListSerializer,
    MembershipPlanDetailSerializer,
    MembershipPlanCreateSerializer,
    MembershipPlanUpdateSerializer,
    PlanStatusTransitionSerializer,
    PlanSyncAmenitiesSerializer,
)
from apps.memberships.services import (
    create_membership_plan,
    update_membership_plan,
    set_plan_status,
    sync_plan_amenities,
    delete_membership_plan,
)
from apps.memberships.selectors import (
    list_gym_plans,
    get_plan_details,
    get_gym_plan_metrics,
)
from common.exceptions import (
    DomainValidationError,
    ResourceNotFoundError,
)
from common.serializers import ErrorDetailSerializer, MessageResponseSerializer


def resolve_plan_gym(request) -> Gym:
    """Helper to determine the target gym from active JWT context, query param, or request body."""
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


class MembershipPlanListCreateView(APIView):
    """
    List and create membership plans for a gym.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Membership Plans"],
        summary="List Gym Membership Plans",
        description="Retrieves a list of membership plans for the gym, with optional filtering by status and type.",
        parameters=[
            OpenApiParameter(
                name="gym_id",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Target gym UUID (if not inferred from active gym JWT context).",
            ),
            OpenApiParameter(
                name="plan_status",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by plan status ('draft', 'active', 'archived').",
            ),
            OpenApiParameter(
                name="plan_type",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by plan type ('time_based', 'session_based').",
            ),
            OpenApiParameter(
                name="search",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Search keyword matching plan name or description.",
            ),
        ],
        responses={
            status.HTTP_200_OK: MembershipPlanListSerializer(many=True),
            status.HTTP_400_BAD_REQUEST: ErrorDetailSerializer,
            status.HTTP_401_UNAUTHORIZED: ErrorDetailSerializer,
            status.HTTP_403_FORBIDDEN: ErrorDetailSerializer,
        },
    )
    def get(self, request):
        gym = resolve_plan_gym(request)
        check_gym_permission(request, gym, required_scope="plans:read")

        plan_status_filter = request.query_params.get("plan_status")
        plan_type_filter = request.query_params.get("plan_type")
        search = request.query_params.get("search")

        plans = list_gym_plans(
            gym=gym,
            plan_status=plan_status_filter,
            plan_type=plan_type_filter,
            search=search,
        )
        if request.query_params.get("page") or request.query_params.get("page_size"):
            from common.pagination import StandardResultsSetPagination
            paginator = StandardResultsSetPagination()
            page = paginator.paginate_queryset(plans, request)
            serializer = MembershipPlanListSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        serializer = MembershipPlanListSerializer(plans, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Membership Plans"],
        summary="Create Membership Plan (5-Step Lifecycle)",
        description="Creates a new 5-step membership plan with pricing, duration, payment schedule, and bundled amenities.",
        request=MembershipPlanCreateSerializer,
        responses={
            status.HTTP_201_CREATED: MembershipPlanDetailSerializer,
            status.HTTP_400_BAD_REQUEST: ErrorDetailSerializer,
            status.HTTP_401_UNAUTHORIZED: ErrorDetailSerializer,
            status.HTTP_403_FORBIDDEN: ErrorDetailSerializer,
        },
        examples=[
            OpenApiExample(
                name="Time-Based Plan Example",
                value={
                    "name": "Standard Gold Membership",
                    "description": "Comprehensive fitness access including all gym areas and selected recovery amenities.",
                    "plan_status": "draft",
                    "plan_type": "time_based",
                    "price": "69.99",
                    "duration_value": 3,
                    "duration_unit": "month",
                    "joining_fee": "25.00",
                    "payment_schedule": "full_payment",
                    "cancellation_policy": "30 days written notice required prior to renewal.",
                    "refund_policy": "Non-refundable after 14-day cooling off period.",
                    "included_amenity_ids": [],
                },
            ),
            OpenApiExample(
                name="Session-Based Plan Example",
                value={
                    "name": "Yoga 10-Session Pack",
                    "description": "Access to 10 yoga studio sessions valid across morning and evening schedule.",
                    "plan_status": "draft",
                    "plan_type": "session_based",
                    "price": "105.00",
                    "duration_value": 10,
                    "duration_unit": "session",
                    "joining_fee": "0.00",
                    "payment_schedule": "full_payment",
                },
            ),
        ],
    )
    def post(self, request):
        gym = resolve_plan_gym(request)
        check_gym_permission(request, gym, required_scope="plans:write")

        serializer = MembershipPlanCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        plan = create_membership_plan(
            gym=gym,
            name=data["name"],
            description=data.get("description"),
            plan_status=data.get("plan_status", "draft"),
            plan_type=data["plan_type"],
            price=data["price"],
            duration_value=data["duration_value"],
            duration_unit=data["duration_unit"],
            joining_fee=data.get("joining_fee", 0),
            payment_schedule=data.get("payment_schedule", "full_payment"),
            installment_schedule_config=data.get("installment_schedule_config"),
            cancellation_policy=data.get("cancellation_policy"),
            refund_policy=data.get("refund_policy"),
            included_amenity_ids=data.get("included_amenity_ids"),
        )
        # Fetch fresh with prefetched relations for detailed response
        detailed_plan = get_plan_details(plan.id, gym)
        return Response(
            MembershipPlanDetailSerializer(detailed_plan).data,
            status=status.HTTP_201_CREATED,
        )


class MembershipPlanMetricsView(APIView):
    """
    Returns aggregated plan counts and pricing metrics across the gym
    computed via database-level aggregations in a single SQL query.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Membership Plans"],
        summary="Get Gym Plan Pricing Metrics",
        description="Returns aggregated metrics (count by status, count by type, average, min, max price) in a single database query.",
        responses={
            status.HTTP_200_OK: OpenApiResponse(description="Aggregated pricing and count metrics."),
        },
    )
    def get(self, request):
        gym = resolve_plan_gym(request)
        check_gym_permission(request, gym, required_scope="plans:read")
        data = get_gym_plan_metrics(gym)
        return Response(data, status=status.HTTP_200_OK)


class MembershipPlanDetailView(APIView):
    """
    Retrieve, update, or delete a single membership plan.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Membership Plans"],
        summary="Get Membership Plan Details",
        description="Retrieves full 5-step details of a membership plan including included amenities.",
        responses={
            status.HTTP_200_OK: MembershipPlanDetailSerializer,
            status.HTTP_404_NOT_FOUND: ErrorDetailSerializer,
        },
    )
    def get(self, request, plan_id: uuid.UUID):
        gym = resolve_plan_gym(request)
        check_gym_permission(request, gym, required_scope="plans:read")

        plan = get_plan_details(plan_id, gym)
        return Response(
            MembershipPlanDetailSerializer(plan).data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        tags=["Membership Plans"],
        summary="Update Membership Plan",
        description="Partially updates plan fields. If active subscriptions exist, pricing/duration are locked.",
        request=MembershipPlanUpdateSerializer,
        responses={
            status.HTTP_200_OK: MembershipPlanDetailSerializer,
            status.HTTP_400_BAD_REQUEST: ErrorDetailSerializer,
            status.HTTP_404_NOT_FOUND: ErrorDetailSerializer,
        },
    )
    def patch(self, request, plan_id: uuid.UUID):
        gym = resolve_plan_gym(request)
        check_gym_permission(request, gym, required_scope="plans:write")

        serializer = MembershipPlanUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        plan = update_membership_plan(
            plan_id=plan_id,
            gym=gym,
            **serializer.validated_data,
        )
        detailed_plan = get_plan_details(plan.id, gym)
        return Response(
            MembershipPlanDetailSerializer(detailed_plan).data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        tags=["Membership Plans"],
        summary="Delete Membership Plan",
        description="Permanently deletes draft plans without subscriptions, or archives active plans.",
        responses={
            status.HTTP_200_OK: MessageResponseSerializer,
            status.HTTP_404_NOT_FOUND: ErrorDetailSerializer,
            status.HTTP_409_CONFLICT: ErrorDetailSerializer,
        },
    )
    def delete(self, request, plan_id: uuid.UUID):
        gym = resolve_plan_gym(request)
        check_gym_permission(request, gym, required_scope="plans:delete")

        delete_membership_plan(plan_id=plan_id, gym=gym)
        return Response(
            {"message": "Membership plan deleted or archived successfully."},
            status=status.HTTP_200_OK,
        )


class MembershipPlanStatusView(APIView):
    """
    Transition plan status (draft -> active <-> archived).
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Membership Plans"],
        summary="Transition Membership Plan Status",
        description="Transitions plan between draft, active, and archived states with validation.",
        request=PlanStatusTransitionSerializer,
        responses={
            status.HTTP_200_OK: MembershipPlanDetailSerializer,
            status.HTTP_400_BAD_REQUEST: ErrorDetailSerializer,
            status.HTTP_404_NOT_FOUND: ErrorDetailSerializer,
        },
    )
    def post(self, request, plan_id: uuid.UUID):
        gym = resolve_plan_gym(request)
        check_gym_permission(request, gym, required_scope="plans:write")

        serializer = PlanStatusTransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        new_status = serializer.validated_data["plan_status"]
        plan = set_plan_status(plan_id=plan_id, gym=gym, new_status=new_status)
        detailed_plan = get_plan_details(plan.id, gym)
        return Response(
            MembershipPlanDetailSerializer(detailed_plan).data,
            status=status.HTTP_200_OK,
        )


class MembershipPlanAmenitiesSyncView(APIView):
    """
    Bulk synchronize included amenities for a membership plan.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Membership Plans"],
        summary="Sync Included Amenities",
        description="Synchronizes the list of free and paid amenities bundled with the membership plan.",
        request=PlanSyncAmenitiesSerializer,
        responses={
            status.HTTP_200_OK: MembershipPlanDetailSerializer,
            status.HTTP_400_BAD_REQUEST: ErrorDetailSerializer,
            status.HTTP_404_NOT_FOUND: ErrorDetailSerializer,
        },
    )
    def put(self, request, plan_id: uuid.UUID):
        gym = resolve_plan_gym(request)
        check_gym_permission(request, gym, required_scope="plans:write")

        serializer = PlanSyncAmenitiesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        amenity_ids = serializer.validated_data["amenity_ids"]
        plan = get_plan_details(plan_id, gym)
        sync_plan_amenities(plan=plan, gym=gym, amenity_ids=amenity_ids)

        detailed_plan = get_plan_details(plan.id, gym)
        return Response(
            MembershipPlanDetailSerializer(detailed_plan).data,
            status=status.HTTP_200_OK,
        )
