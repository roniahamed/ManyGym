import uuid
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter

from apps.members.selectors import (
    list_member_requests,
    get_member_request_detail,
    get_member_detail,
)
from apps.members.services import (
    create_member_request,
    accept_member_request,
    reject_member_request,
    cancel_member_request,
)
from apps.members.rest_api.v1.serializers import (
    MemberRequestListSerializer,
    MemberRequestDetailSerializer,
    MemberRequestCreateSerializer,
    MemberRequestAcceptSerializer,
    MemberRequestRejectSerializer,
    MemberDetailSerializer,
)
from apps.members.rest_api.v1.views.base_views import (
    resolve_member_gym,
    check_member_permission,
)
from common.pagination import StandardResultsSetPagination
from common.serializers import ErrorDetailSerializer, MessageResponseSerializer
from common.exceptions import ResourceNotFoundError


def _resolve_request_and_gym(request, request_id, gym_id=None):
    """
    Resolves target MemberRequest and its Gym in a single unified database query.
    Eliminates redundant Gym resolution queries and preloads user profiles to prevent N+1 queries.
    """
    target_gym_id = (
        gym_id
        or request.query_params.get("gym_id")
        or getattr(request, "gym_id", None)
        or (request.data.get("gym_id") if isinstance(request.data, dict) else None)
    )

    try:
        from apps.members.models import MemberRequest
        qs = MemberRequest.objects.select_related(
            "gym",
            "user__profile",
            "interested_plan",
            "reviewed_by",
            "created_member",
        ).only(
            "id",
            "gym_id",
            "user_id",
            "interested_plan_id",
            "notes",
            "status",
            "rejection_reason",
            "created_member_id",
            "reviewed_by_id",
            "reviewed_at",
            "created_at",
            "updated_at",
            "gym__id",
            "gym__name",
            "gym__owner_user_id",
            "gym__timezone",
            "user__id",
            "user__first_name",
            "user__last_name",
            "user__email",
            "user__phone",
            "user__profile__id",
            "user__profile__user_id",
            "user__profile__avatar_url",
            "interested_plan__id",
            "interested_plan__name",
            "interested_plan__price",
            "interested_plan__duration_value",
            "interested_plan__duration_unit",
            "interested_plan__plan_type",
            "reviewed_by__id",
            "reviewed_by__first_name",
            "reviewed_by__last_name",
            "reviewed_by__email",
        )
        if target_gym_id:
            uuid.UUID(str(target_gym_id))
            member_req = qs.get(id=request_id, gym_id=target_gym_id)
        else:
            member_req = qs.get(id=request_id)

        request._resolved_gym = member_req.gym
        return member_req, member_req.gym
    except (MemberRequest.DoesNotExist, ValueError, AttributeError):
        raise ResourceNotFoundError("Member request not found.")


class MemberRequestListView(APIView):
    """
    List member requests for gym staff or submit a joining request as an authenticated user.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Member Requests"],
        summary="List Member Joining Requests",
        description="Retrieves member joining requests for the gym with status filtering, keyword search, and pagination. Requires 'members:read' permission.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="status", type=str, location=OpenApiParameter.QUERY, required=False, description="Filter by status: pending, accepted, rejected, cancelled"),
            OpenApiParameter(name="search", type=str, location=OpenApiParameter.QUERY, required=False, description="Search by applicant name or email"),
            OpenApiParameter(name="page", type=int, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="page_size", type=int, location=OpenApiParameter.QUERY, required=False),
        ],
        responses={
            200: OpenApiResponse(response=MemberRequestListSerializer(many=True), description="Paginated member requests list."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication credentials required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Insufficient permissions."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Gym not found."),
        },
    )
    def get(self, request, gym_id=None):
        gym = resolve_member_gym(request)
        check_member_permission(request, gym, required_scope="members:read")

        status_filter = request.query_params.get("status")
        search_filter = request.query_params.get("search")

        queryset = list_member_requests(
            gym=gym,
            status=status_filter,
            search=search_filter,
        )

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(queryset, request)
        serializer = MemberRequestListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    @extend_schema(
        tags=["Member Requests"],
        summary="Submit Member Joining Request",
        description="Sends a membership joining request from the authenticated user to the gym.",
        request=MemberRequestCreateSerializer,
        responses={
            201: OpenApiResponse(response=MessageResponseSerializer, description="Request submitted successfully."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure or already a member."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Gym does not accept requests or user is blocked."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Gym not found."),
        },
    )
    def post(self, request, gym_id=None):
        gym = resolve_member_gym(request)
        serializer = MemberRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        res_data = create_member_request(
            user=request.user,
            gym_id=gym.id,
            interested_plan_id=serializer.validated_data.get("interested_plan_id"),
            notes=serializer.validated_data.get("notes"),
        )
        status_code = status.HTTP_201_CREATED if res_data.get("created") else status.HTTP_200_OK
        return Response(res_data, status=status_code)


class MemberRequestDetailView(APIView):
    """
    Retrieve single member request detail.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Member Requests"],
        summary="Get Member Request Detail",
        description="Fetches detailed information for a specific member joining request. Requires 'members:read' permission.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        responses={
            200: OpenApiResponse(response=MemberRequestDetailSerializer, description="Request detail."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Permission denied."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Not found."),
        },
    )
    def get(self, request, request_id, gym_id=None):
        member_req, gym = _resolve_request_and_gym(request, request_id, gym_id=gym_id)
        check_member_permission(request, gym, required_scope="members:read")

        serializer = MemberRequestDetailSerializer(member_req)
        return Response(serializer.data, status=status.HTTP_200_OK)


