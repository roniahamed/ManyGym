import uuid
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from drf_spectacular.utils import extend_schema, OpenApiParameter

from apps.posts.selectors import (
    get_post_detail,
    get_post_detail_by_id,
    get_user_social_context,
    list_gym_feed,
    list_my_posts,
    list_post_reposts,
)
from apps.posts.services import (
    create_post,
    delete_post,
    normalize_repost_target,
    repost_post,
    update_post,
)
from apps.posts.rest_api.v1.serializers import (
    GymFeedFilterSerializer,
    GymPostCreateSerializer,
    GymPostDetailSerializer,
    GymPostListSerializer,
    GymPostUpdateSerializer,
    RepostCreateSerializer,
)
from apps.posts.rest_api.v1.views.base_views import (
    check_post_management_permission,
    check_post_owner_manage_permission,
    check_user_is_member_or_staff,
    resolve_post_gym,
    resolve_post_owner_context,
)
from apps.stories.rest_api.v1.serializers import StorySerializer
from apps.stories.selectors import get_story_detail
from apps.stories.services import extract_single_media_file
from common.enums import PostOwnerTypeEnum, RepostTargetEnum
from common.exceptions import DomainValidationError
from common.pagination import StandardResultsSetPagination
from common.serializers import ErrorDetailSerializer, MessageResponseSerializer


def _build_serializer_context(request) -> dict:
    context = {"request": request}
    if request.user and getattr(request.user, "is_authenticated", False):
        social_ctx = getattr(request, "_user_social_context", None)
        if social_ctx is None:
            social_ctx = get_user_social_context(request.user)
            request._user_social_context = social_ctx
        context.update(social_ctx)
    return context


