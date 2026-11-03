from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter, OpenApiExample

from apps.users.rest_api.v1.serializers import (
    UserSettingSerializer,
    UserSettingUpdateSerializer,
    UserBlockedUserSerializer,
    UserBlockUserCreateSerializer,
    UserFollowerBlockCreateSerializer,
    UserSearchToBlockSerializer,
    UserAccessControlActionSerializer,
)
from apps.users.services import (
    update_user_settings,
    block_user_for_user,
    unblock_user_for_user,
    apply_user_access_control_action,
)
from apps.users.selectors import (
    get_user_settings,
    list_blocked_users_for_user,
    search_users_to_block_for_user,
)
from common.serializers import ErrorDetailSerializer, MessageResponseSerializer


class UserSettingsView(APIView):
    """
    API endpoint for retrieving and updating personal user settings.

    Covers:
    - Display Preferences (language, dark mode)
    - Privacy & Audience (who can message, who can see followers/following, private profile)
    - Access & Control (deactivation, deletion)
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["User Settings"],
        summary="Retrieve User Settings",
        description="""
### Summary
Retrieves comprehensive personal profile settings for the authenticated user, covering Display Preferences, Privacy & Audience visibility, and Account Lifecycle status.

### Authentication & Authorization
- **Authentication**: Required (`Bearer <JWT>`).
- **Authorization**: Authenticated personal account context.

### Success Response
Returns the current `UserSetting` state including personal display choices, privacy rules, and account status timestamps.
        """,
        responses={
            200: OpenApiResponse(response=UserSettingSerializer, description="User settings retrieved successfully."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
        },
    )
    def get(self, request):
        settings_obj = get_user_settings(request.user)
        return Response(UserSettingSerializer(settings_obj).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["User Settings"],
        summary="Update User Settings",
        description="""
### Summary
Updates display preferences, privacy policies, audience rules, or private profile status for the authenticated user.

### Authentication & Authorization
- **Authentication**: Required (`Bearer <JWT>`).
- **Authorization**: User can only modify their own settings (strict tenant isolation).

### Request Fields
- `language` (optional, string, max 20 chars): Display language code (e.g. `'en'`, `'es'`).
- `dark_mode` (optional, boolean): Dark mode theme toggle.
- `is_private` (optional, boolean): Sets account visibility to private profile.
- `who_can_message` (optional, enum): `'everyone'`, `'followers'`, `'no_one'`.
- `who_can_see_followers` (optional, enum): `'everyone'`, `'followers'`, `'private'`.
- `who_can_see_following` (optional, enum): `'everyone'`, `'followers'`, `'private'`.

### Error Responses
- `400 Bad Request`: Validation failure or invalid enum value.
- `401 Unauthorized`: Missing or invalid credentials.
        """,
        request=UserSettingUpdateSerializer,
        responses={
            200: OpenApiResponse(response=UserSettingSerializer, description="User settings updated successfully."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
        },
    )
    def patch(self, request):
        serializer = UserSettingUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated_settings = update_user_settings(request.user, **serializer.validated_data)
        return Response(UserSettingSerializer(updated_settings).data, status=status.HTTP_200_OK)


class UserBlockedUsersListView(APIView):
    """
    API endpoint for listing and adding blocked users.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["User Settings - Blocking"],
        summary="List Blocked Users",
        description="""
### Summary
Retrieves a list of all users currently blocked by the authenticated user.

### Authentication & Authorization
- **Authentication**: Required (`Bearer <JWT>`).
- **Authorization**: Returns only the block records initiated by the authenticated user.

### Success Response
Returns array of blocked user summaries including target user id, names, email, avatar, and blocking reason.
        """,
        responses={
            200: OpenApiResponse(response=UserBlockedUserSerializer(many=True), description="Blocked users list retrieved successfully."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
        },
    )
    def get(self, request):
        blocked_users = list_blocked_users_for_user(request.user)
        return Response(UserBlockedUserSerializer(blocked_users, many=True).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["User Settings - Blocking"],
        summary="Block User",
        description="""
### Summary
Blocks another user from interacting with the authenticated user.

### Side Effects
- Automatically and immediately severs any mutual follow relationships in both directions.
- Prevents the blocked user from initiating direct messages or viewing followers/following lists.

### Request Body
- `user_id` (required, UUID): UUID of the user to block.
- `reason` (optional, string, max 255 chars): Rationale for the block.

### Error Responses
- `400 Bad Request`: Attempting to block yourself, malformed UUID, or invalid reason string.
- `401 Unauthorized`: Missing or invalid authentication token.
- `404 Not Found`: Target user does not exist.
        """,
        request=UserBlockUserCreateSerializer,
        responses={
            201: OpenApiResponse(response=UserBlockedUserSerializer, description="User successfully blocked."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure or self-block attempt."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Target user not found."),
        },
    )
    def post(self, request):
        serializer = UserBlockUserCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        blocked_obj = block_user_for_user(
            blocker=request.user,
            user_id=str(serializer.validated_data["user_id"]),
            reason=serializer.validated_data.get("reason"),
        )
        return Response(UserBlockedUserSerializer(blocked_obj).data, status=status.HTTP_201_CREATED)


