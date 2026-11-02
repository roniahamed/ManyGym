from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter

from apps.gyms.rest_api.v1.serializers import (
    GymFollowerItemSerializer,
    FollowedGymItemSerializer,
    GymFollowActionResponseSerializer,
)
from apps.gyms.services import (
    follow_gym,
    unfollow_gym,
)
from apps.gyms.selectors import (
    list_gym_followers,
    list_gym_following,
    list_user_followed_gyms,
)
from common.serializers import ErrorDetailSerializer
from common.pagination import StandardResultsSetPagination


class GymFollowToggleView(APIView):
    """
    API endpoint for following or unfollowing a Gym.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Gym Social & Follow"],
        summary="Follow a Gym",
        request=None,
        description="Follows a specified gym. Blocked users or inactive/deleted gyms are rejected.",
        responses={
            201: OpenApiResponse(response=GymFollowActionResponseSerializer, description="Successfully followed gym."),
            200: OpenApiResponse(response=GymFollowActionResponseSerializer, description="Already following gym."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Gym is inactive or invalid ID."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="User is blocked from following this gym."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Gym not found."),
        },
    )
    def post(self, request, gym_id):
        follow_obj, created = follow_gym(user=request.user, gym_id=gym_id)
        status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        message = "Successfully followed gym." if created else "Already following gym."
        return Response(
            {
                "message": message,
                "is_following": True,
                "gym_id": str(follow_obj.gym.id),
                "gym_name": follow_obj.gym.name,
            },
            status=status_code,
        )

    @extend_schema(
        tags=["Gym Social & Follow"],
        summary="Unfollow a Gym",
        description="Unfollows a specified gym.",
        responses={
            200: OpenApiResponse(response=GymFollowActionResponseSerializer, description="Successfully unfollowed gym."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Invalid gym ID."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Not currently following gym or gym not found."),
        },
    )
    def delete(self, request, gym_id):
        unfollow_gym(user=request.user, gym_id=gym_id)
        return Response(
            {
                "message": "Successfully unfollowed gym.",
                "is_following": False,
                "gym_id": str(gym_id),
                "gym_name": "",
            },
            status=status.HTTP_200_OK,
        )


class GymFollowersListView(APIView):
    """
    API endpoint for listing followers of a gym.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Gym Social & Follow"],
        summary="List Gym Followers",
        description="""
### Summary
Lists all users who follow the specified gym workspace.

### Authorization & Scopes
- **Authentication**: Required (`Bearer <JWT>`).
- **Required Permission**: Public (any authenticated user can inspect gym followers unless blocked).

### Error Codes
- `401 Unauthorized`: Missing or invalid authentication token.
- `404 Not Found`: Target gym workspace not found.
        """,
        parameters=[
            OpenApiParameter(
                name="page",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="A page number within the paginated result set.",
            ),
            OpenApiParameter(
                name="page_size",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Number of results to return per page.",
            ),
        ],
        responses={
            200: OpenApiResponse(response=GymFollowerItemSerializer(many=True), description="List of gym followers."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Gym not found."),
        },
    )
    def get(self, request, gym_id):
        followers_qs = list_gym_followers(gym_id=gym_id, requesting_user=request.user)

        if request.query_params.get("page") or request.query_params.get("page_size"):
            paginator = StandardResultsSetPagination()
            page_results = paginator.paginate_queryset(followers_qs, request)
            serializer = GymFollowerItemSerializer(page_results, many=True)
            return paginator.get_paginated_response(serializer.data)

        serializer = GymFollowerItemSerializer(followers_qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class UserFollowedGymsListView(APIView):
    """
    API endpoint for listing gyms followed by the current user.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Gym Social & Follow"],
        summary="List Gyms Followed by User",
        description="""
### Summary
Retrieves a list of all gym workspaces followed by the authenticated user.

### Authorization & Scopes
- **Authentication**: Required (`Bearer <JWT>`).
- **Required Permission**: Authenticated account holder (self).

### Error Codes
- `401 Unauthorized`: Missing or invalid authentication token.
        """,
        parameters=[
            OpenApiParameter(
                name="page",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="A page number within the paginated result set.",
            ),
            OpenApiParameter(
                name="page_size",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Number of results to return per page.",
            ),
        ],
        responses={
            200: OpenApiResponse(response=FollowedGymItemSerializer(many=True), description="List of followed gyms."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
        },
    )
    def get(self, request):
        followed_qs = list_user_followed_gyms(user=request.user)

        if request.query_params.get("page") or request.query_params.get("page_size"):
            paginator = StandardResultsSetPagination()
            page_results = paginator.paginate_queryset(followed_qs, request)
            serializer = FollowedGymItemSerializer(page_results, many=True)
            return paginator.get_paginated_response(serializer.data)

        serializer = FollowedGymItemSerializer(followed_qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class GymFollowingListView(APIView):
    """
    API endpoint for listing people and pages followed by a gym.
    Restricted by GymSetting.who_can_see_following (Everyone, Only members, Private).
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Gym Social & Follow"],
        summary="List People and Pages Gym Follows",
        description="Lists all people and pages followed by the gym. Restricted by GymSetting.who_can_see_following ('everyone', 'only_members', 'private').",
        responses={
            200: OpenApiResponse(description="List of accounts followed by gym."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Following list is restricted by privacy settings."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Gym not found."),
        },
    )
    def get(self, request, gym_id):
        following_list = list_gym_following(gym_id=gym_id, requesting_user=request.user)
        return Response(following_list, status=status.HTTP_200_OK)
