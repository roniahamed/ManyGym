import uuid
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter

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
)
from apps.members.rest_api.v1.serializers import (
    MemberListSerializer,
    MemberDetailSerializer,
    MemberCreateSerializer,
    MemberUpdateSerializer,
    MemberAcceptInvitationSerializer,
    MemberMetricsSerializer,
)
from apps.members.rest_api.v1.views.base_views import (
    resolve_member_gym,
    check_member_permission,
)
from common.pagination import StandardResultsSetPagination
from common.exceptions import (
    ResourceNotFoundError,
    PermissionDeniedError,
)
from common.serializers import ErrorDetailSerializer, MessageResponseSerializer


class MemberListCreateView(APIView):
    """
    List members and onboard new members.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    pagination_class = StandardResultsSetPagination

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
        description="""
### Summary
Creates a new member profile, dispatches onboarding invitation email, and sets up initial subscription/payment.

### File Upload Specifications (`profile_photo`)
- **Supported Content-Types**: `multipart/form-data` or `application/json`.
- **Accepted Formats**: `.jpg`, `.jpeg`, `.png`, `.webp`, `.heic`, `.bmp`, `.gif`, `.tiff`, `.jfif`, `.avif`.
- **Maximum File Size**: 10MB.
- **Processing Behavior**: Synchronous. Camera/smartphone EXIF orientation is automatically corrected (prevents rotated/sideways photos), and the image is converted directly to optimized WebP (`.webp`) format with an accompanying thumbnail.
- **Alternative**: An existing external image URL can be passed via `profile_photo_url`.
        """,
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

        profile_photo = (
            data.get("profile_photo")
            or request.FILES.get("profile_photo")
            or request.FILES.get("photo")
        )

        member = create_member(
            gym=gym,
            first_name=data["first_name"],
            last_name=data["last_name"],
            email=data["email"],
            phone=data.get("phone"),
            profile_photo_url=data.get("profile_photo_url"),
            profile_photo=profile_photo,
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
    parser_classes = [MultiPartParser, FormParser, JSONParser]

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
        description="""
### Summary
Partially updates demographic information, emergency contact, assigned trainer, or profile photo.

### File Upload Specifications (`profile_photo`)
- **Supported Content-Types**: `multipart/form-data` or `application/json`.
- **Accepted Formats**: `.jpg`, `.jpeg`, `.png`, `.webp`, `.heic`, `.bmp`, `.gif`, `.tiff`, `.jfif`, `.avif`.
- **Maximum File Size**: 10MB.
- **Processing Behavior**: Automatically corrects EXIF orientation and converts directly to WebP (`.webp`) format.
        """,
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
        validated_data = dict(serializer.validated_data)

        profile_photo = (
            validated_data.get("profile_photo")
            or request.FILES.get("profile_photo")
            or request.FILES.get("photo")
        )
        if profile_photo:
            validated_data["profile_photo"] = profile_photo

        member = update_member_profile(
            member_id=member_id,
            gym=gym,
            **validated_data,
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
        request=None,
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
            status.HTTP_200_OK: MemberMetricsSerializer,
        },
    )
    def get(self, request):
        gym = resolve_member_gym(request)
        check_member_permission(request, gym, required_scope="members:read")

        data = get_gym_member_metrics(gym)
        return Response(data, status=status.HTTP_200_OK)
