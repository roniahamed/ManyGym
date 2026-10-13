from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiExample, OpenApiParameter

from apps.access_control.models import Role, GymStaffAssignment
from apps.access_control.rest_api.v1.serializers import (
    RoleSerializer,
    CreateCustomRoleSerializer,
    UpdateCustomRoleSerializer,
    StaffAssignmentSerializer,
    InviteStaffSerializer,
    UpdateStaffStatusSerializer,
    PermissionSerializer,
)
from apps.access_control.selectors import (
    list_permissions_by_topic,
    list_gym_roles,
    list_gym_staff,
)
from apps.access_control.services import (
    create_custom_role,
    update_custom_role,
    delete_custom_role,
    invite_staff_member,
    update_staff_status,
    remove_staff_assignment,
)
from apps.gyms.models import Gym
from common.exceptions import (
    DomainValidationError,
    ResourceNotFoundError,
    PermissionDeniedError,
)
from common.serializers import ErrorDetailSerializer, MessageResponseSerializer
from common.pagination import StandardResultsSetPagination


def resolve_request_gym(request) -> Gym:
    """Helper to determine the target gym from active context or query param."""
    gym_id = getattr(request, "gym_id", None) or request.query_params.get("gym_id")
    if not gym_id:
        raise DomainValidationError("An active Gym context token or 'gym_id' parameter is required for this operation.")
    try:
        gym = Gym.objects.select_related("owner_user").get(id=gym_id)
    except (Gym.DoesNotExist, ValueError):
        raise ResourceNotFoundError("Gym not found.")
    return gym


class PermissionsListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Access Control & RBAC"],
        summary="List System Permissions Grouped by Topic",
        description="""
### Summary
Retrieves all system permission scopes organized across the 9 core topics:
1. **Studio**
2. **Reports**
3. **Gym Profile**
4. **Subscription Plans**
5. **Members**
6. **Leads**
7. **Trainers**
8. **Routine Templates**
9. **People & Roles**

### Authentication & Authorization
- **Authentication**: Required (`Bearer <JWT>`).
- Used by UI when gym administrators select permission checkboxes to create or edit custom roles.
        """,
        responses={
            200: OpenApiResponse(
                description="Permissions grouped by topic dictionary.",
                examples=[
                    OpenApiExample(
                        name="Permissions Grouped Example",
                        value={
                            "Members": [
                                {
                                    "id": "6190cfd4-05b2-4aee-bf73-a2744d1c6607",
                                    "scope_code": "members:read",
                                    "name": "View Members",
                                    "description": "Read member directory and member details.",
                                },
                                {
                                    "id": "850ed65e-7f29-4342-b770-3ec7bf7a7f39",
                                    "scope_code": "members:edit",
                                    "name": "Edit Members",
                                    "description": "Edit member profile, status, or subscription.",
                                },
                            ],
                            "Routine Templates": [
                                {
                                    "id": "50e65f4e-4a78-4394-98ac-e9c4f96e8ad3",
                                    "scope_code": "routines:assign",
                                    "name": "Assign Routines",
                                    "description": "Assign routines to gym members.",
                                }
                            ],
                        },
                    )
                ],
            ),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
        },
    )
    def get(self, request):
        data = list_permissions_by_topic()
        return Response(data, status=status.HTTP_200_OK)


class RoleListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    @extend_schema(
        tags=["Access Control & RBAC"],
        summary="List Available Roles",
        description="""
### Summary
Returns global system standard roles (`Administrator`, `Staff`, `Trainer`) along with gym-specific custom roles. Supports optional pagination.

### Parameters
- `gym_id`: Optional Gym UUID to include gym custom roles when using personal token.
- `page`: Page number (optional).
- `page_size`: Results per page (optional).
        """,
        parameters=[
            OpenApiParameter(
                name="gym_id",
                description="Optional Gym UUID to include gym custom roles when using personal token",
                required=False,
                type=str,
            ),
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
        ],
        responses={
            200: OpenApiResponse(
                response=RoleSerializer(many=True),
                description="List of available roles.",
            ),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
        },
    )
    def get(self, request):
        gym_id = getattr(request, "gym_id", None) or request.query_params.get("gym_id")
        roles = list_gym_roles(gym_id=gym_id)

        if "page" in request.query_params or "page_size" in request.query_params:
            paginator = self.pagination_class()
            page = paginator.paginate_queryset(roles, request, view=self)
            if page is not None:
                serializer = RoleSerializer(page, many=True)
                return paginator.get_paginated_response(serializer.data)

        return Response(RoleSerializer(roles, many=True).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Access Control & RBAC"],
        summary="Create Custom Role",
        description="""
### Summary
Creates a new custom role scoped to the current gym and binds selected permission IDs.

### Authentication & Authorization
- **Authentication**: Required (`Bearer <JWT>`).
- **Authorization**: User must be Gym Owner or possess `people_roles:manage` scope.

### Business Rules
- Custom role slug is auto-generated from name.
- Slug must be unique within the owning gym.
- `is_custom` is automatically set to `True`.
        """,
        request=CreateCustomRoleSerializer,
        responses={
            201: OpenApiResponse(response=RoleSerializer, description="Custom role created."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Permission denied (lacks people_roles:manage)."),
            409: OpenApiResponse(response=ErrorDetailSerializer, description="Role with this name already exists in gym."),
        },
        examples=[
            OpenApiExample(
                name="Create Custom Role Payload",
                value={
                    "name": "Front Desk Receptionist",
                    "description": "Handles check-ins and member basic viewing",
                    "permission_ids": [
                        "6190cfd4-05b2-4aee-bf73-a2744d1c6607",
                        "d28bfae7-3c5a-4ba4-8887-535c822195d2",
                    ],
                },
                request_only=True,
            )
        ],
    )
    def post(self, request):
        gym = resolve_request_gym(request)
        if gym.owner_user_id != request.user.id and not request.user.is_superuser:
            if "people_roles:manage" not in getattr(request, "scopes", []):
                raise PermissionDeniedError("You do not have permission to manage roles in this gym.")

        serializer = CreateCustomRoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        role = create_custom_role(
            gym=gym,
            name=serializer.validated_data["name"],
            description=serializer.validated_data.get("description"),
            permission_ids=serializer.validated_data.get("permission_ids"),
        )
        role = Role.objects.select_related("gym").prefetch_related("permissions").get(id=role.id)
        return Response(RoleSerializer(role).data, status=status.HTTP_201_CREATED)


class RoleDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Access Control & RBAC"],
        summary="Get Role Details",
        description="Retrieves a specific role and its detailed permission scopes.",
        responses={
            200: OpenApiResponse(response=RoleSerializer, description="Role details."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Role not found."),
        },
    )
    def get(self, request, role_id):
        try:
            role = Role.objects.select_related("gym").prefetch_related("permissions").get(id=role_id)
        except (Role.DoesNotExist, ValueError):
            raise ResourceNotFoundError("Role not found.")
        return Response(RoleSerializer(role).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Access Control & RBAC"],
        summary="Update Custom Role",
        description="""
### Summary
Updates custom role metadata (name, description) and re-assigns selected permission scopes.

### Rules
- Global system standard roles cannot be altered.
- Requires `people_roles:manage` or Gym Ownership.
        """,
        request=UpdateCustomRoleSerializer,
        responses={
            200: OpenApiResponse(response=RoleSerializer, description="Custom role updated."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation error or attempt to edit standard role."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Permission denied."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Role not found."),
        },
    )
    def patch(self, request, role_id):
        try:
            role = Role.objects.select_related("gym").prefetch_related("permissions").get(id=role_id)
        except (Role.DoesNotExist, ValueError):
            raise ResourceNotFoundError("Role not found.")

        if role.gym:
            if role.gym.owner_user_id != request.user.id and not request.user.is_superuser:
                if "people_roles:manage" not in getattr(request, "scopes", []):
                    raise PermissionDeniedError("Permission denied.")

        serializer = UpdateCustomRoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated_role = update_custom_role(
            role=role,
            name=serializer.validated_data.get("name"),
            description=serializer.validated_data.get("description"),
            permission_ids=serializer.validated_data.get("permission_ids"),
        )
        updated_role = Role.objects.select_related("gym").prefetch_related("permissions").get(id=updated_role.id)
        return Response(RoleSerializer(updated_role).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Access Control & RBAC"],
        summary="Delete Custom Role",
        description="""
### Summary
Deletes an unused custom role from the gym.

### Rules
- Cannot delete global system standard roles.
- Cannot delete a role that is currently assigned to any active staff members.
        """,
        responses={
            200: OpenApiResponse(response=MessageResponseSerializer, description="Role deleted."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Cannot delete active assigned role."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Permission denied."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Role not found."),
        },
    )
    def delete(self, request, role_id):
        try:
            role = Role.objects.select_related("gym").get(id=role_id)
        except (Role.DoesNotExist, ValueError):
            raise ResourceNotFoundError("Role not found.")

        if role.gym:
            if role.gym.owner_user_id != request.user.id and not request.user.is_superuser:
                if "people_roles:manage" not in getattr(request, "scopes", []):
                    raise PermissionDeniedError("Permission denied.")

        delete_custom_role(role)
        return Response({"message": "Role successfully deleted."}, status=status.HTTP_200_OK)


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
            if "people_roles:manage" not in getattr(request, "scopes", []):
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
            if "people_roles:manage" not in getattr(request, "scopes", []):
                raise PermissionDeniedError("Permission denied.")

        remove_staff_assignment(assignment)
        return Response({"message": "Staff member access revoked."}, status=status.HTTP_200_OK)
