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
    UserContactInfoSerializer,
    UserContactInfoUpdateSerializer,
    UserTwoFactorToggleSerializer,
    UserDeviceSerializer,
    UserSecuritySettingsSerializer,
    ChangePasswordSerializer,
)
from apps.users.services import (
    update_user_settings,
    block_user_for_user,
    unblock_user_for_user,
    apply_user_access_control_action,
    get_user_contact_info,
    update_user_contact_info,
    get_user_security_overview,
    toggle_user_2fa,
    list_user_devices,
    delete_user_device,
    change_password,
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
    - Display Preferences (language, video autoplay, dark mode)
    - Privacy & Audience (who can follow, who can message, who can see followers/following, private profile)
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
Returns the current `UserSetting` state including personal display choices (language, video autoplay, dark mode), audience privacy rules (who can follow, who can message, follower/following visibility), and account status timestamps.
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
- `video_autoplay` (optional, boolean): Video Autoplay toggle (ON/OFF).
- `dark_mode` (optional, boolean): Dark mode theme toggle (ON/OFF).
- `is_private` (optional, boolean): Sets account visibility to private profile.
- `require_follow_approval` (optional, boolean): Require confirmation before someone can follow you.
- `who_can_follow` (optional, enum): `'everyone'`, `'friends_of_friends'`.
- `who_can_follow_me` (optional, enum): Alias for `who_can_follow`.
- `who_can_message` (optional, enum): `'everyone'`, `'followers'`, `'no_one'`. Default is `'followers'`.
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


# ==============================================================================
# SECTION 5: LOGIN AND SECURITY VIEWS
# ==============================================================================

class UserSecuritySettingsView(APIView):
    """
    Overview endpoint for Login and Security settings.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["User Settings - Login & Security"],
        summary="Retrieve Login and Security Overview",
        description="""
### Summary
Retrieves comprehensive Login and Security settings including:
- Contact info (primary email, optional secondary email, optional phone)
- Two Factor Authentication (2FA) status (ON/OFF)
- Active logged-in devices count (max 5)
- Account status (deactivation, deletion grace period status)
        """,
        responses={
            200: OpenApiResponse(response=UserSecuritySettingsSerializer, description="Security settings overview retrieved successfully."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
        },
    )
    def get(self, request):
        overview = get_user_security_overview(request.user)
        return Response(UserSecuritySettingsSerializer(overview).data, status=status.HTTP_200_OK)


class UserContactInfoView(APIView):
    """
    Endpoint for retrieving and updating user contact info.
    Primary email cannot be updated or deleted.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["User Settings - Login & Security"],
        summary="Retrieve Contact Information",
        description="""
### Summary
Retrieves the user's contact information:
- Primary email (immutable/read-only)
- Secondary email (optional)
- Phone number (optional)
        """,
        responses={
            200: OpenApiResponse(response=UserContactInfoSerializer, description="Contact information retrieved successfully."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
        },
    )
    def get(self, request):
        contact_info = get_user_contact_info(request.user)
        return Response(UserContactInfoSerializer(contact_info).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["User Settings - Login & Security"],
        summary="Update Contact Information",
        description="""
### Summary
Updates optional secondary email and/or phone.
Primary email is immutable and cannot be updated or deleted.

### Validation Rules
- `primary_email` or `email`: Attempting to submit either will return a 400 Bad Request error.
- `secondary_email`: Valid email string, or null/empty to remove. Cannot be identical to primary email.
- `phone`: Max 50 characters, or null/empty to remove.
        """,
        request=UserContactInfoUpdateSerializer,
        responses={
            200: OpenApiResponse(response=UserContactInfoSerializer, description="Contact information updated successfully."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure or primary email modification attempt."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
        },
    )
    def patch(self, request):
        serializer = UserContactInfoUpdateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        user = update_user_contact_info(
            user=request.user,
            secondary_email=serializer.validated_data.get("secondary_email", ...),
            phone=serializer.validated_data.get("phone", ...),
        )
        return Response(UserContactInfoSerializer(get_user_contact_info(user)).data, status=status.HTTP_200_OK)


class UserSecurityChangePasswordView(APIView):
    """
    Endpoint for authenticated password change under Login and Security.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["User Settings - Login & Security"],
        summary="Change Password",
        description="""
### Summary
Changes account password for the logged-in user after verifying current password.

### Request Body
- `current_password` (required): Current account password.
- `new_password` (required): New password (at least 8 characters).
- `confirm_password` (optional): Confirmation password matching new password.
        """,
        request=ChangePasswordSerializer,
        responses={
            200: OpenApiResponse(response=MessageResponseSerializer, description="Password successfully changed."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Incorrect current password or weak new password."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
        },
    )
    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        change_password(
            user=request.user,
            current_password=serializer.validated_data["current_password"],
            new_password=serializer.validated_data["new_password"],
        )
        return Response({"message": "Password successfully changed."}, status=status.HTTP_200_OK)


class UserTwoFactorSettingsView(APIView):
    """
    Endpoint for viewing and toggling Two Factor Authentication state.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["User Settings - Login & Security"],
        summary="Retrieve 2FA Status",
        description="Retrieves whether Two Factor Authentication (2FA) is enabled for the account.",
        responses={
            200: OpenApiResponse(response=UserTwoFactorToggleSerializer, description="2FA status retrieved."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
        },
    )
    def get(self, request):
        setting = request.user.get_settings()
        return Response({"two_factor_enabled": setting.two_factor_enabled}, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["User Settings - Login & Security"],
        summary="Toggle 2FA (ON/OFF)",
        description="""
### Summary
Enables or disables Two Factor Authentication for the account.
When ON, subsequent logins will require a 6-digit OTP code dispatched via fallback:
Primary Email -> Secondary Email -> Phone SMS.
        """,
        request=UserTwoFactorToggleSerializer,
        responses={
            200: OpenApiResponse(response=UserTwoFactorToggleSerializer, description="2FA status updated."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
        },
    )
    def patch(self, request):
        serializer = UserTwoFactorToggleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        enabled = toggle_user_2fa(request.user, serializer.validated_data["two_factor_enabled"])
        return Response({"two_factor_enabled": enabled}, status=status.HTTP_200_OK)


class UserDeviceListView(APIView):
    """
    Endpoint for listing active logged-in devices (max 5).
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["User Settings - Login & Security"],
        summary="List Logged-In Devices",
        description="""
### Summary
Lists all active logged-in devices for the authenticated user profile (up to 5 devices).
Each device record displays device identifier, friendly name, IP address, user agent, and last active timestamp.
        """,
        responses={
            200: OpenApiResponse(response=UserDeviceSerializer(many=True), description="Logged-in devices list retrieved."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
        },
    )
    def get(self, request):
        devices = list_user_devices(request.user)
        return Response(UserDeviceSerializer(devices, many=True, context={"request": request}).data, status=status.HTTP_200_OK)


class UserDeviceDetailView(APIView):
    """
    Endpoint for deleting a logged-in device and cleaning its keys.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["User Settings - Login & Security"],
        summary="Delete Logged-In Device",
        description="""
### Summary
Removes a logged-in device session.
- Revokes active authentication tokens associated with the device.
- Cleans and purges all cryptographic device keys (`UserDeviceKey`) stored for this device.
        """,
        parameters=[
            OpenApiParameter(
                name="device_id",
                description="Client device identifier string or device record UUID.",
                required=True,
                type=str,
                location=OpenApiParameter.PATH,
            )
        ],
        responses={
            200: OpenApiResponse(response=MessageResponseSerializer, description="Device removed and keys cleaned successfully."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Device not found."),
        },
    )
    def delete(self, request, device_id):
        delete_user_device(request.user, device_id)
        return Response(
            {"message": "Device removed and device key cleaned successfully."},
            status=status.HTTP_200_OK,
        )


