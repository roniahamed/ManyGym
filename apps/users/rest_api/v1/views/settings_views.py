from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter

from apps.users.rest_api.v1.serializers import (
    UserSettingSerializer,
    UserSettingUpdateSerializer,
    UserBlockedUserSerializer,
    UserBlockUserCreateSerializer,
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
        description="Retrieves comprehensive settings for the authenticated user.",
        responses={
            200: OpenApiResponse(response=UserSettingSerializer, description="User settings retrieved."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
        },
    )
    def get(self, request):
        settings_obj = get_user_settings(request.user)
        return Response(UserSettingSerializer(settings_obj).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["User Settings"],
        summary="Update User Settings",
        description="Updates personal preferences, privacy rules, or private profile toggle.",
        request=UserSettingUpdateSerializer,
        responses={
            200: OpenApiResponse(response=UserSettingSerializer, description="User settings updated."),
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
        description="Retrieves a list of all users blocked by the authenticated user.",
        responses={
            200: OpenApiResponse(response=UserBlockedUserSerializer(many=True), description="Blocked users list."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
        },
    )
    def get(self, request):
        blocked_users = list_blocked_users_for_user(request.user)
        return Response(UserBlockedUserSerializer(blocked_users, many=True).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["User Settings - Blocking"],
        summary="Block User",
        description="Blocks another user. Automatically severs any mutual follow relationship.",
        request=UserBlockUserCreateSerializer,
        responses={
            201: OpenApiResponse(response=UserBlockedUserSerializer, description="User successfully blocked."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure."),
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
        description="Removes a block on a previously restricted user.",
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
        description="Searches active users by name or email to select for blocking.",
        parameters=[
            OpenApiParameter(name="q", description="Search query string.", required=False, type=str),
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
        description="Blocks an existing follower and immediately removes them from your followers.",
        responses={
            200: OpenApiResponse(response=MessageResponseSerializer, description="Follower blocked and removed."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="User not found."),
        },
    )
    def post(self, request, user_id):
        reason = request.data.get("reason", "Blocked from followers list")
        block_user_for_user(
            blocker=request.user,
            user_id=str(user_id),
            reason=reason,
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
Executes account lifecycle state transitions on the authenticated user profile:
- `deactivate`: Temporarily suspend personal account.
- `reactivate`: Restore personal account from suspension.
- `delete`: Soft-delete personal user account (requires `password` and `confirmation: "delete"`).
- `restore`: Restore soft-deleted account (requires `password`).
        """,
        request=UserAccessControlActionSerializer,
        responses={
            200: OpenApiResponse(response=UserSettingSerializer, description="Settings after state transition."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure."),
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

