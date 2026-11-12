import uuid
from typing import Any, Dict, Optional
from django.core.files.uploadedfile import UploadedFile
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.posts.comment_selectors import (
    attach_nested_replies,
    get_comment_detail,
    list_comment_replies,
    list_post_comments,
)
from apps.posts.rest_api.v1.comment_serializers import (
    PostCommentCreateSerializer,
    PostCommentFilterSerializer,
    PostCommentSerializer,
    PostCommentUpdateSerializer,
)
from apps.posts.rest_api.v1.views.base_views import (
    check_post_management_permission,
    resolve_post_owner_context,
)
from apps.posts.selectors import get_user_social_context
from apps.posts.services.comment_services import (
    UNSET,
    check_comment_delete_permission,
    check_comment_edit_permission,
    create_comment,
    delete_comment,
    update_comment,
)
from common.enums import PostOwnerTypeEnum
from common.exceptions import DomainValidationError
from common.pagination import StandardResultsSetPagination
from common.serializers import ErrorDetailSerializer, MessageResponseSerializer


def _get_social_context_cached(request) -> dict:
    if not request.user or not getattr(request.user, "is_authenticated", False):
        return get_user_social_context(None)
    cached = getattr(request, "_user_social_context", None)
    if cached is None:
        cached = get_user_social_context(request.user)
        request._user_social_context = cached
    return cached


def _is_uploaded_file(val: Any) -> bool:
    return isinstance(val, UploadedFile) or (hasattr(val, "read") and hasattr(val, "name"))


def _extract_comment_media_inputs(
    request,
    validated_data: Dict[str, Any],
    partial: bool = False,
) -> Dict[str, Any]:
    """
    Normalizes photo, video, and gif inputs from either multipart file uploads
    or JSON URL strings without treating a single upload as both file and URL.
    """
    result: Dict[str, Any] = {
        "photo_file": None,
        "video_file": None,
        "gif_file": None,
        "photo_url": UNSET,
        "video_url": UNSET,
        "gif_url": UNSET,
    }

    field_aliases = (
        ("comment_photo", ("photo", "image"), "photo_file", "photo_url"),
        ("comment_video", ("video",), "video_file", "video_url"),
        ("comment_gif", ("gif",), "gif_file", "gif_url"),
    )

    for primary_key, aliases, file_out_key, url_out_key in field_aliases:
        alias_file = None
        for alias in aliases:
            if alias in request.FILES:
                alias_file = request.FILES[alias]
                break

        if primary_key in validated_data:
            raw_val = validated_data[primary_key]
            if _is_uploaded_file(raw_val):
                result[file_out_key] = raw_val
            else:
                result[url_out_key] = raw_val
                if alias_file is not None:
                    result[file_out_key] = alias_file
        elif alias_file is not None:
            result[file_out_key] = alias_file
        elif not partial:
            result[url_out_key] = UNSET

    return result


