from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiExample, OpenApiParameter

from apps.access_control.models import GymStaffAssignment
from apps.access_control.rest_api.v1.serializers import (
    StaffAssignmentSerializer,
    InviteStaffSerializer,
    UpdateStaffStatusSerializer,
)
from apps.access_control.selectors import list_gym_staff
from apps.access_control.services import (
    invite_staff_member,
    update_staff_status,
    remove_staff_assignment,
)
from apps.access_control.rest_api.v1.views.base import resolve_request_gym
from common.exceptions import (
    ResourceNotFoundError,
    PermissionDeniedError,
)
from common.serializers import ErrorDetailSerializer, MessageResponseSerializer
from common.pagination import StandardResultsSetPagination


class StaffListInviteView(APIView):
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    @extend_schema(
        tags=["Access Control & RBAC"],
        summary="List Gym Staff Members",
        description="""
### Summary
Retrieves paginated directory of all staff members assigned to the active gym with their role, invitation date, and assignment status.

### Parameters
- `page`: Page number (default: 1).
- `page_size`: Results per page (default: 20, max: 100).
- `all`: If `true`, returns unpaginated full list.

### Authorization
- Requires active Gym context or Gym Ownership.
        """,
        parameters=[
            OpenApiParameter(
                name="page",
                description="Page number",
                required=False,
                type=int,
            ),
            OpenApiParameter(
                name="page_size",
                description="Results per page (max 100)",
                required=False,
                type=int,
            ),
            OpenApiParameter(
                name="all",
                description="Set to 'true' to retrieve all staff members unpaginated",
                required=False,
                type=bool,
            ),
        ],
        responses={
            200: StaffAssignmentSerializer(many=True),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
        },
    )
    def get(self, request):
        gym = resolve_request_gym(request)
        if gym.owner_user_id != request.user.id and not request.user.is_superuser:
            if str(getattr(request, "gym_id", "")) != str(gym.id):
                is_staff = GymStaffAssignment.objects.filter(user=request.user, gym=gym, status="active").exists()
                if not is_staff:
                    raise PermissionDeniedError("You do not have access to view staff for this gym.")

        staff = list_gym_staff(gym_id=str(gym.id))

        if request.query_params.get("all") == "true" or request.query_params.get("paginate") == "false":
            return Response(StaffAssignmentSerializer(staff, many=True).data, status=status.HTTP_200_OK)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(staff, request, view=self)
        if page is not None:
            serializer = StaffAssignmentSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        return Response(StaffAssignmentSerializer(staff, many=True).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Access Control & RBAC"],
        summary="Invite Staff Member",
        description="""
### Summary
Invites an existing registered user to join the gym with a designated role (e.g. Trainer, Staff, or Custom Role).

### Business Rules
- User must be registered in Many Gym platform.
- Target role must be a system standard role or belong to this gym.
- If previously inactive, the assignment is reactivated.
        """,
        request=InviteStaffSerializer,
        responses={
            201: OpenApiResponse(response=StaffAssignmentSerializer, description="Staff assignment created."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Permission denied (requires people_roles:manage)."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="User email or role not found."),
        },
        examples=[
            OpenApiExample(
                name="Invite Staff Payload",
                value={
                    "email": "sarah.trainer@manygym.com",
                    "role_id": "84c9826f-9988-4433-2211-123456789abc",
                },
                request_only=True,
            )
        ],
    )
    def post(self, request):
        gym = resolve_request_gym(request)
        if gym.owner_user_id != request.user.id and not request.user.is_superuser:
            if "people_roles:manage" not in getattr(request, "scopes", []):
                raise PermissionDeniedError("Permission denied.")

        serializer = InviteStaffSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        assignment = invite_staff_member(
            gym=gym,
            user_email=serializer.validated_data["email"],
            role_id=str(serializer.validated_data["role_id"]),
        )
        assignment = (
            GymStaffAssignment.objects.select_related("user__profile", "role__gym", "gym")
            .prefetch_related("role__permissions")
            .get(id=assignment.id)
        )
        return Response(StaffAssignmentSerializer(assignment).data, status=status.HTTP_201_CREATED)


class StaffDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Access Control & RBAC"],
        summary="Update Staff Status (Active / Inactive)",
        description="""
### Summary
Toggles a staff member's assignment status between `active` and `inactive`.

### Impact
When `inactive`, the staff member can no longer switch context to this gym or execute operations on its behalf.
        """,
        request=UpdateStaffStatusSerializer,
        responses={
            200: OpenApiResponse(response=StaffAssignmentSerializer, description="Staff status updated."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Invalid status value."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Permission denied."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Staff assignment not found."),
        },
        examples=[
            OpenApiExample(
                name="Deactivate Staff Payload",
                value={"status": "inactive"},
                request_only=True,
            )
        ],
    )
    def patch(self, request, assignment_id):
        try:
            assignment = (
                GymStaffAssignment.objects.select_related("gym", "user__profile", "role__gym")
                .prefetch_related("role__permissions")
                .get(id=assignment_id)
            )
        except (GymStaffAssignment.DoesNotExist, ValueError):
            raise ResourceNotFoundError("Staff assignment not found.")

        if assignment.gym.owner_user_id != request.user.id and not request.user.is_superuser:
            if str(getattr(request, "gym_id", "")) != str(assignment.gym.id) or "people_roles:manage" not in getattr(request, "scopes", []):
                raise PermissionDeniedError("Permission denied.")

        serializer = UpdateStaffStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = update_staff_status(assignment, serializer.validated_data["status"])
        updated = (
            GymStaffAssignment.objects.select_related("gym", "user__profile", "role__gym")
            .prefetch_related("role__permissions")
            .get(id=updated.id)
        )
        return Response(StaffAssignmentSerializer(updated).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Access Control & RBAC"],
        summary="Revoke Staff Access",
        description="""
### Summary
Permanently removes a staff member assignment from the gym.

### Side Effects
- Any active gym context tokens for this user on this gym will immediately fail context validation.
        """,
        responses={
            200: OpenApiResponse(response=MessageResponseSerializer, description="Staff access revoked."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Permission denied."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Staff assignment not found."),
        },
    )
    def delete(self, request, assignment_id):
        try:
            assignment = GymStaffAssignment.objects.select_related("gym").get(id=assignment_id)
        except (GymStaffAssignment.DoesNotExist, ValueError):
            raise ResourceNotFoundError("Staff assignment not found.")

        if assignment.gym.owner_user_id != request.user.id and not request.user.is_superuser:
            if str(getattr(request, "gym_id", "")) != str(assignment.gym.id) or "people_roles:manage" not in getattr(request, "scopes", []):
                raise PermissionDeniedError("Permission denied.")

        remove_staff_assignment(assignment)
        return Response({"message": "Staff member access revoked."}, status=status.HTTP_200_OK)
