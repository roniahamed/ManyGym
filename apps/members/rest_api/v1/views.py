import uuid
from decimal import Decimal
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter

from apps.gyms.models import Gym
from apps.access_control.models import GymStaffAssignment
from apps.memberships.models import MembershipPlan
from apps.members.models import Member, MemberSubscription
from apps.members.selectors import (
    list_gym_members,
    get_member_detail,
    get_gym_member_metrics,
)
from apps.members.services import (
    create_member,
    update_member_profile,
    delete_member,
    resend_member_invitation,
    accept_member_invitation,
    create_member_subscription,
    record_member_payment,
    attach_extra_amenities,
    transition_membership_status,
)
from apps.members.rest_api.v1.serializers import (
    MemberListSerializer,
    MemberDetailSerializer,
    MemberCreateSerializer,
    MemberUpdateSerializer,
    MemberAcceptInvitationSerializer,
    MemberSubscriptionCreateSerializer,
    MemberSubscriptionDetailSerializer,
    MemberSubscriptionStatusTransitionSerializer,
    MemberPaymentCreateSerializer,
    MemberPaymentSerializer,
    MemberExtraAmenitiesCreateSerializer,
    MemberExtraAmenitySerializer,
)
from common.pagination import StandardResultsSetPagination
from common.exceptions import (
    DomainValidationError,
    ResourceNotFoundError,
    PermissionDeniedError,
)
from common.serializers import ErrorDetailSerializer, MessageResponseSerializer


def resolve_member_gym(request) -> Gym:
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


def check_member_permission(request, gym: Gym, required_scope: str = None) -> None:
    """Enforces gym owner or required permission scope."""
    if gym.owner_user_id == request.user.id or request.user.is_superuser:
        return
    scopes = getattr(request, "scopes", None)
    if not scopes:
        staff = (
            GymStaffAssignment.objects.filter(gym=gym, user=request.user, status="active")
            .select_related("role")
            .first()
        )
        if staff and staff.role:
            scopes = list(staff.role.permissions.values_list("scope_code", flat=True))
        else:
            scopes = []
        request.scopes = scopes

    if required_scope and required_scope not in scopes:
        raise PermissionDeniedError(f"You do not possess the required '{required_scope}' scope for this gym operation.")


