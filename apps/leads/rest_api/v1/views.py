import uuid
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter

from apps.gyms.models import Gym
from apps.access_control.models import GymStaffAssignment
from apps.leads.models import Lead, LeadCustomReasons, LeadNextMove, LeadNotes
from apps.leads.selectors import (
    list_leads,
    get_lead_details,
    get_lead_by_id,
    list_custom_reasons,
    get_lead_metrics,
)
from apps.leads.services import (
    create_lead,
    update_lead,
    update_lead_stage,
    schedule_next_move,
    complete_next_move,
    add_lead_note,
    convert_lead_to_member,
    create_custom_reason,
    delete_lead,
)
from apps.leads.rest_api.v1.serializers import (
    LeadListSerializer,
    LeadDetailSerializer,
    LeadCreateSerializer,
    LeadUpdateSerializer,
    LeadStageUpdateSerializer,
    LeadNextMoveSerializer,
    LeadNextMoveCreateSerializer,
    LeadNextMoveUpdateSerializer,
    LeadNoteSerializer,
    LeadNoteCreateSerializer,
    LeadConvertToMemberSerializer,
    LeadCustomReasonSerializer,
    LeadCustomReasonCreateSerializer,
    LeadMetricsSerializer,
    ReasonsDirectorySerializer,
)
from common.pagination import StandardResultsSetPagination
from common.exceptions import (
    DomainValidationError,
    ResourceNotFoundError,
    PermissionDeniedError,
)
from common.enums import NotJoiningReasonStandard
from common.serializers import ErrorDetailSerializer, MessageResponseSerializer


def resolve_lead_gym(request) -> Gym:
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


def check_lead_permission(request, gym: Gym, required_scope: str = None) -> None:
    """Enforces gym owner or required permission scope for Leads CRM."""
    if gym.owner_user_id == request.user.id or request.user.is_superuser:
        return
    scopes = getattr(request, "scopes", [])
    # 'leads:manage' supersedes 'leads:read'
    if required_scope == "leads:read":
        if "leads:read" in scopes or "leads:manage" in scopes:
            return
    elif required_scope and required_scope in scopes:
        return

    raise PermissionDeniedError(f"You do not possess the required '{required_scope}' scope for this gym operation.")