class MemberRequestAcceptView(APIView):
    """
    Accept a member joining request and enroll applicant as gym member.
    The staff or admin provides the required membership details.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @extend_schema(
        tags=["Member Requests"],
        summary="Accept Member Request",
        description="Accepts a pending member request and enrolls the user as an active gym member with the provided subscription, trainer, payment, and demographic details. Requires 'members:edit' permission.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        request=MemberRequestAcceptSerializer,
        responses={
            201: OpenApiResponse(response=MemberDetailSerializer, description="Member created successfully from request."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Permission denied."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Request or gym not found."),
            409: OpenApiResponse(response=ErrorDetailSerializer, description="Request already processed or user already a member."),
        },
    )
    def post(self, request, request_id, gym_id=None):
        member_req, gym = _resolve_request_and_gym(request, request_id, gym_id=gym_id)
        check_member_permission(request, gym, required_scope="members:edit")

        serializer = MemberRequestAcceptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        member = accept_member_request(
            request_id=request_id,
            gym=gym,
            reviewer=request.user,
            plan_id=data.get("plan_id"),
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
            assigned_trainer_id=data.get("assigned_trainer_id"),
            extra_amenity_ids=data.get("extra_amenity_ids"),
            initial_payment_amount=data.get("initial_payment_amount"),
            initial_payment_method=data.get("initial_payment_method"),
            initial_payment_date=data.get("initial_payment_date"),
            initial_payment_notes=data.get("initial_payment_notes"),
            first_name=data.get("first_name"),
            last_name=data.get("last_name"),
            email=data.get("email"),
            phone=data.get("phone"),
            profile_photo=data.get("profile_photo"),
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
            internal_notes=data.get("internal_notes"),
        )

        member_dossier = get_member_detail(member_id=member.id, gym=gym)
        member_detail = MemberDetailSerializer(member_dossier)
        return Response(
            {
                "message": "Member request accepted and member successfully enrolled.",
                "member": member_detail.data,
            },
            status=status.HTTP_201_CREATED,
        )


class MemberRequestRejectView(APIView):
    """
    Reject a member joining request.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Member Requests"],
        summary="Reject Member Request",
        description="Rejects a pending member joining request with an optional reason. Requires 'members:edit' permission.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        request=MemberRequestRejectSerializer,
        responses={
            200: OpenApiResponse(response=MemberRequestDetailSerializer, description="Request rejected."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Permission denied."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Not found."),
            409: OpenApiResponse(response=ErrorDetailSerializer, description="Request already processed."),
        },
    )
    def post(self, request, request_id, gym_id=None):
        member_req, gym = _resolve_request_and_gym(request, request_id, gym_id=gym_id)
        check_member_permission(request, gym, required_scope="members:edit")

        serializer = MemberRequestRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        req_obj = reject_member_request(
            request_id=request_id,
            gym=gym,
            reviewer=request.user,
            rejection_reason=serializer.validated_data.get("rejection_reason"),
        )
        return Response(
            {
                "message": "Member request rejected successfully.",
                "request": MemberRequestDetailSerializer(req_obj).data,
            },
            status=status.HTTP_200_OK,
        )


class MemberRequestCancelView(APIView):
    """
    User cancels their own pending join request.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Member Requests"],
        summary="Cancel Own Member Request",
        description="Allows an applicant user to cancel their own pending join request.",
        responses={
            200: OpenApiResponse(response=MessageResponseSerializer, description="Request cancelled successfully."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Request not found."),
            409: OpenApiResponse(response=ErrorDetailSerializer, description="Cannot cancel non-pending request."),
        },
    )
    def post(self, request, request_id):
        req_obj = cancel_member_request(
            request_id=request_id,
            user=request.user,
        )
        return Response(
            {
                "message": "Member request cancelled successfully.",
                "request_id": str(req_obj.id),
                "status": req_obj.status,
            },
            status=status.HTTP_200_OK,
        )
