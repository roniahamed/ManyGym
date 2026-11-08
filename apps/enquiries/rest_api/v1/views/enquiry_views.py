import uuid

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter

from common.exceptions import DomainValidationError

from apps.enquiries.selectors import list_enquiries, get_enquiry_by_id
from apps.enquiries.services import (
    create_enquiry,
    update_enquiry,
    delete_enquiry,
    add_enquiry_note,
)
from apps.enquiries.permissions import (
    check_enquiry_gym_access,
    get_user_staff_gym_ids,
)
from apps.enquiries.rest_api.v1.serializers import (
    EnquiryListSerializer,
    EnquiryDetailSerializer,
    EnquiryCreateSerializer,
    EnquiryUpdateSerializer,
    EnquiryAddNoteSerializer,
)
from common.pagination import StandardResultsSetPagination
from common.serializers import ErrorDetailSerializer, MessageResponseSerializer


class EnquiryListCreateView(APIView):
    """
    API endpoint for listing enquiries (gym staff only) and creating enquiries (authenticated users).
    """
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    @extend_schema(
        tags=["Enquiries CRM"],
        summary="List Enquiries",
        description="""
### Summary
Retrieves paginated enquiries. Only authorized staff and owners of the respective gym can view inquiries.
        """,
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False, description="Filter by Gym UUID (User must be gym staff/owner)."),
            OpenApiParameter(name="status", type=str, location=OpenApiParameter.QUERY, required=False, description="Filter by status (NEW, CONTACTED, VISIT, BOOKED)."),
            OpenApiParameter(name="type", type=str, location=OpenApiParameter.QUERY, required=False, description="Filter by type (GENERAL_INQUIRY, CALLBACK_REQUEST, COMPLAINT, EMERGENCY, SPECIAL_REQUEST)."),
            OpenApiParameter(name="search", type=str, location=OpenApiParameter.QUERY, required=False, description="Search by name, email, phone, or summary."),
            OpenApiParameter(name="user_id", type=str, location=OpenApiParameter.QUERY, required=False, description="Filter by registered Manygym User UUID."),
            OpenApiParameter(name="page", type=int, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="page_size", type=int, location=OpenApiParameter.QUERY, required=False),
        ],
        responses={
            200: OpenApiResponse(response=EnquiryListSerializer(many=True), description="Paginated list of enquiries."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Staff permission required."),
        },
    )
    def get(self, request):
        gym_id = request.query_params.get("gym_id")
        status_filter = request.query_params.get("status")
        type_filter = request.query_params.get("type")
        search = request.query_params.get("search")
        user_id = request.query_params.get("user_id")

        if gym_id:
            try:
                gym_uuid = uuid.UUID(str(gym_id))
            except (ValueError, TypeError, AttributeError):
                raise DomainValidationError("Invalid gym_id format.")
            check_enquiry_gym_access(request.user, gym_uuid, action="view")
            allowed_gym_ids = None
        else:
            allowed_gym_ids = get_user_staff_gym_ids(request.user)

        qs = list_enquiries(
            gym_id=gym_id,
            status=status_filter,
            type=type_filter,
            search=search,
            user_id=user_id,
            allowed_gym_ids=allowed_gym_ids,
        )

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        if page is not None:
            serializer = EnquiryListSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        serializer = EnquiryListSerializer(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Enquiries CRM"],
        summary="Create a New Enquiry",
        description="""
### Summary
Creates a new Enquiry record for a gym. Any authenticated user can submit an enquiry.
- **Mandatory**: `gym_id`, `first_name`, `last_name`, and **either** `email` or `phone`.
- **Optional**: `manygym_user_id`, `type`, `status`, `summary`, `notes`.
        """,
        request=EnquiryCreateSerializer,
        responses={
            201: OpenApiResponse(response=EnquiryDetailSerializer, description="Enquiry created successfully."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
        },
    )
    def post(self, request):
        serializer = EnquiryCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        manygym_user = data.get("manygym_user_id")
        if not manygym_user and getattr(request, "user", None) and request.user.is_authenticated:
            manygym_user = request.user

        enquiry = create_enquiry(
            first_name=data["first_name"],
            last_name=data["last_name"],
            email=data.get("email"),
            phone=data.get("phone"),
            manygym_user=manygym_user,
            gym=data["gym_id"],
            type=data.get("type"),
            status=data.get("status"),
            summary=data.get("summary", ""),
            notes=data.get("notes", []),
        )
        return Response(EnquiryDetailSerializer(enquiry).data, status=status.HTTP_201_CREATED)


class EnquiryDetailView(APIView):
    """
    API endpoint for viewing, updating, and deleting an individual enquiry.
    Restricted to staff/owner of that specific gym.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Enquiries CRM"],
        summary="View an Enquiry",
        description="Retrieves full details of a single enquiry by its UUID. Only staff of the respective gym can access.",
        responses={
            200: OpenApiResponse(response=EnquiryDetailSerializer, description="Enquiry details."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Staff permission required."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Enquiry not found."),
        },
    )
    def get(self, request, enquiry_id):
        enquiry = get_enquiry_by_id(enquiry_id=enquiry_id)
        check_enquiry_gym_access(request.user, enquiry.gym, action="view")
        return Response(EnquiryDetailSerializer(enquiry).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Enquiries CRM"],
        summary="Update an Enquiry",
        description="Updates fields of an existing enquiry (status, type, summary, contact info, notes). Staff only.",
        request=EnquiryUpdateSerializer,
        responses={
            200: OpenApiResponse(response=EnquiryDetailSerializer, description="Enquiry updated successfully."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Staff permission required."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Enquiry not found."),
        },
    )
    def patch(self, request, enquiry_id):
        enquiry = get_enquiry_by_id(enquiry_id=enquiry_id)
        check_enquiry_gym_access(request.user, enquiry.gym, action="update")
        serializer = EnquiryUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = update_enquiry(enquiry_id=enquiry_id, **serializer.validated_data)
        return Response(EnquiryDetailSerializer(updated).data, status=status.HTTP_200_OK)

    def put(self, request, enquiry_id):
        return self.patch(request, enquiry_id)

    @extend_schema(
        tags=["Enquiries CRM"],
        summary="Delete an Enquiry",
        description="Permanently deletes an enquiry. Staff only.",
        responses={
            200: OpenApiResponse(response=MessageResponseSerializer, description="Enquiry deleted successfully."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Staff permission required."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Enquiry not found."),
        },
    )
    def delete(self, request, enquiry_id):
        enquiry = get_enquiry_by_id(enquiry_id=enquiry_id)
        check_enquiry_gym_access(request.user, enquiry.gym, action="delete")
        delete_enquiry(enquiry_id=enquiry_id)
        return Response(
            {"message": "Enquiry deleted successfully.", "is_deleted": True},
            status=status.HTTP_200_OK,
        )


class EnquiryAddNoteView(APIView):
    """
    Convenience API endpoint for appending a text note to an enquiry.
    Restricted to staff of that specific gym.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Enquiries CRM"],
        summary="Add Note to Enquiry",
        description="Appends a text note to the enquiry's notes list. Staff only.",
        request=EnquiryAddNoteSerializer,
        responses={
            200: OpenApiResponse(response=EnquiryDetailSerializer, description="Note added successfully."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Staff permission required."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Enquiry not found."),
        },
    )
    def post(self, request, enquiry_id):
        enquiry = get_enquiry_by_id(enquiry_id=enquiry_id)
        check_enquiry_gym_access(request.user, enquiry.gym, action="add notes to")
        serializer = EnquiryAddNoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        note_text = serializer.validated_data["note_text"]
        updated = add_enquiry_note(enquiry_id=enquiry_id, note_text=note_text)
        return Response(EnquiryDetailSerializer(updated).data, status=status.HTTP_200_OK)