class PostCommentsView(APIView):
    """
    List paginated top-level comments (with optional nested reply previews) on a post,
    or create a new comment / reply.
    """
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    pagination_class = StandardResultsSetPagination

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated()]
        return [AllowAny()]

    @extend_schema(
        tags=["Post Comments"],
        summary="List Paginated Post Comments (with Nested Replies)",
        description=(
            "Retrieves paginated top-level comments for a post with optional nested reply previews. "
            "Supports `sort` (`newest`, `oldest`, `most_replied`), `media_type` (`photo`, `video`, `gif`, `text`), "
            "`include_replies`, `replies_limit` (0-10), `reply_depth` (0-5), `page`, and `page_size`."
        ),
        parameters=[PostCommentFilterSerializer],
        responses={
            200: PostCommentSerializer(many=True),
            400: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def get(self, request, post_id: Optional[uuid.UUID] = None):
        filter_serializer = PostCommentFilterSerializer(data=request.query_params)
        filter_serializer.is_valid(raise_exception=True)
        params = filter_serializer.validated_data

        social_ctx = _get_social_context_cached(request)
        target_post_id = post_id or params.get("source_post_id")
        target_comment_id = params.get("source_comment_id")

        if post_id is None and target_comment_id is not None:
            qs = list_comment_replies(
                comment_id=target_comment_id,
                post_id=target_post_id,
                requesting_user=request.user,
                sort=params.get("sort") or "oldest",
                media_type=params.get("media_type"),
                social_ctx=social_ctx,
            )
        elif target_post_id is not None:
            qs = list_post_comments(
                post_id=target_post_id,
                requesting_user=request.user,
                sort=params.get("sort") or "newest",
                media_type=params.get("media_type"),
                social_ctx=social_ctx,
            )
        else:
            raise DomainValidationError(
                "Either post_id in URL or source_post_id/source_comment_id query parameter is required."
            )

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        items = list(page) if page is not None else list(qs)

        attach_nested_replies(
            comments=items,
            requesting_user=request.user,
            social_ctx=social_ctx,
            include_replies=params.get("include_replies", True),
            replies_limit=params.get("replies_limit", 2),
            reply_depth=params.get("reply_depth", 2),
            reply_sort=params.get("reply_sort") or "oldest",
        )

        serializer = PostCommentSerializer(items, many=True, context={"request": request})
        if page is not None:
            return paginator.get_paginated_response(serializer.data)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Post Comments"],
        summary="Create Comment or Reply on a Post",
        description=(
            "Creates a top-level comment on a post, or a nested reply when `source_comment_id` is supplied. "
            "Supports optional `comment_text` and up to one media attachment (`comment_photo`, `comment_video`, or `comment_gif`)."
        ),
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        request=PostCommentCreateSerializer,
        responses={
            201: PostCommentSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def post(self, request, post_id: Optional[uuid.UUID] = None):
        owner_type, gym = resolve_post_owner_context(
            request,
            allow_explicit_gym_id=True,
            require_active_gym=True,
        )
        if owner_type == PostOwnerTypeEnum.GYM:
            check_post_management_permission(request, gym)

        serializer = PostCommentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        body_post_id = data.get("source_post_id")
        if post_id is not None and body_post_id is not None and str(post_id) != str(body_post_id):
            raise DomainValidationError("source_post_id in request body does not match URL post_id.")

        resolved_post_id = post_id or body_post_id
        media_inputs = _extract_comment_media_inputs(request, data, partial=False)
        duration_val = data["duration_seconds"] if "duration_seconds" in data else UNSET

        comment = create_comment(
            actor_user=request.user,
            source_post_id=resolved_post_id,
            source_comment_id=data.get("source_comment_id"),
            owner_type=owner_type,
            gym=gym,
            comment_text=data.get("comment_text"),
            photo_file=media_inputs["photo_file"],
            video_file=media_inputs["video_file"],
            gif_file=media_inputs["gif_file"],
            photo_url=media_inputs["photo_url"],
            video_url=media_inputs["video_url"],
            gif_url=media_inputs["gif_url"],
            duration_seconds=duration_val,
        )

        loaded = get_comment_detail(
            comment_id=comment.id,
            requesting_user=request.user,
            for_management=True,
        )
        loaded._prefetched_replies = []
        loaded._has_more_replies = False
        return Response(
            PostCommentSerializer(loaded, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class CommentRepliesView(APIView):
    """
    List paginated nested replies for a comment at any depth, or create a reply directly.
    """
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    pagination_class = StandardResultsSetPagination

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated()]
        return [AllowAny()]

    @extend_schema(
        tags=["Post Comments"],
        summary="List Paginated Replies to a Comment",
        description=(
            "Retrieves paginated direct replies for a specific comment (at any nesting level), "
            "with optional nested child previews."
        ),
        parameters=[PostCommentFilterSerializer],
        responses={
            200: PostCommentSerializer(many=True),
            400: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def get(self, request, comment_id: uuid.UUID, post_id: Optional[uuid.UUID] = None):
        filter_serializer = PostCommentFilterSerializer(data=request.query_params)
        filter_serializer.is_valid(raise_exception=True)
        params = filter_serializer.validated_data

        social_ctx = _get_social_context_cached(request)
        qs = list_comment_replies(
            comment_id=comment_id,
            post_id=post_id,
            requesting_user=request.user,
            sort=params.get("sort") or "oldest",
            media_type=params.get("media_type"),
            social_ctx=social_ctx,
        )

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        items = list(page) if page is not None else list(qs)

        attach_nested_replies(
            comments=items,
            requesting_user=request.user,
            social_ctx=social_ctx,
            include_replies=params.get("include_replies", True),
            replies_limit=params.get("replies_limit", 2),
            reply_depth=params.get("reply_depth", 2),
            reply_sort=params.get("reply_sort") or "oldest",
        )

        serializer = PostCommentSerializer(items, many=True, context={"request": request})
        if page is not None:
            return paginator.get_paginated_response(serializer.data)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Post Comments"],
        summary="Reply to a Comment",
        description="Creates a nested reply targeting the specified comment.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        request=PostCommentCreateSerializer,
        responses={
            201: PostCommentSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def post(self, request, comment_id: uuid.UUID, post_id: Optional[uuid.UUID] = None):
        owner_type, gym = resolve_post_owner_context(
            request,
            allow_explicit_gym_id=True,
            require_active_gym=True,
        )
        if owner_type == PostOwnerTypeEnum.GYM:
            check_post_management_permission(request, gym)

        serializer = PostCommentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        body_post_id = data.get("source_post_id")
        if post_id is not None and body_post_id is not None and str(post_id) != str(body_post_id):
            raise DomainValidationError("source_post_id in request body does not match URL post_id.")

        body_comment_id = data.get("source_comment_id")
        if body_comment_id is not None and str(comment_id) != str(body_comment_id):
            raise DomainValidationError("source_comment_id in request body does not match URL comment_id.")

        media_inputs = _extract_comment_media_inputs(request, data, partial=False)
        duration_val = data["duration_seconds"] if "duration_seconds" in data else UNSET

        comment = create_comment(
            actor_user=request.user,
            source_post_id=post_id or body_post_id,
            source_comment_id=comment_id,
            owner_type=owner_type,
            gym=gym,
            comment_text=data.get("comment_text"),
            photo_file=media_inputs["photo_file"],
            video_file=media_inputs["video_file"],
            gif_file=media_inputs["gif_file"],
            photo_url=media_inputs["photo_url"],
            video_url=media_inputs["video_url"],
            gif_url=media_inputs["gif_url"],
            duration_seconds=duration_val,
        )

        loaded = get_comment_detail(
            comment_id=comment.id,
            requesting_user=request.user,
            for_management=True,
        )
        loaded._prefetched_replies = []
        loaded._has_more_replies = False
        return Response(
            PostCommentSerializer(loaded, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class CommentDetailView(APIView):
    """
    Retrieve, edit, or delete a single comment or nested reply.
    """
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_permissions(self):
        if self.request.method in ("PATCH", "DELETE"):
            return [IsAuthenticated()]
        return [AllowAny()]

    @extend_schema(
        tags=["Post Comments"],
        summary="Get Comment Detail (with Optional Nested Thread)",
        parameters=[
            OpenApiParameter(name="include_replies", type=bool, required=False),
            OpenApiParameter(name="replies_limit", type=int, required=False),
            OpenApiParameter(name="reply_depth", type=int, required=False),
            OpenApiParameter(name="reply_sort", type=str, required=False),
        ],
        responses={
            200: PostCommentSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def get(self, request, comment_id: uuid.UUID, post_id: Optional[uuid.UUID] = None):
        filter_serializer = PostCommentFilterSerializer(data=request.query_params)
        filter_serializer.is_valid(raise_exception=True)
        params = filter_serializer.validated_data

        social_ctx = _get_social_context_cached(request)
        comment = get_comment_detail(
            comment_id=comment_id,
            post_id=post_id,
            requesting_user=request.user,
            for_management=False,
            social_ctx=social_ctx,
        )

        attach_nested_replies(
            comments=[comment],
            requesting_user=request.user,
            social_ctx=social_ctx,
            include_replies=params.get("include_replies", True),
            replies_limit=params.get("replies_limit", 2),
            reply_depth=params.get("reply_depth", 2),
            reply_sort=params.get("reply_sort") or "oldest",
        )
        return Response(
            PostCommentSerializer(comment, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        tags=["Post Comments"],
        summary="Update a Comment or Reply",
        request=PostCommentUpdateSerializer,
        responses={
            200: PostCommentSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def patch(self, request, comment_id: uuid.UUID, post_id: Optional[uuid.UUID] = None):
        comment = get_comment_detail(
            comment_id=comment_id,
            post_id=post_id,
            requesting_user=request.user,
            for_management=True,
        )
        check_comment_edit_permission(request, comment)

        serializer = PostCommentUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        media_inputs = _extract_comment_media_inputs(request, data, partial=True)
        comment_text_val = data["comment_text"] if "comment_text" in data else UNSET
        duration_val = data["duration_seconds"] if "duration_seconds" in data else UNSET

        updated = update_comment(
            comment=comment,
            comment_text=comment_text_val,
            photo_file=media_inputs["photo_file"],
            video_file=media_inputs["video_file"],
            gif_file=media_inputs["gif_file"],
            photo_url=media_inputs["photo_url"],
            video_url=media_inputs["video_url"],
            gif_url=media_inputs["gif_url"],
            remove_media=bool(data.get("remove_media", False)),
            duration_seconds=duration_val,
        )

        loaded = get_comment_detail(
            comment_id=updated.id,
            requesting_user=request.user,
            for_management=True,
        )
        loaded._prefetched_replies = []
        loaded._has_more_replies = loaded.replies_count > 0
        return Response(
            PostCommentSerializer(loaded, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        tags=["Post Comments"],
        summary="Delete a Comment or Reply",
        responses={
            200: MessageResponseSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def delete(self, request, comment_id: uuid.UUID, post_id: Optional[uuid.UUID] = None):
        comment = get_comment_detail(
            comment_id=comment_id,
            post_id=post_id,
            requesting_user=request.user,
            for_management=True,
        )
        check_comment_delete_permission(request, comment)

        deleted_count = delete_comment(comment)
        return Response(
            {
                "message": "Comment deleted successfully.",
                "deleted_count": deleted_count,
            },
            status=status.HTTP_200_OK,
        )

