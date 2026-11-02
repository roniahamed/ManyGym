import uuid
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiParameter

from apps.access_control.models import GymStaffAssignment
from apps.members.models import Member
from apps.routines.selectors import (
    list_member_routine_history,
    get_member_routine_by_id,
)
from apps.routines.services import (
    assign_routine_to_member,
    customize_member_routine,
)
from apps.routines.rest_api.v1.serializers import (
    MemberRoutineDetailSerializer,
    MemberRoutineAssignSerializer,
    MemberRoutineUpdateSerializer,
)
from apps.routines.rest_api.v1.views.base import (
    resolve_routine_gym,
    check_routine_permission,
)
from common.exceptions import (
    ResourceNotFoundError,
)
from common.serializers import ErrorDetailSerializer


class MemberRoutineListView(APIView):
    """
    List member routine assignments (active routine and historical routines).
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Member Workouts"],
        summary="List Member Routines",
        description="Retrieves the current active workout routine and routine history for a gym member.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        responses={
            200: MemberRoutineDetailSerializer(many=True),
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def get(self, request, member_id: uuid.UUID):
        gym = resolve_routine_gym(request)
        check_routine_permission(request, gym, required_scopes=["routines:read", "members:read"])

        routines = list_member_routine_history(gym=gym, member_id=member_id)
        serializer = MemberRoutineDetailSerializer(routines, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class MemberRoutineAssignView(APIView):
    """
    Prescribe a template or custom workout routine to a gym member.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Member Workouts"],
        summary="Assign Routine to Member",
        description="Prescribes a template or custom workout routine to a member, deactivating any existing active routine.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        request=MemberRoutineAssignSerializer,
        responses={
            201: MemberRoutineDetailSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def post(self, request, member_id: uuid.UUID):
        gym = resolve_routine_gym(request)
        check_routine_permission(request, gym, required_scopes=["routines:assign", "routines:manage"])

        try:
            member = Member.objects.get(id=member_id, gym=gym)
        except Member.DoesNotExist:
            raise ResourceNotFoundError("Member not found.")

        serializer = MemberRoutineAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        prescribing_staff = (
            GymStaffAssignment.objects.filter(gym=gym, user=request.user).first()
            if request.user.is_authenticated
            else None
        )

        member_routine = assign_routine_to_member(
            gym=gym,
            member=member,
            source_template_id=data.get("source_template_id"),
            routine_name=data.get("routine_name"),
            routine_format=data.get("routine_format"),
            level=data.get("level"),
            notes=data.get("notes"),
            days=data.get("days"),
            prescribed_by_staff_id=prescribing_staff.id if prescribing_staff else None,
        )

        detail = get_member_routine_by_id(gym=gym, member_id=member.id, routine_id=member_routine.id)
        return Response(MemberRoutineDetailSerializer(detail).data, status=status.HTTP_201_CREATED)


class MemberRoutineDetailView(APIView):
    """
    Retrieve or customize a specific member routine prescription.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Member Workouts"],
        summary="Get Member Routine Dossier",
        description="Retrieves a specific member routine record with all exercises and workout days/sessions.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        responses={
            200: MemberRoutineDetailSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def get(self, request, member_id: uuid.UUID, routine_id: uuid.UUID):
        gym = resolve_routine_gym(request)
        check_routine_permission(request, gym, required_scopes=["routines:read", "members:read"])

        routine = get_member_routine_by_id(gym=gym, member_id=member_id, routine_id=routine_id)
        return Response(MemberRoutineDetailSerializer(routine).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Member Workouts"],
        summary="Customize Member Routine",
        description="Allows assigned trainers to adjust exercises, sets, reps, notes, or active status specifically for that member.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        request=MemberRoutineUpdateSerializer,
        responses={
            200: MemberRoutineDetailSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def patch(self, request, member_id: uuid.UUID, routine_id: uuid.UUID):
        gym = resolve_routine_gym(request)
        check_routine_permission(request, gym, required_scopes=["routines:assign", "routines:manage"])

        routine = get_member_routine_by_id(gym=gym, member_id=member_id, routine_id=routine_id)
        serializer = MemberRoutineUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        customize_member_routine(
            member_routine=routine,
            routine_name=data.get("routine_name"),
            level=data.get("level"),
            notes=data.get("notes"),
            is_active=data.get("is_active"),
            days=data.get("days"),
        )

        updated_routine = get_member_routine_by_id(gym=gym, member_id=member_id, routine_id=routine_id)
        return Response(MemberRoutineDetailSerializer(updated_routine).data, status=status.HTTP_200_OK)
