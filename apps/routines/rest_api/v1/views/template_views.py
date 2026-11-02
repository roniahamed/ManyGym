import uuid
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiParameter

from apps.access_control.models import GymStaffAssignment
from apps.routines.selectors import (
    list_routine_templates,
    get_routine_template_detail,
)
from apps.routines.services import (
    create_routine_template,
    update_routine_template,
    delete_routine_template,
)
from apps.routines.rest_api.v1.serializers import (
    RoutineTemplateListSerializer,
    RoutineTemplateDetailSerializer,
    RoutineTemplateCreateSerializer,
    RoutineTemplateUpdateSerializer,
)
from apps.routines.rest_api.v1.views.base_views import (
    resolve_routine_gym,
    check_routine_permission,
)
from common.pagination import StandardResultsSetPagination
from common.serializers import ErrorDetailSerializer, MessageResponseSerializer


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
