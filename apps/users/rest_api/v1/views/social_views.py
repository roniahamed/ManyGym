import uuid
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter, OpenApiTypes

from apps.users.rest_api.v1.serializers import (
    FollowUserItemSerializer,
    UserFollowActionResponseSerializer,
    FollowActionSerializer,
    FollowActionResponseSerializer,
    UnifiedTargetFollowersResponseSerializer,
    UnifiedFollowedAccountsResponseSerializer,
)
from apps.users.services import (
    follow_user,
    unfollow_user,
)
from apps.gyms.services import (
    follow_gym,
    unfollow_gym,
)
from apps.users.selectors import (
    list_user_followers,
    list_user_following,
    is_following_user,
    resolve_target_entity,
)
from apps.gyms.selectors import (
    list_gym_followers,
    list_user_followed_gyms,
    is_following_gym,
)
from apps.gyms.rest_api.v1.serializers import GymFollowerItemSerializer, FollowedGymItemSerializer
from common.exceptions import DomainValidationError
from common.serializers import ErrorDetailSerializer
from common.pagination import StandardResultsSetPagination


class UserFollowToggleView(APIView):
    """
    API endpoint for following or unfollowing a public user.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["User Social & Follow"],
        summary="Follow a User",
        request=None,
        description="Follows a target user if the target user account is public and active.",
        responses={
            201: OpenApiResponse(response=UserFollowActionResponseSerializer, description="Successfully followed user."),
            200: OpenApiResponse(response=UserFollowActionResponseSerializer, description="Already following user."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Invalid request (e.g. self-follow)."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Target user is private."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Target user not found."),
        },
    )
    def post(self, request, user_id):
        follow_obj, created = follow_user(follower=request.user, target_user_id=user_id)
        status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        message = "Successfully followed user." if created else "Already following user."
        return Response(
            {
                "message": message,
                "is_following": True,
                "target_user_id": str(user_id),
            },
            status=status_code,
        )

    @extend_schema(
        tags=["User Social & Follow"],
        summary="Unfollow a User",
        description="Unfollows a target user that was previously followed.",
        responses={
            200: OpenApiResponse(response=UserFollowActionResponseSerializer, description="Successfully unfollowed user."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Invalid target user ID."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Not currently following user or user not found."),
        },
    )
    def delete(self, request, user_id):
        unfollow_user(follower=request.user, target_user_id=user_id)
        return Response(
            {
                "message": "Successfully unfollowed user.",
                "is_following": False,
                "target_user_id": str(user_id),
            },
            status=status.HTTP_200_OK,
        )


class UserFollowersListView(APIView):
    """
    API endpoint for listing followers of a specific user.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["User Social & Follow"],
        summary="List User Followers",
        description="Lists all users who follow the specified user. Restricted if the target user is private.",
        responses={
            200: OpenApiResponse(response=FollowUserItemSerializer(many=True), description="List of user followers."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="User account is private."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="User not found."),
        },
    )
    def get(self, request, user_id):
        target = request.user if str(user_id) == str(request.user.id) else user_id
        followers_qs = list_user_followers(user_id=target, requesting_user=request.user)

        if request.query_params.get("page") or request.query_params.get("page_size"):
            paginator = StandardResultsSetPagination()
            page_results = paginator.paginate_queryset(followers_qs, request)
            serializer = FollowUserItemSerializer(page_results, many=True, context={"relation_type": "follower"})
            return paginator.get_paginated_response(serializer.data)

        serializer = FollowUserItemSerializer(followers_qs, many=True, context={"relation_type": "follower"})
        return Response(serializer.data, status=status.HTTP_200_OK)


class UserFollowingListView(APIView):
    """
    API endpoint for listing accounts followed by a specific user.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["User Social & Follow"],
        summary="List User Following",
        description="""
### Summary
Lists all users that the specified user is following. Restricted if the target user is private.

