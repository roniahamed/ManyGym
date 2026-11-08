import uuid
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from drf_spectacular.utils import extend_schema, OpenApiParameter

from apps.posts.selectors import (
    list_gym_feed,
    get_post_detail,
    get_user_social_context,
)
from apps.posts.services import (
    create_post,
    update_post,
    delete_post,
)
from apps.posts.rest_api.v1.serializers import (
    GymFeedFilterSerializer,
    GymPostListSerializer,
    GymPostDetailSerializer,
    GymPostCreateSerializer,
    GymPostUpdateSerializer,
)
from apps.posts.rest_api.v1.views.base_views import (
    resolve_post_gym,
    check_user_is_member_or_staff,
    check_post_management_permission,
)
from common.pagination import StandardResultsSetPagination
from common.serializers import ErrorDetailSerializer


class GymFeedView(APIView):
    """
    List gym community feed posts or publish a new post with text and media.
    """
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    pagination_class = StandardResultsSetPagination

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated()]
        return [AllowAny()]

    @extend_schema(
        tags=["Community Feed"],
        summary="List Gym Community Feed",
        description="Retrieves community posts for a gym or personalized feed globally when gym_id is omitted. Unauthenticated guests and non-members see only public posts; verified members and staff see both public and members_only posts. When gym_id is omitted, returns personalized feed of followed users/gyms, connected gyms, and public posts of any users or gyms.",
        parameters=[
            GymFeedFilterSerializer,
        ],
        responses={
            200: GymPostListSerializer(many=True),
            400: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def get(self, request):
        filter_serializer = GymFeedFilterSerializer(data=request.query_params)
        filter_serializer.is_valid(raise_exception=True)
        params = filter_serializer.validated_data

        gym_id = (
            params.get("gym_id")
            or getattr(request, "gym_id", None)
            or (request.data.get("gym_id") if isinstance(request.data, dict) else None)
        )
        if gym_id:
            gym = resolve_post_gym(request)
            is_member_or_staff = check_user_is_member_or_staff(request, gym)
        else:
            gym = None
            is_member_or_staff = False

        privacy = params.get("privacy")
        search = params.get("search")
        feed_type = params.get("feed_type") or params.get("source")

        qs = list_gym_feed(
            gym=gym,
            is_member_or_staff=is_member_or_staff,
            privacy_filter=privacy,
            search=search,
            requesting_user=request.user,
            feed_type=feed_type,
        )

        context = {"request": request}
        if request.user and request.user.is_authenticated:
            context.update(get_user_social_context(request.user))

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        if page is not None:
            serializer = GymPostListSerializer(page, many=True, context=context)
            return paginator.get_paginated_response(serializer.data)

        serializer = GymPostListSerializer(qs, many=True, context=context)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Community Feed"],
        summary="Create Community Post",
        description="Creates a new community post with optional text and media attachments (pictures or videos). Requires 'posts:manage' scope.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        request=GymPostCreateSerializer,
        responses={
            201: GymPostDetailSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
        },
    )
    def post(self, request):
        gym = resolve_post_gym(request)
        check_post_management_permission(request, gym)

        serializer = GymPostCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Gather any uploaded files (support multipart 'media_files', 'files', or singular 'file')
        media_files = (
            request.FILES.getlist("media_files")
            or request.FILES.getlist("files")
            or request.FILES.getlist("file")
        )

        post = create_post(
            gym=gym,
            author_user=request.user,
            content_text=data.get("content_text"),
            privacy=data.get("privacy"),
            media_files=media_files,
            media_items=data.get("media_items"),
        )

        loaded_post = get_post_detail(gym=gym, post_id=post.id, is_member_or_staff=True)
        return Response(GymPostDetailSerializer(loaded_post, context={"request": request}).data, status=status.HTTP_201_CREATED)


class GymPostDetailView(APIView):
    """
    Retrieve, update, or delete a single gym community post.
    """
    def get_permissions(self):
        if self.request.method in ("PATCH", "DELETE"):
            return [IsAuthenticated()]
        return [AllowAny()]

    @extend_schema(
        tags=["Community Feed"],
        summary="Get Post Detail",
        description="Retrieves a single community post dossier with all attached media.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=True),
        ],
        responses={
            200: GymPostDetailSerializer,
            400: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def get(self, request, post_id: uuid.UUID):
        gym = resolve_post_gym(request)
        is_member_or_staff = check_user_is_member_or_staff(request, gym)

        post = get_post_detail(
            gym=gym,
            post_id=post_id,
            is_member_or_staff=is_member_or_staff,
            requesting_user=request.user,
        )
        context = {"request": request}
        if request.user and request.user.is_authenticated:
            context.update(get_user_social_context(request.user))
        return Response(GymPostDetailSerializer(post, context=context).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Community Feed"],
        summary="Update Community Post",
        description="Updates post text, privacy level, or reorders media attachments. Requires 'posts:manage' scope.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        request=GymPostUpdateSerializer,
        responses={
            200: GymPostDetailSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def patch(self, request, post_id: uuid.UUID):
        gym = resolve_post_gym(request)
        check_post_management_permission(request, gym)

        post = get_post_detail(gym=gym, post_id=post_id, is_member_or_staff=True)
        serializer = GymPostUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        update_post(
            post=post,
            content_text=data.get("content_text"),
            privacy=data.get("privacy"),
            media_order=data.get("media_order"),
        )

        loaded_post = get_post_detail(gym=gym, post_id=post.id, is_member_or_staff=True)
        return Response(GymPostDetailSerializer(loaded_post).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Community Feed"],
        summary="Delete Community Post",
        description="Permanently deletes a gym community post and its associated media assets. Requires 'posts:manage' scope.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        responses={
            200: ErrorDetailSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def delete(self, request, post_id: uuid.UUID):
        gym = resolve_post_gym(request)
        check_post_management_permission(request, gym)

        post = get_post_detail(gym=gym, post_id=post_id, is_member_or_staff=True)
        delete_post(post)
        return Response({"message": "Post deleted successfully."}, status=status.HTTP_200_OK)
