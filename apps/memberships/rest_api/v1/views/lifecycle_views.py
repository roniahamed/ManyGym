import uuid
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema

from apps.gyms.rest_api.v1.views import check_gym_permission
from apps.memberships.rest_api.v1.serializers import (
    MembershipPlanDetailSerializer,
    PlanStatusTransitionSerializer,
    PlanSyncAmenitiesSerializer,
)
from apps.memberships.services import (
    set_plan_status,
    sync_plan_amenities,
)
from apps.memberships.selectors import get_plan_details
from apps.memberships.rest_api.v1.views.base_views import resolve_plan_gym
from common.serializers import ErrorDetailSerializer


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
