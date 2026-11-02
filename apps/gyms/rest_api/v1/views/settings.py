from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter

from apps.gyms.rest_api.v1.serializers import (
    GymSettingSerializer,
    GymSettingUpdateSerializer,
    GymBlockedUserSerializer,
    GymBlockUserCreateSerializer,
    GymUserSearchToBlockSerializer,
    GymAccessControlActionSerializer,
)
from apps.gyms.services import (
    update_gym_settings,
    block_user_for_gym,
    unblock_user_for_gym,
    apply_access_control_action,
)
from apps.gyms.selectors import (
    get_gym_settings,
    list_blocked_users_for_gym,
    search_users_to_block_for_gym,
)
from apps.gyms.rest_api.v1.views.base import resolve_gym_context, check_gym_permission
from common.serializers import ErrorDetailSerializer, MessageResponseSerializer


class GymSettingsView(APIView):
    """
    API endpoint for retrieving and updating gym settings.

    Covers:
    - Preference: Display (language, video autoplay, dark mode)
    - Privacy and Sharing: Alerts (admin logs, issues)
    - Privacy and Sharing: Audience (messaging, join requests, member roster, followees, age restriction)
    - Visibility: Access & Control (deactivation, publishing, deletion)
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Gym Settings"],
        summary="Retrieve Gym Settings",
        description="""
### Summary
Retrieves comprehensive gym workspace settings spanning Display preferences, Alert notification toggles, Audience & Sharing rules, and Access & Control lifecycle states.

### Authorization & Scopes
- **Authentication**: Required (`Bearer <JWT>`).
- **Required Permission**: Gym Owner or active Gym Context Token with `gym_profile:read` scope.

### Error Codes
- `401 Unauthorized`: Missing or invalid authentication token.
- `403 Forbidden`: User does not possess the required `gym_profile:read` scope.
- `404 Not Found`: Target gym workspace not found.
        """,
        parameters=[
            OpenApiParameter(
                name="gym_id",
                description="Target Gym UUID if not using a gym context JWT token.",
                required=False,
                type=str,
            )
        ],
        responses={
            200: OpenApiResponse(response=GymSettingSerializer, description="Gym settings retrieved successfully."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Permission denied."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Gym not found."),
        },
    )
    def get(self, request):
        gym = resolve_gym_context(request)
        check_gym_permission(request, gym, required_scope="gym_profile:read")
        settings_obj = get_gym_settings(str(gym.id))
        return Response(GymSettingSerializer(settings_obj).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Gym Settings"],
        summary="Update Gym Settings",
        description="""
### Summary
Performs partial update (PATCH) of gym configuration settings across Display, Alerts, Audience, and Access & Control.

### Authorization & Scopes
- **Authentication**: Required (`Bearer <JWT>`).
- **Required Permission**: Gym Owner or active Gym Context Token with `gym_profile:edit` scope.

### Error Codes
- `400 Bad Request`: Payload validation error or invalid enum value.
- `401 Unauthorized`: Missing or invalid authentication token.
- `403 Forbidden`: User does not possess the required `gym_profile:edit` scope.
- `404 Not Found`: Target gym workspace not found.
        """,
        parameters=[
            OpenApiParameter(
                name="gym_id",
                description="Target Gym UUID if not using a gym context JWT token.",
                required=False,
                type=str,
            )
        ],
        request=GymSettingUpdateSerializer,
        responses={
            200: OpenApiResponse(response=GymSettingSerializer, description="Gym settings updated successfully."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Permission denied."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Gym not found."),
        },
    )
    def patch(self, request):
        gym = resolve_gym_context(request)
        check_gym_permission(request, gym, required_scope="gym_profile:edit")

        serializer = GymSettingUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated_settings = update_gym_settings(gym, **serializer.validated_data)
        return Response(GymSettingSerializer(updated_settings).data, status=status.HTTP_200_OK)


class GymBlockedUsersListView(APIView):
    """
    API endpoint for listing and adding blocked users for a gym.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Gym Settings - Blocking"],
        summary="List Blocked Users",
        description="""
### Summary
Retrieves a paginated list of all users currently blocked from interacting with this gym workspace.

### Authorization & Scopes
- **Authentication**: Required (`Bearer <JWT>`).
- **Required Permission**: Gym Owner or active Gym Context Token with `gym_profile:read` scope.

### Error Codes
- `401 Unauthorized`: Missing or invalid authentication token.
- `403 Forbidden`: User does not possess the required `gym_profile:read` scope.
- `404 Not Found`: Target gym workspace not found.
        """,
        parameters=[
            OpenApiParameter(
                name="gym_id",
                description="Target Gym UUID if not using a gym context JWT token.",
                required=False,
                type=str,
            )
        ],
        responses={
            200: OpenApiResponse(response=GymBlockedUserSerializer(many=True), description="List of blocked users."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Permission denied."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Gym not found."),
        },
    )
    def get(self, request):
        gym = resolve_gym_context(request)
        check_gym_permission(request, gym, required_scope="gym_profile:read")
        blocked_qs = list_blocked_users_for_gym(str(gym.id))
        return Response(GymBlockedUserSerializer(blocked_qs, many=True).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Gym Settings - Blocking"],
        summary="Block a User",
        description="""
### Summary
Blocks a user from interacting with this gym workspace. The gym owner cannot be blocked.

### Authorization & Scopes
- **Authentication**: Required (`Bearer <JWT>`).
- **Required Permission**: Gym Owner or active Gym Context Token with `gym_profile:edit` scope.

### Error Codes
- `400 Bad Request`: Invalid payload or attempting to block the gym owner.
- `401 Unauthorized`: Missing or invalid authentication token.
- `403 Forbidden`: User does not possess the required `gym_profile:edit` scope.
- `404 Not Found`: Target gym workspace or user to block not found.
        """,
        parameters=[
            OpenApiParameter(
                name="gym_id",
                description="Target Gym UUID if not using a gym context JWT token.",
                required=False,
                type=str,
            )
        ],
        request=GymBlockUserCreateSerializer,
        responses={
            201: OpenApiResponse(response=GymBlockedUserSerializer, description="User successfully blocked."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation error."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Permission denied."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="User not found."),
        },
    )
    def post(self, request):
        gym = resolve_gym_context(request)
        check_gym_permission(request, gym, required_scope="gym_profile:edit")

        serializer = GymBlockUserCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        blocked = block_user_for_gym(
            gym=gym,
            user_id=str(serializer.validated_data["user_id"]),
            blocked_by_user=request.user,
            reason=serializer.validated_data.get("reason"),
        )
        return Response(GymBlockedUserSerializer(blocked).data, status=status.HTTP_201_CREATED)


