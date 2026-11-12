import uuid
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import OpenApiParameter, extend_schema

from apps.stories.permissions import resolve_story_owner_context
from apps.stories.rest_api.v1.serializers import (
    StoryCreateSerializer,
    StoryFilterSerializer,
    StorySerializer,
    StoryTrayBucketSerializer,
    StoryUpdateSerializer,
    StoryViewSerializer,
)
from apps.stories.selectors import (
    get_story_detail,
    list_active_stories,
    list_my_stories,
    list_story_tray,
    list_story_viewers,
)
from apps.stories.services import (
    create_story,
    delete_story,
    extract_single_media_file,
    record_story_view,
    update_story,
)
from common.enums import StoryOwnerTypeEnum
from common.pagination import StandardResultsSetPagination
from common.serializers import ErrorDetailSerializer, MessageResponseSerializer


class StoryListCreateView(APIView):
    """
    List active visible stories or upload a new single-media story (as Public User or Gym).
    """
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    pagination_class = StandardResultsSetPagination

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated()]
        return [AllowAny()]

    @extend_schema(
        tags=["Stories"],
        summary="List Active Stories",
        description=(
            "Retrieves non-expired stories visible to the requesting user. "
            "Respects owner-type privacy rules (Public users: public/followers/private; "
            "Gyms: public/followers/members_only/private), blocklists, and age restrictions."
        ),
        parameters=[StoryFilterSerializer],
        responses={
            200: StorySerializer(many=True),
            400: ErrorDetailSerializer,
        },
    )
    def get(self, request):
        filter_serializer = StoryFilterSerializer(data=request.query_params)
        filter_serializer.is_valid(raise_exception=True)
        params = filter_serializer.validated_data

        qs = list_active_stories(
            requesting_user=request.user,
            owner_type=params.get("owner_type") or None,
            user_id=params.get("user_id"),
            gym_id=params.get("gym_id"),
            feed_type=params.get("feed_type"),
            privacy=params.get("privacy") or None,
        )

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        if page is not None:
            serializer = StorySerializer(page, many=True, context={"request": request})
            return paginator.get_paginated_response(serializer.data)

        serializer = StorySerializer(qs, many=True, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Stories"],
        summary="Upload Story",
        description=(
            "Uploads a single-media story (1 image or 1 video) as either a Public User or a Gym. "
            "Supports lifetime selection (6, 12, 18 [default], 24, 48 hours), optional source_post_id, "
            "and owner-specific privacy levels."
        ),
        request=StoryCreateSerializer,
        responses={
            201: StorySerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def post(self, request):
        # Strictly reject multi-file uploads before serializer parsing
        media_file = extract_single_media_file(request.FILES)

        serializer = StoryCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        owner_type, gym = resolve_story_owner_context(
            request,
            require_active_gym=True,
        )

        story = create_story(
            user=request.user,
            owner_type=owner_type,
            gym=gym,
            source_post_id=data.get("source_post_id"),
            media_file=media_file,
            media_url=data.get("media_url"),
            thumbnail_url=data.get("thumbnail_url"),
            file_size_bytes=data.get("file_size_bytes", 0),
            duration_seconds=data.get("duration_seconds"),
            lifetime_hours=data.get("lifetime_hours"),
            privacy=data.get("privacy"),
            caption=data.get("caption"),
            background_color=data.get("background_color"),
        )

        loaded = get_story_detail(story.id, requesting_user=request.user, for_management=True)
        return Response(
            StorySerializer(loaded, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class StoryTrayView(APIView):
    """
    Returns active stories grouped by owner (Public User or Gym) for story ring / tray UIs.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Stories"],
        summary="Get Story Tray (Grouped by Owner)",
        description="Returns active stories grouped by Public User or Gym, prioritizing owners with unviewed stories.",
        parameters=[
            OpenApiParameter(name="owner_type", type=str, required=False, enum=StoryOwnerTypeEnum.values),
            OpenApiParameter(name="feed_type", type=str, required=False),
        ],
        responses={
            200: StoryTrayBucketSerializer(many=True),
            400: ErrorDetailSerializer,
        },
    )
    def get(self, request):
        owner_type = request.query_params.get("owner_type") or None
        feed_type = request.query_params.get("feed_type") or None
        buckets = list_story_tray(
            requesting_user=request.user,
            owner_type=owner_type,
            feed_type=feed_type,
        )
        serializer = StoryTrayBucketSerializer(buckets, many=True, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class MyStoriesView(APIView):
    """
    Lists the authenticated user's own stories (or active gym's stories in gym context),
    including private and optionally expired/archived stories.
    """
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    @extend_schema(
        tags=["Stories"],
        summary="List My Stories (Personal or Gym)",
        description="Lists stories owned by the current personal user or active gym context from the Bearer token (including private and optional expired archive).",
        parameters=[
            OpenApiParameter(name="include_expired", type=bool, required=False),
            OpenApiParameter(name="include_archived", type=bool, required=False),
        ],
        responses={
            200: StorySerializer(many=True),
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
        },
    )
    def get(self, request):
        owner_type, gym = resolve_story_owner_context(
            request,
            require_active_gym=False,
        )
        include_expired = str(request.query_params.get("include_expired", "")).lower() in ("1", "true", "yes")
        include_archived_raw = request.query_params.get("include_archived")
        include_archived = True if include_archived_raw is None else str(include_archived_raw).lower() in ("1", "true", "yes")

        qs = list_my_stories(
            user=request.user,
            owner_type=owner_type,
            gym=gym,
            include_expired=include_expired,
            include_archived=include_archived,
        )

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        if page is not None:
            serializer = StorySerializer(page, many=True, context={"request": request})
            return paginator.get_paginated_response(serializer.data)

        serializer = StorySerializer(qs, many=True, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class StoryDetailView(APIView):
    """
    Retrieve, update, or delete a single story.
    """
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get_permissions(self):
        if self.request.method in ("PATCH", "DELETE"):
            return [IsAuthenticated()]
        return [AllowAny()]

    @extend_schema(
        tags=["Stories"],
        summary="Get Story Detail",
        description="Retrieves a single story. Pass ?mark_viewed=true (when authenticated) to record a view.",
        parameters=[
            OpenApiParameter(name="mark_viewed", type=bool, required=False),
        ],
        responses={
            200: StorySerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def get(self, request, story_id: uuid.UUID):
        story = get_story_detail(story_id=story_id, requesting_user=request.user, for_management=False)
        mark_viewed = str(request.query_params.get("mark_viewed", "")).lower() in ("1", "true", "yes")
        if mark_viewed and request.user and request.user.is_authenticated:
            _, created = record_story_view(story, request.user)
            if created:
                story.has_viewed = True

        return Response(StorySerializer(story, context={"request": request}).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Stories"],
        summary="Update Story",
        description="Updates story caption, background_color, privacy, lifetime, or archive status. Owner/Gym manager only.",
        request=StoryUpdateSerializer,
        responses={
            200: StorySerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def patch(self, request, story_id: uuid.UUID):
        story = get_story_detail(story_id=story_id, requesting_user=request.user, for_management=True)
        serializer = StoryUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        updated = update_story(
            story=story,
            actor_user=request.user,
            caption=data.get("caption"),
            privacy=data.get("privacy"),
            lifetime_hours=data.get("lifetime_hours"),
            background_color=data.get("background_color"),
            is_archived=data.get("is_archived"),
            update_caption="caption" in data,
            update_background_color="background_color" in data,
        )
        return Response(StorySerializer(updated, context={"request": request}).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Stories"],
        summary="Delete Story",
        description="Permanently deletes a story and cleans up story-owned media files. Owner/Gym manager only.",
        responses={
            200: MessageResponseSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def delete(self, request, story_id: uuid.UUID):
        story = get_story_detail(story_id=story_id, requesting_user=request.user, for_management=True)
        delete_story(story, actor_user=request.user)
        return Response({"message": "Story deleted successfully."}, status=status.HTTP_200_OK)


class StoryRecordViewView(APIView):
    """
    Records an idempotent view on an active story by the authenticated user.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Stories"],
        summary="Record Story View",
        description="Marks the story as viewed by the authenticated user and updates unique views_count.",
        responses={
            200: MessageResponseSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def post(self, request, story_id: uuid.UUID):
        story = get_story_detail(story_id=story_id, requesting_user=request.user, for_management=False)
        _, created = record_story_view(story, request.user)
        return Response(
            {
                "message": "Story view recorded." if created else "Story already viewed.",
                "views_count": story.views_count,
                "newly_viewed": created,
            },
            status=status.HTTP_200_OK,
        )


class StoryViewersListView(APIView):
    """
    Lists unique viewers of a story (only accessible to the story owner or gym manager).
    """
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    @extend_schema(
        tags=["Stories"],
        summary="List Story Viewers",
        description="Retrieves users who viewed this story. Restricted to the story owner or authorized gym staff.",
        responses={
            200: StoryViewSerializer(many=True),
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def get(self, request, story_id: uuid.UUID):
        qs = list_story_viewers(story_id=story_id, requesting_user=request.user)
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        if page is not None:
            serializer = StoryViewSerializer(page, many=True, context={"request": request})
            return paginator.get_paginated_response(serializer.data)

        serializer = StoryViewSerializer(qs, many=True, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