### Authentication & Authorization
- **Authentication**: Bearer JWT token required.
- **Authorization**: Public for open profiles. If the target user is private, only the account owner can view.
        """,
        parameters=[
            OpenApiParameter(name="page", type=int, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="page_size", type=int, location=OpenApiParameter.QUERY, required=False),
        ],
        responses={
            200: OpenApiResponse(response=FollowUserItemSerializer(many=True), description="List of users followed."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="User account is private."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="User not found."),
        },
    )
    def get(self, request, user_id):
        target = request.user if str(user_id) == str(request.user.id) else user_id
        following_qs = list_user_following(user_id=target, requesting_user=request.user)

        if request.query_params.get("page") or request.query_params.get("page_size"):
            paginator = StandardResultsSetPagination()
            page_results = paginator.paginate_queryset(following_qs, request)
            serializer = FollowUserItemSerializer(page_results, many=True, context={"relation_type": "following"})
            return paginator.get_paginated_response(serializer.data)

        serializer = FollowUserItemSerializer(following_qs, many=True, context={"relation_type": "following"})
        return Response(serializer.data, status=status.HTTP_200_OK)


class UnifiedFollowView(APIView):
    """
    Unified API endpoint for following and unfollowing Users or Gyms.
    Target entity type (user vs gym) is automatically detected if omitted.
    Supports both POST (follow/unfollow) and DELETE (unfollow).
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Unified Social Follow"],
        summary="Follow or Unfollow a User or Gym",
        description="""
### Summary
Unified single endpoint to follow or unfollow any public User or Gym.

### Auto-Detection
`target_type` is **automatically detected** from the database (whether UUID is a Gym or User).

### Request
- Pass `target_id` (or `id`) in JSON body (`{"target_id": "<uuid>"}`) or directly in URL path (`/api/v1/follows/<target_id>/`).
- Optional `action`: `"follow"` (default) or `"unfollow"`.
        """,
        parameters=[
            OpenApiParameter(
                name="target_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                required=False,
                description="UUID of target User or Gym to unfollow (if not supplied in URL path or JSON request body).",
            ),
        ],
        request=FollowActionSerializer,
        responses={
            201: OpenApiResponse(response=FollowActionResponseSerializer, description="Successfully followed target."),
            200: OpenApiResponse(response=FollowActionResponseSerializer, description="Successfully unfollowed target or already following."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure or self-follow attempt."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Target user is private or user is blocked by gym."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Target entity not found."),
        },
    )
    def post(self, request, target_id=None):
        data = {}
        if request.query_params:
            data.update(request.query_params.dict())
        if request.data and isinstance(request.data, dict):
            data.update(request.data)
        if target_id:
            data["target_id"] = str(target_id)
        serializer = FollowActionSerializer(data=data, context={"target_id": target_id})
        serializer.is_valid(raise_exception=True)

        raw_id = serializer.validated_data["target_id"]
        raw_type = serializer.validated_data.get("target_type")
        action = serializer.validated_data.get("action", "follow").lower()

        target_info = resolve_target_entity(raw_id, raw_type)
        target_type, resolved_id = target_info
        entity = getattr(target_info, "entity", None)

        if action == "unfollow":
            return self._perform_unfollow(request.user, target_type, resolved_id)
        return self._perform_follow(request.user, target_type, entity or resolved_id)

    @extend_schema(
        tags=["Unified Social Follow"],
        summary="Unfollow a User or Gym",
        description="""
### Summary
Unfollows a previously followed User or Gym.

### Auto-Detection
`target_type` is **automatically detected**.

### Parameters
Parameters can be sent via:
1. URL path: `/api/v1/follows/<target_id>/`
2. JSON body: `{"target_id": "<uuid>"}`
3. Query param: `?target_id=<uuid>`
        """,
        parameters=[
            OpenApiParameter(
                name="target_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                required=False,
                description="UUID of target User or Gym to unfollow (if not supplied in URL path or JSON request body).",
            ),
        ],
        request=FollowActionSerializer,
        responses={
            200: OpenApiResponse(response=FollowActionResponseSerializer, description="Successfully unfollowed target."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Not currently following target or target not found."),
        },
    )
    def delete(self, request, target_id=None):
        data = {}
        if request.query_params:
            data.update(request.query_params.dict())
        if request.data and isinstance(request.data, dict):
            data.update(request.data)
        if target_id:
            data["target_id"] = str(target_id)
        serializer = FollowActionSerializer(data=data, context={"target_id": target_id})
        serializer.is_valid(raise_exception=True)

        raw_id = serializer.validated_data["target_id"]
        raw_type = serializer.validated_data.get("target_type")

        target_info = resolve_target_entity(raw_id, raw_type)
        target_type, resolved_id = target_info
        return self._perform_unfollow(request.user, target_type, resolved_id)

    @extend_schema(
        tags=["Unified Social Follow"],
        summary="Get Followers or Following List",
        description="""
### Summary
- If `target_id` is supplied (in URL path or query param), returns the **followers list** of the target User or Gym. Target entity type is **automatically detected**. Respects target privacy settings (returns 403 if restricted).
- If `target_id` is omitted, returns the list of entities (Users and Gyms) followed by the current authenticated user.

### Authentication & Authorization
- **Authentication**: Bearer JWT token required.
- **Authorization**: Authenticated users. Restricted if target User is private or target Gym followers visibility is restricted.
        """,
        parameters=[
            OpenApiParameter(name="target_id", type=uuid.UUID, location=OpenApiParameter.QUERY, required=False, description="UUID of target entity."),
            OpenApiParameter(name="page", type=int, location=OpenApiParameter.QUERY, required=False, description="Page number."),
            OpenApiParameter(name="page_size", type=int, location=OpenApiParameter.QUERY, required=False, description="Page size (max 100)."),
        ],
        responses={
            200: OpenApiResponse(response=UnifiedTargetFollowersResponseSerializer, description="Followers list of target entity (or followed accounts if target_id omitted)."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Target is private or restricted by settings."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Target entity not found."),
        },
    )
    def get(self, request, target_id=None):
        raw_id = target_id or request.query_params.get("target_id") or request.query_params.get("id")
        if not raw_id:
            user_following_qs = list_user_following(user_id=request.user, requesting_user=request.user)
            followed_gyms_qs = list_user_followed_gyms(user=request.user)

            if request.query_params.get("page") or request.query_params.get("page_size"):
                paginator = StandardResultsSetPagination()
                page_users = paginator.paginate_queryset(user_following_qs, request)
                page_gyms = list(followed_gyms_qs[:paginator.get_page_size(request) or 20])
                payload = {
                    "followed_users": FollowUserItemSerializer(page_users, many=True, context={"relation_type": "following"}).data,
                    "followed_gyms": FollowedGymItemSerializer(page_gyms, many=True).data,
                    "total_followed_users": user_following_qs.count(),
                    "total_followed_gyms": followed_gyms_qs.count(),
                }
                return paginator.get_paginated_response(payload)

            followed_users_data = FollowUserItemSerializer(user_following_qs, many=True, context={"relation_type": "following"}).data
            followed_gyms_data = FollowedGymItemSerializer(followed_gyms_qs, many=True).data
            payload = {
                "followed_users": followed_users_data,
                "followed_gyms": followed_gyms_data,
                "total_followed_users": len(followed_users_data),
                "total_followed_gyms": len(followed_gyms_data),
            }
            return Response(payload, status=status.HTTP_200_OK)

        target_info = resolve_target_entity(raw_id)
        target_type, resolved_id = target_info
        entity = getattr(target_info, "entity", None)

        if target_type == "user":
            followers_qs = list_user_followers(user_id=entity or resolved_id, requesting_user=request.user)

            if request.query_params.get("page") or request.query_params.get("page_size"):
                paginator = StandardResultsSetPagination()
                page_results = paginator.paginate_queryset(followers_qs, request)
                followers_data = FollowUserItemSerializer(page_results, many=True, context={"relation_type": "follower"}).data
                is_following = is_following_user(request.user, resolved_id)
                return paginator.get_paginated_response({
                    "target_type": "user",
                    "target_id": str(resolved_id),
                    "followers_count": paginator.page.paginator.count,
                    "is_following": is_following,
                    "followers": followers_data,
                })

            followers_data = FollowUserItemSerializer(followers_qs, many=True, context={"relation_type": "follower"}).data
            if request.user.id == resolved_id:
                is_following = False
            else:
                user_in_data = any(item["user_id"] == request.user.id for item in followers_data)
                is_following = True if user_in_data else is_following_user(request.user, resolved_id)

            return Response(
                {
                    "target_type": "user",
                    "target_id": str(resolved_id),
                    "followers_count": len(followers_data),
                    "is_following": is_following,
                    "followers": followers_data,
                },
                status=status.HTTP_200_OK,
            )

        # target_type == "gym"
        followers_qs = list_gym_followers(gym_id=entity or resolved_id, requesting_user=request.user)

        if request.query_params.get("page") or request.query_params.get("page_size"):
            paginator = StandardResultsSetPagination()
            page_results = paginator.paginate_queryset(followers_qs, request)
            followers_data = GymFollowerItemSerializer(page_results, many=True).data
            return paginator.get_paginated_response({
                "target_type": "gym",
                "target_id": str(resolved_id),
                "followers_count": paginator.page.paginator.count,
                "is_following": is_following_gym(request.user, resolved_id),
                "followers": followers_data,
            })

        followers_data = GymFollowerItemSerializer(followers_qs, many=True).data
        user_in_data = any(item["user_id"] == request.user.id for item in followers_data)
        is_following = True if user_in_data else is_following_gym(request.user, resolved_id)

        return Response(
            {
                "target_type": "gym",
                "target_id": str(resolved_id),
                "followers_count": len(followers_data),
                "is_following": is_following,
                "followers": followers_data,
            },
            status=status.HTTP_200_OK,
        )

    def _perform_follow(self, user, target_type: str, target_id):
        if target_type == "user":
            follow_obj, created = follow_user(follower=user, target_user_id=target_id)
            target_name = f"{follow_obj.followed_user.first_name} {follow_obj.followed_user.last_name}".strip()
            status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
            message = "Successfully followed user." if created else "Already following user."
        elif target_type == "gym":
            follow_obj, created = follow_gym(user=user, gym_id=target_id)
            target_name = follow_obj.gym.name
            status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
            message = "Successfully followed gym." if created else "Already following gym."
        else:
            raise DomainValidationError(f"Invalid target_type '{target_type}'. Must be 'user' or 'gym'.")

        return Response(
            {
                "message": message,
                "is_following": True,
                "target_type": target_type,
                "target_id": str(getattr(target_id, "id", target_id)),
                "target_name": target_name,
            },
            status=status_code,
        )

    def _perform_unfollow(self, user, target_type: str, target_id):
        resolved_uuid = getattr(target_id, "id", target_id)
        if target_type == "user":
            unfollow_user(follower=user, target_user_id=resolved_uuid)
            message = "Successfully unfollowed user."
        elif target_type == "gym":
            unfollow_gym(user=user, gym_id=resolved_uuid)
            message = "Successfully unfollowed gym."
        else:
            raise DomainValidationError(f"Invalid target_type '{target_type}'. Must be 'user' or 'gym'.")

        return Response(
            {
                "message": message,
                "is_following": False,
                "target_type": target_type,
                "target_id": str(resolved_uuid),
                "target_name": None,
            },
            status=status.HTTP_200_OK,
        )