class UserBlockedUserDetailView(APIView):
    """
    API endpoint for unblocking a previously blocked user.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["User Settings - Blocking"],
        summary="Unblock User",
        description="""
### Summary
Removes a block on a previously restricted user.

### Parameters
- `user_id` (path, required, UUID): UUID of the blocked user to unblock.

### Error Responses
- `401 Unauthorized`: Missing or invalid credentials.
- `404 Not Found`: Blocked user record not found (e.g. user was not blocked by caller).
        """,
        parameters=[
            OpenApiParameter(
                name="user_id",
                description="UUID of the blocked user to remove from blocklist.",
                required=True,
                type=str,
                location=OpenApiParameter.PATH,
            )
        ],
        responses={
            200: OpenApiResponse(response=MessageResponseSerializer, description="User successfully unblocked."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Blocked user record not found."),
        },
    )
    def delete(self, request, user_id):
        unblock_user_for_user(blocker=request.user, user_id=str(user_id))
        return Response({"message": "User unblocked successfully."}, status=status.HTTP_200_OK)


class UserSearchUsersToBlockView(APIView):
    """
    API endpoint for searching users to block.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["User Settings - Blocking"],
        summary="Search Users to Block",
        description="""
### Summary
Searches active Manygym users by name or email to select for blocking.

### Filtering Rules
- Automatically excludes the authenticated user themselves.
- Automatically excludes users who are already in the authenticated user's blocklist.

### Parameters
- `q` (query, optional, string): Search query matching first name, last name, or email.
        """,
        parameters=[
            OpenApiParameter(name="q", description="Search query string matching first name, last name, or email.", required=False, type=str),
        ],
        responses={
            200: OpenApiResponse(response=UserSearchToBlockSerializer(many=True), description="Matching users list."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
        },
    )
    def get(self, request):
        query = request.query_params.get("q", "")
        users = search_users_to_block_for_user(request.user, query=query)
        return Response(UserSearchToBlockSerializer(users, many=True).data, status=status.HTTP_200_OK)


class UserFollowerBlockView(APIView):
    """
    Direct endpoint allowing a user to block someone directly from their followers list.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["User Settings - Blocking"],
        summary="Block User From Followers",
        description="""
### Summary
Blocks an existing follower and immediately removes them from your followers list.

### Parameters
- `user_id` (path, required, UUID): UUID of the follower to block.

### Request Body
- `reason` (optional, string, max 255 chars): Rationale for blocking from followers list. Defaults to `'Blocked from followers list'`.

### Side Effects
- Immediately deletes the follow relation from both users.
- Creates a `UserBlockedUser` entry.

### Error Responses
- `400 Bad Request`: Validation failure or attempt to block self.
- `401 Unauthorized`: Missing or invalid credentials.
- `404 Not Found`: Target user not found.
        """,
        parameters=[
            OpenApiParameter(
                name="user_id",
                description="UUID of the follower to block and remove.",
                required=True,
                type=str,
                location=OpenApiParameter.PATH,
            )
        ],
        request=UserFollowerBlockCreateSerializer,
        responses={
            200: OpenApiResponse(response=MessageResponseSerializer, description="Follower blocked and removed."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="User not found."),
        },
    )
    def post(self, request, user_id):
        serializer = UserFollowerBlockCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        block_user_for_user(
            blocker=request.user,
            user_id=str(user_id),
            reason=serializer.validated_data.get("reason", "Blocked from followers list"),
        )
        return Response(
            {"message": "User successfully blocked and removed from followers."},
            status=status.HTTP_200_OK,
        )


class UserAccessControlActionView(APIView):
    """
    API endpoint for user profile lifecycle actions (deactivate, reactivate, delete, restore).
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["User Settings - Access & Control"],
        summary="Perform Profile Access & Control Action",
        description="""
### Summary
Executes administrative account lifecycle state transitions on the authenticated user profile.

### Actions & Workflow Rules
- `deactivate`: Temporarily suspend personal account. Revokes active session tokens.
- `reactivate`: Restore personal account from suspension. Restores `status=ACTIVE`.
- `delete`: Soft-delete personal user account. Requires valid `password` and `confirmation: "delete"`. Revokes all active session tokens.
- `restore`: Restore soft-deleted account. Requires valid `password`. Restores `status=ACTIVE`.

### Side Effects
- `deactivate` and `delete` immediately revoke all active `AuthToken` sessions.
- Deleted or deactivated accounts return structured reactivation/restoration notices upon subsequent login attempts.

### Error Responses
- `400 Bad Request`: Invalid action, incorrect password, or missing confirmation text.
- `401 Unauthorized`: Missing or invalid authentication token.
        """,
        request=UserAccessControlActionSerializer,
        responses={
            200: OpenApiResponse(response=UserSettingSerializer, description="Settings after state transition."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure or password confirmation mismatch."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
        },
    )
    def post(self, request):
        serializer = UserAccessControlActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated_settings = apply_user_access_control_action(
            user=request.user,
            action=serializer.validated_data["action"],
            password=serializer.validated_data.get("password"),
            confirmation=serializer.validated_data.get("confirmation"),
        )
        return Response(UserSettingSerializer(updated_settings).data, status=status.HTTP_200_OK)