class GymFeedView(APIView):
    """
    List community/profile feed posts and reposts, or publish a new post/repost
    as either a Public User or a Gym (automatically resolved from Bearer token).
    """
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    pagination_class = StandardResultsSetPagination

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated()]
        return [AllowAny()]

    @extend_schema(
        tags=["Community Feed"],
        summary="List Community & Profile Feed",
        description=(
            "Retrieves community posts and reposts. Pass `user_id` for a public user's profile feed, "
            "`gym_id` for a gym's profile feed, or omit both for the personalized global feed. "
            "Supports filtering by `owner_type`, `feed_type`, `privacy`, `is_repost`, and `search`."
        ),
        parameters=[GymFeedFilterSerializer],
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

        gym_id = params.get("gym_id")
        if gym_id:
            gym = resolve_post_gym(request)
            is_member_or_staff = check_user_is_member_or_staff(request, gym)
        else:
            gym = None
            is_member_or_staff = False

        privacy = params.get("privacy")
        search = params.get("search")
        feed_type = params.get("feed_type") or params.get("source")
        owner_type = params.get("owner_type") or None
        user_id = params.get("user_id")
        is_repost = params.get("is_repost")

        context = _build_serializer_context(request) if gym is None else {"request": request}
        social_ctx = getattr(request, "_user_social_context", None) if gym is None else None

        qs = list_gym_feed(
            gym=gym,
            is_member_or_staff=is_member_or_staff,
            privacy_filter=privacy,
            search=search,
            requesting_user=request.user,
            feed_type=feed_type,
            owner_type=owner_type,
            user_id=user_id,
            is_repost=is_repost,
            social_ctx=social_ctx,
        )

        if gym is not None:
            context = _build_serializer_context(request)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        if page is not None:
            serializer = GymPostListSerializer(page, many=True, context=context)
            return paginator.get_paginated_response(serializer.data)

        serializer = GymPostListSerializer(qs, many=True, context=context)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Community Feed"],
        summary="Create Post or Repost",
        description=(
            "Creates a new post (or repost when `source_post_id` is provided) as either a Public User "
            "or a Gym based on the Bearer token context (or explicit `gym_id`). "
            "Public users support privacy: `public`, `followers`, `private`. "
            "Gyms support privacy: `public`, `followers`, `members_only`, `private` (requires `posts:manage`)."
        ),
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        request=GymPostCreateSerializer,
        responses={
            201: GymPostDetailSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def post(self, request):
        owner_type, gym = resolve_post_owner_context(
            request,
            allow_explicit_gym_id=True,
            require_active_gym=True,
        )
        if owner_type == PostOwnerTypeEnum.GYM:
            check_post_management_permission(request, gym)

        serializer = GymPostCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        source_post_id = data.get("source_post_id")
        target = normalize_repost_target(data.get("target"))

        if source_post_id and target == RepostTargetEnum.STORY:
            media_file = extract_single_media_file(request.FILES)
            result = repost_post(
                actor_user=request.user,
                source_post_id=source_post_id,
                target=RepostTargetEnum.STORY,
                owner_type=owner_type,
                gym=gym,
                privacy=data.get("privacy"),
                content_text=data.get("content_text"),
                caption=data.get("caption"),
                background_color=data.get("background_color"),
                lifetime_hours=data.get("lifetime_hours"),
                media_file=media_file,
                media_url=data.get("media_url"),
                thumbnail_url=data.get("thumbnail_url"),
                file_size_bytes=data.get("file_size_bytes", 0),
                duration_seconds=data.get("duration_seconds"),
            )
            loaded_story = get_story_detail(result["story"].id, requesting_user=request.user, for_management=True)
            payload = StorySerializer(loaded_story, context={"request": request}).data
            payload["target"] = RepostTargetEnum.STORY
            return Response(payload, status=status.HTTP_201_CREATED)

        media_files = (
            request.FILES.getlist("media_files")
            or request.FILES.getlist("files")
            or request.FILES.getlist("file")
        )

        post = create_post(
            gym=gym,
            author_user=request.user,
            owner_type=owner_type,
            content_text=data.get("content_text"),
            privacy=data.get("privacy"),
            media_files=media_files,
            media_items=data.get("media_items"),
            source_post_id=source_post_id,
        )

        loaded_post = get_post_detail_by_id(post_id=post.id, requesting_user=request.user, for_management=True)
        context = _build_serializer_context(request)
        return Response(GymPostDetailSerializer(loaded_post, context=context).data, status=status.HTTP_201_CREATED)


class MyPostsFeedView(APIView):
    """
    Lists the authenticated user's own profile feed (or active gym's profile feed in gym context),
    including private posts and reposts.
    """
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    @extend_schema(
        tags=["Community Feed"],
        summary="List My Profile Feed (Personal or Gym)",
        description="Lists posts and reposts belonging to the authenticated Personal User or active Gym token context.",
        parameters=[
            OpenApiParameter(name="privacy", type=str, required=False),
            OpenApiParameter(name="is_repost", type=bool, required=False),
            OpenApiParameter(name="search", type=str, required=False),
        ],
        responses={
            200: GymPostListSerializer(many=True),
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
        },
    )
    def get(self, request):
        filter_serializer = GymFeedFilterSerializer(data=request.query_params)
        filter_serializer.is_valid(raise_exception=True)
        params = filter_serializer.validated_data

        owner_type, gym = resolve_post_owner_context(
            request,
            allow_explicit_gym_id=False,
            require_active_gym=False,
        )

        qs = list_my_posts(
            user=request.user,
            owner_type=owner_type,
            gym=gym,
            privacy_filter=params.get("privacy"),
            is_repost=params.get("is_repost"),
            search=params.get("search"),
        )

        context = _build_serializer_context(request)
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        if page is not None:
            serializer = GymPostListSerializer(page, many=True, context=context)
            return paginator.get_paginated_response(serializer.data)

        serializer = GymPostListSerializer(qs, many=True, context=context)
        return Response(serializer.data, status=status.HTTP_200_OK)


class PostRepostView(APIView):
    """
    Reposts another user's/gym's post or the actor's own previous post onto either:
    - 'profile': actor's profile feed (Personal User or Gym)
    - 'story': actor's Story
    Owner identity ('user' vs 'gym') is automatically resolved from the Bearer token.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @extend_schema(
        tags=["Community Feed"],
        summary="Repost Post (Share on Profile or Share on Story)",
        description=(
            "Reposts an existing post (another user's/gym's post or your own previous post) to "
            "`target='profile'` (showing on profile feed) or `target='story'` (sharing on Story). "
            "Owner type (`user` vs `gym`) is automatically detected from the Bearer token. "
            "Public user privacy choices: `public`, `followers`, `private`. "
            "Gym privacy choices: `public`, `followers`, `members_only`, `private`."
        ),
        request=RepostCreateSerializer,
        responses={
            201: GymPostDetailSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def post(self, request, post_id: uuid.UUID | None = None):
        media_file = extract_single_media_file(request.FILES)

        serializer = RepostCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        body_source_id = data.get("source_post_id")
        if post_id is not None and body_source_id is not None and str(post_id) != str(body_source_id):
            raise DomainValidationError("source_post_id in request body does not match URL post_id.")

        source_post_id = post_id or body_source_id
        if not source_post_id:
            raise DomainValidationError("source_post_id is required.")

        owner_type, gym = resolve_post_owner_context(
            request,
            allow_explicit_gym_id=False,
            require_active_gym=True,
        )
        if owner_type == PostOwnerTypeEnum.GYM:
            check_post_management_permission(request, gym)

        result = repost_post(
            actor_user=request.user,
            source_post_id=source_post_id,
            target=data.get("target") or RepostTargetEnum.PROFILE,
            owner_type=owner_type,
            gym=gym,
            privacy=data.get("privacy"),
            content_text=data.get("content_text"),
            caption=data.get("caption"),
            background_color=data.get("background_color"),
            lifetime_hours=data.get("lifetime_hours"),
            media_file=media_file,
            media_url=data.get("media_url"),
            thumbnail_url=data.get("thumbnail_url"),
            file_size_bytes=data.get("file_size_bytes", 0),
            duration_seconds=data.get("duration_seconds"),
        )

        if result["target"] == RepostTargetEnum.STORY:
            loaded_story = get_story_detail(result["story"].id, requesting_user=request.user, for_management=True)
            payload = StorySerializer(loaded_story, context={"request": request}).data
            payload["target"] = RepostTargetEnum.STORY
            return Response(payload, status=status.HTTP_201_CREATED)

        loaded_post = get_post_detail_by_id(result["post"].id, requesting_user=request.user, for_management=True)
        context = _build_serializer_context(request)
        payload = GymPostDetailSerializer(loaded_post, context=context).data
        payload["target"] = RepostTargetEnum.PROFILE
        return Response(payload, status=status.HTTP_201_CREATED)


class PostRepostsListView(APIView):
    """
    Lists visible profile reposts of a specific post.
    """
    permission_classes = [AllowAny]
    pagination_class = StandardResultsSetPagination

    @extend_schema(
        tags=["Community Feed"],
        summary="List Reposts of a Post",
        description="Retrieves visible profile reposts referencing the specified post ID.",
        responses={
            200: GymPostListSerializer(many=True),
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def get(self, request, post_id: uuid.UUID):
        qs = list_post_reposts(post_id=post_id, requesting_user=request.user)
        context = _build_serializer_context(request)
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        if page is not None:
            serializer = GymPostListSerializer(page, many=True, context=context)
            return paginator.get_paginated_response(serializer.data)

        serializer = GymPostListSerializer(qs, many=True, context=context)
        return Response(serializer.data, status=status.HTTP_200_OK)


class GymPostDetailView(APIView):
    """
    Retrieve, update, or delete a single community post or repost (Personal User or Gym).
    """
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get_permissions(self):
        if self.request.method in ("PATCH", "DELETE"):
            return [IsAuthenticated()]
        return [AllowAny()]

    @extend_schema(
        tags=["Community Feed"],
        summary="Get Post Detail",
        description="Retrieves a single post or repost dossier with attached media and embedded source_post.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        responses={
            200: GymPostDetailSerializer,
            400: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def get(self, request, post_id: uuid.UUID):
        explicit_gym_id = request.query_params.get("gym_id")
        if explicit_gym_id:
            gym = resolve_post_gym(request)
            is_member_or_staff = check_user_is_member_or_staff(request, gym)
            post = get_post_detail(
                gym=gym,
                post_id=post_id,
                is_member_or_staff=is_member_or_staff,
                requesting_user=request.user,
            )
        else:
            post = get_post_detail_by_id(
                post_id=post_id,
                requesting_user=request.user,
                for_management=False,
            )

        context = _build_serializer_context(request)
        return Response(GymPostDetailSerializer(post, context=context).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Community Feed"],
        summary="Update Post or Repost",
        description="Updates post text, privacy level, or reorders media attachments.",
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
        explicit_gym_id = (
            request.query_params.get("gym_id")
            or (request.data.get("gym_id") if isinstance(request.data, dict) else None)
        )
        if explicit_gym_id:
            gym = resolve_post_gym(request)
            check_post_management_permission(request, gym)
            post = get_post_detail(gym=gym, post_id=post_id, is_member_or_staff=True, requesting_user=request.user)
        else:
            post = get_post_detail_by_id(post_id=post_id, requesting_user=request.user, for_management=True)
            check_post_owner_manage_permission(request, post)

        serializer = GymPostUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        update_post(
            post=post,
            content_text=data.get("content_text"),
            privacy=data.get("privacy"),
            media_order=data.get("media_order"),
        )

        loaded_post = get_post_detail_by_id(post_id=post.id, requesting_user=request.user, for_management=True)
        context = _build_serializer_context(request)
        return Response(GymPostDetailSerializer(loaded_post, context=context).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Community Feed"],
        summary="Delete Post or Repost",
        description="Permanently deletes a post or repost and cleans up its associated media assets.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        responses={
            200: MessageResponseSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def delete(self, request, post_id: uuid.UUID):
        explicit_gym_id = (
            request.query_params.get("gym_id")
            or (request.data.get("gym_id") if isinstance(request.data, dict) else None)
        )
        if explicit_gym_id:
            gym = resolve_post_gym(request)
            check_post_management_permission(request, gym)
            post = get_post_detail(gym=gym, post_id=post_id, is_member_or_staff=True, requesting_user=request.user)
        else:
            post = get_post_detail_by_id(post_id=post_id, requesting_user=request.user, for_management=True)
            check_post_owner_manage_permission(request, post)

        delete_post(post)
        return Response({"message": "Post deleted successfully."}, status=status.HTTP_200_OK)