class MemberListCreateView(APIView):
    """
    List members and onboard new members.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Members & Lifecycle"],
        summary="List Gym Members",
        description="Retrieves the member directory with search, filters (status, payment, trainer), and pagination.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="joining_status", type=str, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="membership_status", type=str, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="payment_status", type=str, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="assigned_trainer_id", type=str, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="search", type=str, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="page", type=int, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="page_size", type=int, location=OpenApiParameter.QUERY, required=False),
        ],
        responses={
            status.HTTP_200_OK: MemberListSerializer(many=True),
            status.HTTP_400_BAD_REQUEST: ErrorDetailSerializer,
            status.HTTP_403_FORBIDDEN: ErrorDetailSerializer,
        },
    )
    def get(self, request):
        gym = resolve_member_gym(request)
        check_member_permission(request, gym, required_scope="members:read")

        joining_status = request.query_params.get("joining_status")
        membership_status = request.query_params.get("membership_status")
        payment_status = request.query_params.get("payment_status")
        trainer_id_raw = request.query_params.get("assigned_trainer_id")
        search = request.query_params.get("search")

        trainer_id = None
        if trainer_id_raw:
            try:
                trainer_id = uuid.UUID(str(trainer_id_raw))
            except ValueError:
                raise ResourceNotFoundError("Trainer not found.")

        members = list_gym_members(
            gym=gym,
            joining_status=joining_status,
            membership_status=membership_status,
            payment_status=payment_status,
            assigned_trainer_id=trainer_id,
            search=search,
        )

        if request.query_params.get("page") or request.query_params.get("page_size"):
            paginator = StandardResultsSetPagination()
            page = paginator.paginate_queryset(members, request)
            serializer = MemberListSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        serializer = MemberListSerializer(members, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Members & Lifecycle"],
        summary="Create / Onboard Member",
        description="Creates a new member profile, dispatches onboarding invitation email, and sets up initial subscription/payment.",
        request=MemberCreateSerializer,
        responses={
            status.HTTP_201_CREATED: MemberDetailSerializer,
            status.HTTP_400_BAD_REQUEST: ErrorDetailSerializer,
            status.HTTP_403_FORBIDDEN: ErrorDetailSerializer,
        },
    )
    def post(self, request):
        gym = resolve_member_gym(request)
        check_member_permission(request, gym, required_scope="members:edit")

        serializer = MemberCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        member = create_member(
            gym=gym,
            first_name=data["first_name"],
            last_name=data["last_name"],
            email=data["email"],
            phone=data.get("phone"),
            profile_photo_url=data.get("profile_photo_url"),
            address=data.get("address"),
            city=data.get("city"),
            country=data.get("country"),
            date_of_birth=data.get("date_of_birth"),
            sex=data.get("sex"),
            nationality=data.get("nationality"),
            emergency_contact_name=data.get("emergency_contact_name"),
            emergency_contact_phone=data.get("emergency_contact_phone"),
            emergency_contact_relationship=data.get("emergency_contact_relationship"),
            assigned_trainer_id=data.get("assigned_trainer_id"),
            internal_notes=data.get("internal_notes"),
            plan_id=data.get("plan_id"),
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
            extra_amenity_ids=data.get("extra_amenity_ids"),
            initial_payment_amount=data.get("initial_payment_amount"),
            initial_payment_method=data.get("initial_payment_method"),
            initial_payment_date=data.get("initial_payment_date"),
            initial_payment_notes=data.get("initial_payment_notes"),
        )
        detailed_member = get_member_detail(member.id, gym)
        return Response(
            MemberDetailSerializer(detailed_member).data,
            status=status.HTTP_201_CREATED,
        )


class MemberDetailView(APIView):
    """
    Retrieve, update, or remove a member.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Members & Lifecycle"],
        summary="Get Member Dossier",
        description="Retrieves full member profile, subscription history, extra amenities, and payment transactions.",
        responses={
            status.HTTP_200_OK: MemberDetailSerializer,
            status.HTTP_404_NOT_FOUND: ErrorDetailSerializer,
        },
    )
    def get(self, request, member_id: uuid.UUID):
        gym = resolve_member_gym(request)
        check_member_permission(request, gym, required_scope="members:read")

        member = get_member_detail(member_id, gym)
        return Response(MemberDetailSerializer(member).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Members & Lifecycle"],
        summary="Update Member Details",
        description="Partially updates demographic information, emergency contact, or assigned trainer.",
        request=MemberUpdateSerializer,
        responses={
            status.HTTP_200_OK: MemberDetailSerializer,
            status.HTTP_400_BAD_REQUEST: ErrorDetailSerializer,
            status.HTTP_404_NOT_FOUND: ErrorDetailSerializer,
        },
    )
    def patch(self, request, member_id: uuid.UUID):
        gym = resolve_member_gym(request)
        check_member_permission(request, gym, required_scope="members:edit")

        serializer = MemberUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        member = update_member_profile(
            member_id=member_id,
            gym=gym,
            **serializer.validated_data,
        )
        detailed_member = get_member_detail(member.id, gym)
        return Response(MemberDetailSerializer(detailed_member).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Members & Lifecycle"],
        summary="Delete Member",
        description="Permanently deletes member if no payments exist.",
        responses={
            status.HTTP_200_OK: MessageResponseSerializer,
            status.HTTP_404_NOT_FOUND: ErrorDetailSerializer,
            status.HTTP_409_CONFLICT: ErrorDetailSerializer,
        },
    )
    def delete(self, request, member_id: uuid.UUID):
        gym = resolve_member_gym(request)
        check_member_permission(request, gym, required_scope="members:delete")

        delete_member(member_id=member_id, gym=gym)
        return Response({"message": "Member removed successfully."}, status=status.HTTP_200_OK)


