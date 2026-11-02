from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiExample, OpenApiParameter

from apps.access_control.models import Role
from apps.access_control.rest_api.v1.serializers import (
    RoleSerializer,
    CreateCustomRoleSerializer,
    UpdateCustomRoleSerializer,
)
from apps.access_control.selectors import list_gym_roles
from apps.access_control.services import (
    create_custom_role,
    update_custom_role,
    delete_custom_role,
)
from apps.access_control.rest_api.v1.views.base_views import resolve_request_gym
from common.exceptions import (
    ResourceNotFoundError,
    PermissionDeniedError,
)
from common.serializers import ErrorDetailSerializer, MessageResponseSerializer
from common.pagination import StandardResultsSetPagination


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
                if str(getattr(request, "gym_id", "")) != str(role.gym.id) or "people_roles:manage" not in getattr(request, "scopes", []):
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
                if str(getattr(request, "gym_id", "")) != str(role.gym.id) or "people_roles:manage" not in getattr(request, "scopes", []):
                    raise PermissionDeniedError("Permission denied.")

        delete_custom_role(role)
        return Response({"message": "Role successfully deleted."}, status=status.HTTP_200_OK)
