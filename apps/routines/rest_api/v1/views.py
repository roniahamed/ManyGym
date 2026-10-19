import uuid
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter

from apps.gyms.models import Gym
from apps.access_control.models import GymStaffAssignment
from apps.members.models import Member
from apps.routines.models import RoutineTemplate, MemberRoutine
from apps.routines.selectors import (
    list_routine_templates,
    get_routine_template_detail,
    get_member_active_routine,
    list_member_routine_history,
    get_member_routine_by_id,
)
from apps.routines.services import (
    create_routine_template,
    update_routine_template,
    delete_routine_template,
    assign_routine_to_member,
    customize_member_routine,
)
from apps.routines.rest_api.v1.serializers import (
    RoutineTemplateListSerializer,
    RoutineTemplateDetailSerializer,
    RoutineTemplateCreateSerializer,
    RoutineTemplateUpdateSerializer,
    MemberRoutineListSerializer,
    MemberRoutineDetailSerializer,
    MemberRoutineAssignSerializer,
    MemberRoutineUpdateSerializer,
)
from common.pagination import StandardResultsSetPagination
from common.exceptions import (
    DomainValidationError,
    ResourceNotFoundError,
    PermissionDeniedError,
)
from common.serializers import ErrorDetailSerializer, MessageResponseSerializer


def resolve_routine_gym(request) -> Gym:
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


def check_routine_permission(request, gym: Gym, required_scopes: list[str]) -> None:
    """Enforces gym owner, superuser, or required permission scopes for Routine Templates & Workouts."""
    if gym.owner_user_id == request.user.id or request.user.is_superuser:
        return
    scopes = getattr(request, "scopes", [])

    # 'routines:manage' supersedes all routine operations
    if "routines:manage" in scopes:
        return

    # Check if any of the accepted scopes are in user's granted scopes
    for req_scope in required_scopes:
        if req_scope in scopes:
            return

    scope_names = " or ".join(f"'{s}'" for s in required_scopes)
    raise PermissionDeniedError(f"You do not possess the required {scope_names} scope for this gym operation.")


# ==============================================================================
# ROUTINE TEMPLATE VIEWS
# ==============================================================================

class RoutineTemplateListCreateView(APIView):
    """
    List reusable routine templates or create a new template with nested workout days and exercises.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Routine Templates"],
        summary="List Routine Templates",
        description="Retrieves gym routine templates filtered by format, level, fitness goals, and search keyword.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="routine_format", type=str, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="level", type=str, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="goal", type=str, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="search", type=str, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="page", type=int, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="page_size", type=int, location=OpenApiParameter.QUERY, required=False),
        ],
        responses={
            200: RoutineTemplateListSerializer(many=True),
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
        },
    )
    def get(self, request):
        gym = resolve_routine_gym(request)
        check_routine_permission(request, gym, required_scopes=["routines:read", "trainers:read"])

        routine_format = request.query_params.get("routine_format")
        level = request.query_params.get("level")
        goal = request.query_params.get("goal")
        search = request.query_params.get("search")

        qs = list_routine_templates(
            gym=gym,
            routine_format=routine_format,
            level=level,
            goal=goal,
            search=search,
        )

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(qs, request)
        if page is not None:
            serializer = RoutineTemplateListSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        serializer = RoutineTemplateListSerializer(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Routine Templates"],
        summary="Create Routine Template",
        description="Atomically provisions a reusable workout routine template with nested days/sessions and exercises.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        request=RoutineTemplateCreateSerializer,
        responses={
            201: RoutineTemplateDetailSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
        },
    )
    def post(self, request):
        gym = resolve_routine_gym(request)
        check_routine_permission(request, gym, required_scopes=["routines:manage"])

        serializer = RoutineTemplateCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        author_staff = (
            GymStaffAssignment.objects.filter(gym=gym, user=request.user).first()
            if request.user.is_authenticated
            else None
        )

        template = create_routine_template(
            gym=gym,
            template_name=data["template_name"],
            routine_format=data.get("routine_format"),
            level=data.get("level"),
            notes=data.get("notes"),
            goals=data.get("goals"),
            days=data.get("days"),
            created_by_staff_id=author_staff.id if author_staff else None,
        )

        detail = get_routine_template_detail(gym=gym, template_id=template.id)
        return Response(RoutineTemplateDetailSerializer(detail).data, status=status.HTTP_201_CREATED)


class RoutineTemplateDetailView(APIView):
    """
    Retrieve full routine template dossier, update schedule/exercises, or remove template.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Routine Templates"],
        summary="Get Routine Template Dossier",
        description="Retrieves a complete routine template with all nested workout days/sessions and exercises.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        responses={
            200: RoutineTemplateDetailSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def get(self, request, template_id: uuid.UUID):
        gym = resolve_routine_gym(request)
        check_routine_permission(request, gym, required_scopes=["routines:read", "trainers:read"])

        template = get_routine_template_detail(gym=gym, template_id=template_id)
        return Response(RoutineTemplateDetailSerializer(template).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Routine Templates"],
        summary="Full Update Routine Template",
        description="Overwrites routine template metadata and replaces days/exercises layout.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        request=RoutineTemplateUpdateSerializer,
        responses={
            200: RoutineTemplateDetailSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def put(self, request, template_id: uuid.UUID):
        gym = resolve_routine_gym(request)
        check_routine_permission(request, gym, required_scopes=["routines:manage"])

        template = get_routine_template_detail(gym=gym, template_id=template_id)
        serializer = RoutineTemplateUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        update_routine_template(
            template=template,
            template_name=data.get("template_name"),
            routine_format=data.get("routine_format"),
            level=data.get("level"),
            notes=data.get("notes"),
            goals=data.get("goals"),
            days=data.get("days"),
        )

        updated_detail = get_routine_template_detail(gym=gym, template_id=template.id)
        return Response(RoutineTemplateDetailSerializer(updated_detail).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Routine Templates"],
        summary="Partial Update Routine Template",
        description="Updates specific fields of a routine template without modifying omitted fields.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        request=RoutineTemplateUpdateSerializer,
        responses={
            200: RoutineTemplateDetailSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def patch(self, request, template_id: uuid.UUID):
        gym = resolve_routine_gym(request)
        check_routine_permission(request, gym, required_scopes=["routines:manage"])

        template = get_routine_template_detail(gym=gym, template_id=template_id)
        serializer = RoutineTemplateUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        update_routine_template(
            template=template,
            template_name=data.get("template_name"),
            routine_format=data.get("routine_format"),
            level=data.get("level"),
            notes=data.get("notes"),
            goals=data.get("goals"),
            days=data.get("days"),
        )

        updated_detail = get_routine_template_detail(gym=gym, template_id=template.id)
        return Response(RoutineTemplateDetailSerializer(updated_detail).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Routine Templates"],
        summary="Delete Routine Template",
        description="Removes a routine template if it is not currently actively prescribed to members.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        responses={
            200: MessageResponseSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
            409: ErrorDetailSerializer,
        },
    )
    def delete(self, request, template_id: uuid.UUID):
        gym = resolve_routine_gym(request)
        check_routine_permission(request, gym, required_scopes=["routines:manage"])

        template = get_routine_template_detail(gym=gym, template_id=template_id)
        delete_routine_template(template)
        return Response({"message": "Routine template deleted successfully."}, status=status.HTTP_200_OK)


# ==============================================================================
# MEMBER ROUTINE PRESCRIPTION VIEWS
# ==============================================================================

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