class MemberResendInvitationView(APIView):
    """
    Re-dispatch onboarding invitation email.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Members & Lifecycle"],
        summary="Resend Onboarding Invitation",
        description="Regenerates an invitation token and sends onboarding confirmation email.",
        responses={
            status.HTTP_200_OK: MessageResponseSerializer,
            status.HTTP_400_BAD_REQUEST: ErrorDetailSerializer,
            status.HTTP_404_NOT_FOUND: ErrorDetailSerializer,
        },
    )
    def post(self, request, member_id: uuid.UUID):
        gym = resolve_member_gym(request)
        check_member_permission(request, gym, required_scope="members:edit")

        resend_member_invitation(member_id=member_id, gym=gym)
        return Response({"message": "Onboarding invitation email sent successfully."}, status=status.HTTP_200_OK)


class MemberAcceptInvitationView(APIView):
    """
    Public/authenticated endpoint to link a user account with a member profile via invitation token.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Members & Lifecycle"],
        summary="Accept Member Invitation",
        description="Links the active authenticated user account to the member profile using the invitation token.",
        request=MemberAcceptInvitationSerializer,
        responses={
            status.HTTP_200_OK: MemberDetailSerializer,
            status.HTTP_400_BAD_REQUEST: ErrorDetailSerializer,
        },
    )
    def post(self, request):
        if not request.user.is_active:
            raise PermissionDeniedError("Your user account is inactive or disabled.")
        serializer = MemberAcceptInvitationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        token = serializer.validated_data["token"]
        member = accept_member_invitation(token=token, user=request.user)
        detailed_member = get_member_detail(member.id, member.gym)
        return Response(MemberDetailSerializer(detailed_member).data, status=status.HTTP_200_OK)


class MemberSubscriptionCreateView(APIView):
    """
    Attach a new membership subscription to an existing member.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Members & Subscriptions"],
        summary="Attach Subscription to Member",
        description="Attaches a new membership plan subscription, optional extra amenities, and initial payment.",
        request=MemberSubscriptionCreateSerializer,
        responses={
            status.HTTP_201_CREATED: MemberSubscriptionDetailSerializer,
            status.HTTP_400_BAD_REQUEST: ErrorDetailSerializer,
            status.HTTP_404_NOT_FOUND: ErrorDetailSerializer,
        },
    )
    def post(self, request, member_id: uuid.UUID):
        gym = resolve_member_gym(request)
        check_member_permission(request, gym, required_scope="members:edit")

        member = get_member_detail(member_id, gym)
        serializer = MemberSubscriptionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            plan = MembershipPlan.objects.get(id=data["plan_id"], gym=gym)
        except MembershipPlan.DoesNotExist:
            raise ResourceNotFoundError("Membership plan not found.")

        start_date = data.get("start_date") or timezone.now().date()
        sub = create_member_subscription(
            member=member,
            plan=plan,
            start_date=start_date,
            end_date=data.get("end_date"),
            extra_amenity_ids=data.get("extra_amenity_ids"),
            initial_payment_amount=data.get("initial_payment_amount"),
            initial_payment_method=data.get("initial_payment_method"),
            initial_payment_date=data.get("initial_payment_date"),
            initial_payment_notes=data.get("initial_payment_notes"),
        )
        return Response(MemberSubscriptionDetailSerializer(sub).data, status=status.HTTP_201_CREATED)


class MemberSubscriptionStatusView(APIView):
    """
    Pause, cancel, or resume a subscription.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Members & Subscriptions"],
        summary="Transition Subscription Status",
        description="Transitions subscription state (active <-> paused, active/paused -> cancelled).",
        request=MemberSubscriptionStatusTransitionSerializer,
        responses={
            status.HTTP_200_OK: MemberSubscriptionDetailSerializer,
            status.HTTP_400_BAD_REQUEST: ErrorDetailSerializer,
            status.HTTP_404_NOT_FOUND: ErrorDetailSerializer,
        },
    )
    def patch(self, request, subscription_id: uuid.UUID):
        gym = resolve_member_gym(request)
        check_member_permission(request, gym, required_scope="members:edit")

        serializer = MemberSubscriptionStatusTransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        new_status = serializer.validated_data["membership_status"]
        sub = transition_membership_status(subscription_id=subscription_id, gym=gym, new_status=new_status)
        return Response(MemberSubscriptionDetailSerializer(sub).data, status=status.HTTP_200_OK)