class GymBlockedUserDetailView(APIView):
    """
    API endpoint for removing a block on a user for a gym.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Gym Settings - Blocking"],
        summary="Unblock a User",
        description="""
### Summary
Removes an active block on a user for this gym workspace, allowing them to interact with the gym again.

### Authorization & Scopes
- **Authentication**: Required (`Bearer <JWT>`).
- **Required Permission**: Gym Owner or active Gym Context Token with `gym_profile:edit` scope.

### Error Codes
- `401 Unauthorized`: Missing or invalid authentication token.
- `403 Forbidden`: User does not possess the required `gym_profile:edit` scope.
- `404 Not Found`: Blocked user record or gym workspace not found.
        """,
        parameters=[
            OpenApiParameter(
                name="gym_id",
                description="Target Gym UUID if not using a gym context JWT token.",
                required=False,
                type=str,
            )
        ],
        responses={
            200: OpenApiResponse(response=MessageResponseSerializer, description="User unblocked successfully."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Permission denied."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Blocked user not found."),
        },
    )
    def delete(self, request, user_id):
        gym = resolve_gym_context(request)
        check_gym_permission(request, gym, required_scope="gym_profile:edit")
        unblock_user_for_gym(gym=gym, user_id=str(user_id))
        return Response({"message": "User unblocked successfully."}, status=status.HTTP_200_OK)


class GymSearchUsersToBlockView(APIView):
    """
    API endpoint for searching users to block.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Gym Settings - Blocking"],
        summary="Search Users to Block",
        description="""
### Summary
Searches active Manygym users by name or email to select for blocking. Automatically excludes the gym owner and users who are already blocked.

### Authorization & Scopes
- **Authentication**: Required (`Bearer <JWT>`).
- **Required Permission**: Gym Owner or active Gym Context Token with `gym_profile:read` scope.

### Error Codes
- `401 Unauthorized`: Missing or invalid authentication token.
- `403 Forbidden`: User does not possess the required `gym_profile:read` scope.
- `404 Not Found`: Target gym workspace not found.
        """,
        parameters=[
            OpenApiParameter(
                name="gym_id",
                description="Target Gym UUID if not using a gym context JWT token.",
                required=False,
                type=str,
            ),
            OpenApiParameter(
                name="q",
                description="Search query string matching first name, last name, or email.",
                required=False,
                type=str,
            ),
        ],
        responses={
            200: OpenApiResponse(response=GymUserSearchToBlockSerializer(many=True), description="Matching users list."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Permission denied."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Gym not found."),
        },
    )
    def get(self, request):
        gym = resolve_gym_context(request)
        check_gym_permission(request, gym, required_scope="gym_profile:read")
        query = request.query_params.get("q", "")
        users = search_users_to_block_for_gym(str(gym.id), query=query)
        return Response(GymUserSearchToBlockSerializer(users, many=True).data, status=status.HTTP_200_OK)


class GymAccessControlActionView(APIView):
    """
    API endpoint for executing lifecycle state transitions on a gym workspace.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Gym Settings - Access & Control"],
        summary="Perform Access & Control Action",
        description="""
### Summary
Executes administrative lifecycle transitions on a gym workspace:
- `deactivate`: Temporarily suspend gym operations.
- `reactivate`: Restore gym operations from suspension.
- `unpublish`: Hide gym from public directory searches.
- `publish`: Make gym visible in public directory searches.
- `delete`: Soft-delete gym workspace.
- `restore`: Restore soft-deleted gym workspace.

### Authorization & Scopes
- **Authentication**: Required (`Bearer <JWT>`).
- **Required Permission**: Gym Owner or active Gym Context Token with `gym_profile:edit` scope.

### Error Codes
- `400 Bad Request`: Invalid transition action.
- `401 Unauthorized`: Missing or invalid authentication token.
- `403 Forbidden`: User does not possess the required `gym_profile:edit` scope.
- `404 Not Found`: Target gym workspace not found.
        """,
        parameters=[
            OpenApiParameter(
                name="gym_id",
                description="Target Gym UUID if not using a gym context JWT token.",
                required=False,
                type=str,
            )
        ],
        request=GymAccessControlActionSerializer,
        responses={
            200: OpenApiResponse(response=GymSettingSerializer, description="Gym settings after state transition."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Permission denied."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Gym not found."),
        },
    )
    def post(self, request):
        gym = resolve_gym_context(request)
        check_gym_permission(request, gym, required_scope="gym_profile:edit")

        serializer = GymAccessControlActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated_settings = apply_access_control_action(
            gym=gym,
            action=serializer.validated_data["action"],
            user=request.user,
        )
        return Response(GymSettingSerializer(updated_settings).data, status=status.HTTP_200_OK)
