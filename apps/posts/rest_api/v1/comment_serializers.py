from django.core.files.uploadedfile import UploadedFile
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.posts.models import PostComment
from common.enums import CommentMediaTypeEnum
from common.serializers import (
    AbsoluteMediaURLField,
    StrictCharField,
    StrictUUIDField,
)


def _resolve_url(request, url: str | None) -> str | None:
    if not url or not isinstance(url, str):
        return url
    if url.startswith(("http://", "https://", "data:")):
        return url
    if request is not None and hasattr(request, "build_absolute_uri"):
        return request.build_absolute_uri(url)
    return url


class _FlexibleMediaInputField(serializers.Field):
    """
    Accepts either an uploaded file (multipart/form-data) or a media URL string
    while rejecting booleans, numbers, lists, or dicts.
    """

    def to_internal_value(self, data):
        if data is None:
            return None
        if isinstance(data, UploadedFile) or (hasattr(data, "read") and hasattr(data, "name")):
            return data
        if isinstance(data, str):
            if len(data) > 1000:
                raise serializers.ValidationError("Media URL cannot exceed 1000 characters.")
            return data
        raise serializers.ValidationError("Must be a valid media URL string or uploaded file.")

    def to_representation(self, value):
        return value


class PostCommentFilterSerializer(serializers.Serializer):
    """Validates query parameters for paginated comment and nested reply listing."""
    source_post_id = serializers.UUIDField(required=False, allow_null=True)
    source_comment_id = serializers.UUIDField(required=False, allow_null=True)
    sort = serializers.ChoiceField(
        choices=[("newest", "Newest"), ("oldest", "Oldest"), ("most_replied", "Most Replied")],
        required=False,
        allow_null=True,
        allow_blank=True,
    )
    reply_sort = serializers.ChoiceField(
        choices=[("oldest", "Oldest"), ("newest", "Newest"), ("most_replied", "Most Replied")],
        required=False,
        default="oldest",
    )
    media_type = serializers.ChoiceField(
        choices=[
            (CommentMediaTypeEnum.PHOTO, "Photo"),
            (CommentMediaTypeEnum.VIDEO, "Video"),
            (CommentMediaTypeEnum.GIF, "GIF"),
            ("text", "Text Only"),
        ],
        required=False,
        allow_null=True,
        allow_blank=True,
    )
    include_replies = serializers.BooleanField(required=False, default=True)
    replies_limit = serializers.IntegerField(required=False, min_value=0, max_value=10, default=2)
    reply_depth = serializers.IntegerField(required=False, min_value=0, max_value=5, default=2)
    page = serializers.IntegerField(required=False, min_value=1, default=1)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=100, default=20)


class PostCommentCreateSerializer(serializers.Serializer):
    """Validates input payload for creating a post comment or nested reply."""
    source_post_id = StrictUUIDField(
        required=False,
        allow_null=True,
        help_text="Target post UUID (optional if provided in URL path or inferred from source_comment_id).",
    )
    source_comment_id = StrictUUIDField(
        required=False,
        allow_null=True,
        help_text="Optional parent comment UUID when replying to an existing comment.",
    )
    comment_text = StrictCharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=5000,
        help_text="Optional text content of the comment.",
    )
    comment_photo = _FlexibleMediaInputField(
        required=False,
        allow_null=True,
        help_text="Optional photo file upload (JPG/JPEG/PNG/WEBP, <=10MB) or photo URL.",
    )
    comment_video = _FlexibleMediaInputField(
        required=False,
        allow_null=True,
        help_text="Optional video file upload (MP4/MOV, <=200MB) or video URL.",
    )
    comment_gif = _FlexibleMediaInputField(
        required=False,
        allow_null=True,
        help_text="Optional GIF file upload (.gif, <=10MB) or GIF URL.",
    )
    duration_seconds = serializers.FloatField(required=False, allow_null=True, min_value=0.0)