class MemberSubscriptionPaymentCreateView(APIView):
    """
    Log a payment transaction against a subscription.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Members & Subscriptions"],
        summary="Log Subscription Payment",
        description="Records a payment transaction against the subscription and recalculates payment standing.",
        request=MemberPaymentCreateSerializer,
        responses={
            status.HTTP_201_CREATED: MemberPaymentSerializer,
            status.HTTP_400_BAD_REQUEST: ErrorDetailSerializer,
            status.HTTP_404_NOT_FOUND: ErrorDetailSerializer,
        },
    )
    def post(self, request, subscription_id: uuid.UUID):
        gym = resolve_member_gym(request)
        check_member_permission(request, gym, required_scope="members:edit")

        try:
            sub = MemberSubscription.objects.select_related("plan", "member").get(
                id=subscription_id,
                member__gym=gym,
            )
        except MemberSubscription.DoesNotExist:
            raise ResourceNotFoundError(f"Member subscription '{subscription_id}' not found.")

        serializer = MemberPaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        payment = record_member_payment(
            subscription=sub,
            amount=data["amount"],
            payment_method=data["payment_method"],
            payment_date=data.get("payment_date") or timezone.now().date(),
            notes=data.get("notes"),
        )
        return Response(MemberPaymentSerializer(payment).data, status=status.HTTP_201_CREATED)


class MemberSubscriptionExtraAmenitiesView(APIView):
    """
    Attach extra paid amenities to a subscription.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Members & Subscriptions"],
        summary="Attach Extra Amenities",
        description="Subscribes member to additional paid amenities (e.g. personal locker, sauna).",
        request=MemberExtraAmenitiesCreateSerializer,
        responses={
            status.HTTP_201_CREATED: MemberExtraAmenitySerializer(many=True),
            status.HTTP_400_BAD_REQUEST: ErrorDetailSerializer,
            status.HTTP_404_NOT_FOUND: ErrorDetailSerializer,
        },
    )
    def post(self, request, subscription_id: uuid.UUID):
        gym = resolve_member_gym(request)
        check_member_permission(request, gym, required_scope="members:edit")

        try:
            sub = MemberSubscription.objects.select_related("plan", "member__gym").get(
                id=subscription_id,
                member__gym=gym,
            )
        except MemberSubscription.DoesNotExist:
            raise ResourceNotFoundError(f"Member subscription '{subscription_id}' not found.")

        serializer = MemberExtraAmenitiesCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        amenity_ids = serializer.validated_data["amenity_ids"]

        extras = attach_extra_amenities(subscription=sub, amenity_ids=amenity_ids)
        return Response(MemberExtraAmenitySerializer(extras, many=True).data, status=status.HTTP_201_CREATED)


class MemberMetricsView(APIView):
    """
    Database-level aggregations for member directory and subscription ledger.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Members & Lifecycle"],
        summary="Get Member Directory Metrics",
        description="Returns total members, joined count, invited count, active subscriptions, unpaid count, and total revenue.",
        responses={
            status.HTTP_200_OK: OpenApiResponse(description="Aggregated member and subscription metrics."),
        },
    )
    def get(self, request):
        gym = resolve_member_gym(request)
        check_member_permission(request, gym, required_scope="members:read")

        data = get_gym_member_metrics(gym)
        return Response(data, status=status.HTTP_200_OK)