class LeadListCreateView(APIView):
    """
    List prospective leads and create new leads in the CRM sales pipeline.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Leads CRM"],
        summary="List Leads",
        description="Retrieves the gym leads directory with stage, source, staff filters, search, and pagination.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="stage", type=str, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="source", type=str, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="assigned_staff_id", type=str, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="interested_plan_id", type=str, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="search", type=str, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="page", type=int, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="page_size", type=int, location=OpenApiParameter.QUERY, required=False),
        ],
        responses={
            200: LeadListSerializer(many=True),
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
        },
    )
    def get(self, request):
        gym = resolve_lead_gym(request)
        check_lead_permission(request, gym, required_scope="leads:read")

        stage = request.query_params.get("stage")
        source = request.query_params.get("source")
        assigned_staff_id = request.query_params.get("assigned_staff_id")
        interested_plan_id = request.query_params.get("interested_plan_id")
        search = request.query_params.get("search")

        staff_uuid = None
        if assigned_staff_id:
            try:
                staff_uuid = uuid.UUID(assigned_staff_id)
            except ValueError:
                raise DomainValidationError("Invalid assigned_staff_id UUID format.")

        plan_uuid = None
        if interested_plan_id:
            try:
                plan_uuid = uuid.UUID(interested_plan_id)
            except ValueError:
                raise DomainValidationError("Invalid interested_plan_id UUID format.")

        leads_qs = list_leads(
            gym=gym,
            stage=stage,
            source=source,
            assigned_staff_id=staff_uuid,
            interested_plan_id=plan_uuid,
            search=search,
        )

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(leads_qs, request)
        if page is not None:
            serializer = LeadListSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        serializer = LeadListSerializer(leads_qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Leads CRM"],
        summary="Create Lead",
        description="Captures a new prospective gym lead with contact information, fitness goals, and initial note.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        request=LeadCreateSerializer,
        responses={
            201: LeadDetailSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
        },
    )
    def post(self, request):
        gym = resolve_lead_gym(request)
        check_lead_permission(request, gym, required_scope="leads:manage")

        serializer = LeadCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Determine author staff if request user is active staff
        author_staff = (
            GymStaffAssignment.objects.filter(gym=gym, user=request.user).first()
            if request.user.is_authenticated
            else None
        )

        lead = create_lead(
            gym=gym,
            first_name=data["first_name"],
            last_name=data.get("last_name"),
            phone=data.get("phone"),
            email=data.get("email"),
            interested_plan_id=data.get("interested_plan_id"),
            assigned_staff_id=data.get("assigned_staff_id"),
            source=data.get("source"),
            stage=data.get("stage"),
            expected_start_date=data.get("expected_start_date"),
            trial_booked_at=data.get("trial_booked_at"),
            not_joining_reason_standard=data.get("not_joining_reason_standard"),
            not_joining_custom_reason_id=data.get("not_joining_custom_reason_id"),
            fitness_goals=data.get("fitness_goals"),
            initial_note=data.get("initial_note"),
            author_staff_id=author_staff.id if author_staff else None,
        )

        detail = get_lead_details(gym=gym, lead_id=lead.id)
        out_serializer = LeadDetailSerializer(detail)
        return Response(out_serializer.data, status=status.HTTP_201_CREATED)


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


class LeadDetailUpdateDeleteView(APIView):
    """
    Retrieve full lead dossier, update fields/stage, or remove a lead.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Leads CRM"],
        summary="Get Lead Dossier",
        description="Retrieves detailed lead dossier including action items (next moves), staff notes, and goals.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        responses={
            200: LeadDetailSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def get(self, request, lead_id: uuid.UUID):
        gym = resolve_lead_gym(request)
        check_lead_permission(request, gym, required_scope="leads:read")

        lead = get_lead_details(gym=gym, lead_id=lead_id)
        serializer = LeadDetailSerializer(lead)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Leads CRM"],
        summary="Update Lead",
        description="Updates lead contact info, interested plan, staff assignment, pipeline stage, or fitness goals.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        request=LeadUpdateSerializer,
        responses={
            200: LeadDetailSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def patch(self, request, lead_id: uuid.UUID):
        gym = resolve_lead_gym(request)
        check_lead_permission(request, gym, required_scope="leads:manage")

        lead = get_lead_by_id(gym=gym, lead_id=lead_id)
        serializer = LeadUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        kwargs = {}
        for f in [
            "first_name", "last_name", "phone", "email",
            "interested_plan_id", "assigned_staff_id", "source", "stage",
            "not_joining_reason_standard", "not_joining_custom_reason_id",
            "expected_start_date", "trial_booked_at", "fitness_goals",
        ]:
            if f in data:
                kwargs[f] = data[f]

        update_lead(lead=lead, **kwargs)

        updated_lead = get_lead_details(gym=gym, lead_id=lead.id)
        return Response(LeadDetailSerializer(updated_lead).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Leads CRM"],
        summary="Delete Lead",
        description="Permanently deletes an unjoined lead record from the CRM.",
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
    def delete(self, request, lead_id: uuid.UUID):
        gym = resolve_lead_gym(request)
        check_lead_permission(request, gym, required_scope="leads:manage")

        lead = get_lead_by_id(gym=gym, lead_id=lead_id)
        delete_lead(lead)
        return Response({"message": "Lead deleted successfully."}, status=status.HTTP_200_OK)


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


class LeadConvertView(APIView):
    """
    Atomically convert a prospective lead into an active gym member.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Leads CRM"],
        summary="Convert Lead to Member",
        description="Atomically provisions a Member dossier, assigns membership plan, triggers onboarding invitation, and marks lead as joined.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        request=LeadConvertToMemberSerializer,
        responses={
            201: OpenApiResponse(
                description="Lead converted successfully.",
                response={
                    "type": "object",
                    "properties": {
                        "message": {"type": "string"},
                        "member_id": {"type": "string", "format": "uuid"},
                        "lead_id": {"type": "string", "format": "uuid"},
                    },
                },
            ),
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
            409: ErrorDetailSerializer,
        },
    )
    def post(self, request, lead_id: uuid.UUID):
        gym = resolve_lead_gym(request)
        check_lead_permission(request, gym, required_scope="leads:manage")

        lead = get_lead_by_id(gym=gym, lead_id=lead_id)
        serializer = LeadConvertToMemberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        author_staff = (
            GymStaffAssignment.objects.filter(gym=gym, user=request.user).first()
            if request.user.is_authenticated
            else None
        )

        member = convert_lead_to_member(
            lead=lead,
            plan_id=data.get("plan_id"),
            member_email=data.get("member_email"),
            last_name=data.get("last_name"),
            assigned_trainer_id=data.get("assigned_trainer_id"),
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
            extra_amenity_ids=data.get("extra_amenity_ids"),
            initial_payment_amount=data.get("initial_payment_amount"),
            initial_payment_method=data.get("initial_payment_method"),
            initial_payment_date=data.get("initial_payment_date"),
            initial_payment_notes=data.get("initial_payment_notes"),
            date_of_birth=data.get("date_of_birth"),
            sex=data.get("sex"),
            nationality=data.get("nationality"),
            emergency_contact_name=data.get("emergency_contact_name"),
            emergency_contact_phone=data.get("emergency_contact_phone"),
            emergency_contact_relationship=data.get("emergency_contact_relationship"),
            address=data.get("address"),
            city=data.get("city"),
            country=data.get("country"),
            author_staff_id=author_staff.id if author_staff else None,
        )

        return Response(
            {
                "message": "Lead converted successfully to active member.",
                "member_id": str(member.id),
                "lead_id": str(lead.id),
            },
            status=status.HTTP_201_CREATED,
        )
