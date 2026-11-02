import uuid
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiParameter

from apps.access_control.models import GymStaffAssignment
from apps.leads.models import LeadNextMove
from apps.leads.selectors import (
    get_lead_by_id,
    list_custom_reasons,
    get_lead_metrics,
)
from apps.leads.services import (
    schedule_next_move,
    complete_next_move,
    add_lead_note,
    create_custom_reason,
)
from apps.leads.rest_api.v1.serializers import (
    LeadNextMoveSerializer,
    LeadNextMoveCreateSerializer,
    LeadNextMoveUpdateSerializer,
    LeadNoteSerializer,
    LeadNoteCreateSerializer,
    LeadCustomReasonSerializer,
    LeadCustomReasonCreateSerializer,
    LeadMetricsSerializer,
    ReasonsDirectorySerializer,
)
from apps.leads.rest_api.v1.views.base import (
    resolve_lead_gym,
    check_lead_permission,
)
from common.exceptions import (
    DomainValidationError,
    ResourceNotFoundError,
)
from common.enums import NotJoiningReasonStandard
from common.serializers import ErrorDetailSerializer


class LeadMetricsView(APIView):
    """
    Sales pipeline KPI metrics and funnel breakdown.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Leads CRM"],
        summary="Lead Pipeline Metrics",
        description="Aggregated pipeline analytics including stage counts, conversion rate, and pending next moves.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        responses={
            200: LeadMetricsSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
        },
    )
    def get(self, request):
        gym = resolve_lead_gym(request)
        check_lead_permission(request, gym, required_scope="leads:read")

        metrics_data = get_lead_metrics(gym)
        serializer = LeadMetricsSerializer(metrics_data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class LeadReasonsView(APIView):
    """
    List standard reasons and gym-specific custom lost reasons, or create a new custom reason.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Leads CRM"],
        summary="List Lost Reasons",
        description="Retrieves both standard system lost reasons and gym-specific custom reasons.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        responses={
            200: ReasonsDirectorySerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
        },
    )
    def get(self, request):
        gym = resolve_lead_gym(request)
        check_lead_permission(request, gym, required_scope="leads:read")

        custom_reasons = list_custom_reasons(gym)
        standard_reasons = [
            {"value": choice[0], "label": choice[1]}
            for choice in NotJoiningReasonStandard.choices
        ]

        serializer = ReasonsDirectorySerializer({
            "standard_reasons": standard_reasons,
            "custom_reasons": custom_reasons,
        })
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Leads CRM"],
        summary="Create Custom Lost Reason",
        description="Configures a new gym-specific custom reason for lost lead classifications.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        request=LeadCustomReasonCreateSerializer,
        responses={
            201: LeadCustomReasonSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
        },
    )
    def post(self, request):
        gym = resolve_lead_gym(request)
        check_lead_permission(request, gym, required_scope="leads:manage")

        serializer = LeadCustomReasonCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        reason = create_custom_reason(
            gym=gym,
            reason_name=serializer.validated_data["reason_name"],
        )
        return Response(LeadCustomReasonSerializer(reason).data, status=status.HTTP_201_CREATED)


class LeadNextMoveListCreateView(APIView):
    """
    Schedule follow-up action items (next moves) for a prospective lead.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Leads CRM"],
        summary="Schedule Next Move",
        description="Adds a scheduled action item or follow-up task to a lead's agenda.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        request=LeadNextMoveCreateSerializer,
        responses={
            201: LeadNextMoveSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def post(self, request, lead_id: uuid.UUID):
        gym = resolve_lead_gym(request)
        check_lead_permission(request, gym, required_scope="leads:manage")

        lead = get_lead_by_id(gym=gym, lead_id=lead_id)
        serializer = LeadNextMoveCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        move = schedule_next_move(
            lead=lead,
            scheduled_date=serializer.validated_data["scheduled_date"],
            short_description=serializer.validated_data["short_description"],
        )
        return Response(LeadNextMoveSerializer(move).data, status=status.HTTP_201_CREATED)


class LeadNextMoveDetailView(APIView):
    """
    Mark next move completed or update its schedule.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Leads CRM"],
        summary="Update Next Move",
        description="Updates scheduled date, description, or marks the action item as completed.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        request=LeadNextMoveUpdateSerializer,
        responses={
            200: LeadNextMoveSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def patch(self, request, lead_id: uuid.UUID, move_id: uuid.UUID):
        gym = resolve_lead_gym(request)
        check_lead_permission(request, gym, required_scope="leads:manage")

        lead = get_lead_by_id(gym=gym, lead_id=lead_id)
        try:
            move = LeadNextMove.objects.get(id=move_id, lead=lead)
        except LeadNextMove.DoesNotExist:
            raise ResourceNotFoundError("Next move not found for this lead.")

        serializer = LeadNextMoveUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if data.get("is_completed") is True:
            complete_next_move(move)

        update_fields = []
        if "scheduled_date" in data:
            move.scheduled_date = data["scheduled_date"]
            update_fields.append("scheduled_date")
        if "short_description" in data:
            desc_clean = data["short_description"].strip()
            if not desc_clean:
                raise DomainValidationError("Description cannot be empty.")
            move.short_description = desc_clean
            update_fields.append("short_description")
        if "is_completed" in data and not data["is_completed"]:
            move.is_completed = False
            update_fields.append("is_completed")

        if update_fields:
            move.save(update_fields=update_fields)

        return Response(LeadNextMoveSerializer(move).data, status=status.HTTP_200_OK)


class LeadNoteCreateView(APIView):
    """
    Append an internal note to the lead's history.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Leads CRM"],
        summary="Add Lead Note",
        description="Records an internal staff note or call summary on the prospective lead.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        request=LeadNoteCreateSerializer,
        responses={
            201: LeadNoteSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def post(self, request, lead_id: uuid.UUID):
        gym = resolve_lead_gym(request)
        check_lead_permission(request, gym, required_scope="leads:manage")

        lead = get_lead_by_id(gym=gym, lead_id=lead_id)
        serializer = LeadNoteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        author_staff_id = serializer.validated_data.get("author_staff_id")
        if not author_staff_id and request.user.is_authenticated:
            staff_record = GymStaffAssignment.objects.filter(gym=gym, user=request.user).first()
            if staff_record:
                author_staff_id = staff_record.id

        note = add_lead_note(
            lead=lead,
            note_text=serializer.validated_data["note_text"],
            author_staff_id=author_staff_id,
        )
        return Response(LeadNoteSerializer(note).data, status=status.HTTP_201_CREATED)