class PostCommentUpdateSerializer(serializers.Serializer):
    """Validates partial updates to comment text or media attachments."""
    comment_text = StrictCharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=5000,
    )
    comment_photo = _FlexibleMediaInputField(required=False, allow_null=True)
    comment_video = _FlexibleMediaInputField(required=False, allow_null=True)
    comment_gif = _FlexibleMediaInputField(required=False, allow_null=True)
    remove_media = serializers.BooleanField(required=False, default=False)
    duration_seconds = serializers.FloatField(required=False, allow_null=True, min_value=0.0)


class PostCommentSerializer(serializers.ModelSerializer):
    """
    Serialized representation of a comment or nested reply.
    Reads pre-attached `_prefetched_replies` without triggering N+1 queries.
    """
    user_id = serializers.UUIDField(read_only=True)
    owner_type = serializers.CharField(read_only=True)
    gym_id = serializers.UUIDField(read_only=True, allow_null=True)
    gym_name = serializers.SerializerMethodField()
    gym_avatar_url = serializers.SerializerMethodField()
    author_name = serializers.SerializerMethodField()
    author_avatar_url = serializers.SerializerMethodField()
    source_post_id = serializers.UUIDField(read_only=True)
    source_comment_id = serializers.UUIDField(read_only=True, allow_null=True)
    root_comment_id = serializers.UUIDField(read_only=True, allow_null=True)
    reply_to_user_id = serializers.UUIDField(read_only=True, allow_null=True)
    reply_to_user_name = serializers.SerializerMethodField()
    comment_photo = AbsoluteMediaURLField(read_only=True, allow_null=True)
    comment_video = AbsoluteMediaURLField(read_only=True, allow_null=True)
    comment_gif = AbsoluteMediaURLField(read_only=True, allow_null=True)
    media_url = AbsoluteMediaURLField(source="resolved_media_url", read_only=True, allow_null=True)
    thumbnail_url = AbsoluteMediaURLField(source="resolved_thumbnail_url", read_only=True, allow_null=True)
    has_more_replies = serializers.SerializerMethodField()
    replies = serializers.SerializerMethodField()

    class Meta:
        model = PostComment
        fields = [
            "id",
            "user_id",
            "owner_type",
            "gym_id",
            "gym_name",
            "gym_avatar_url",
            "author_name",
            "author_avatar_url",
            "source_post_id",
            "source_comment_id",
            "root_comment_id",
            "depth",
            "reply_to_user_id",
            "reply_to_user_name",
            "comment_text",
            "comment_photo",
            "comment_video",
            "comment_gif",
            "media_type",
            "media_url",
            "thumbnail_url",
            "processing_status",
            "width",
            "height",
            "file_size_bytes",
            "duration_seconds",
            "replies_count",
            "total_replies_count",
            "has_more_replies",
            "replies",
            "is_edited",
            "edited_at",
            "created_at",
            "updated_at",
        ]

    def get_gym_name(self, obj) -> str | None:
        return obj.gym.name if obj.gym else None

    def get_gym_avatar_url(self, obj) -> str | None:
        if obj.gym and obj.gym.profile_picture_url:
            return _resolve_url(self.context.get("request"), obj.gym.profile_picture_url)
        return None

    def get_author_name(self, obj) -> str:
        if obj.user:
            name = f"{obj.user.first_name} {obj.user.last_name}".strip()
            return name or obj.user.email
        return "Unknown"

    def get_author_avatar_url(self, obj) -> str | None:
        if obj.user and hasattr(obj.user, "profile") and obj.user.profile:
            return _resolve_url(self.context.get("request"), obj.user.profile.avatar_url)
        return None

    def get_reply_to_user_name(self, obj) -> str | None:
        if obj.reply_to_user:
            name = f"{obj.reply_to_user.first_name} {obj.reply_to_user.last_name}".strip()
            return name or obj.reply_to_user.email
        return None

    def get_has_more_replies(self, obj) -> bool:
        if hasattr(obj, "_has_more_replies"):
            return bool(obj._has_more_replies)
        return obj.replies_count > 0

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_replies(self, obj) -> list:
        prefetched = getattr(obj, "_prefetched_replies", None)
        if not prefetched:
            return []
        return PostCommentSerializer(prefetched, many=True, context=self.context).data

