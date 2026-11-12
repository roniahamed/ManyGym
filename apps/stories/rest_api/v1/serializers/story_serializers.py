from rest_framework import serializers

from apps.posts.models import GymPost
from apps.stories.models import Story, StoryView
from common.enums import (
    StoryOwnerTypeEnum,
    StoryPrivacyEnum,
)
from common.serializers import (
    AbsoluteMediaURLField,
    StrictBooleanField,
    StrictCharField,
    StrictIntegerField,
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


class _FlexibleLifetimeField(serializers.Field):
    """Accepts integer or string lifetime values (6, 12, 18, 24, 48 hours) while rejecting booleans/objects."""

    def to_internal_value(self, data):
        if isinstance(data, bool) or not isinstance(data, (int, str)):
            raise serializers.ValidationError("Lifetime must be one of 6, 12, 18, 24, or 48 hours.")
        return data

    def to_representation(self, value):
        return value


class StoryFilterSerializer(serializers.Serializer):
    owner_type = serializers.ChoiceField(
        choices=StoryOwnerTypeEnum.choices,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Filter stories by uploader type ('user' or 'gym').",
    )
    user_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Filter active stories belonging to a specific public user.",
    )
    gym_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Filter active stories belonging to a specific gym.",
    )
    feed_type = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Feed filter: 'all', 'followed', 'connected', or 'public'.",
    )
    privacy = serializers.ChoiceField(
        choices=StoryPrivacyEnum.choices,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Filter by story privacy level.",
    )
    page = serializers.IntegerField(required=False, min_value=1, default=1)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=100, default=20)


class StoryCreateSerializer(serializers.Serializer):
    source_post_id = StrictUUIDField(
        required=False,
        allow_null=True,
        help_text="Optional UUID of a community post being shared to this story.",
    )
    media_url = StrictCharField(
        max_length=1000,
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Single pre-uploaded or external media URL (image or video). Omit when uploading a multipart file. media_type is auto-detected.",
    )
    thumbnail_url = StrictCharField(
        max_length=1000,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    file_size_bytes = StrictIntegerField(required=False, default=0, min_value=0)
    duration_seconds = serializers.FloatField(required=False, allow_null=True, min_value=0.0)
    file = serializers.FileField(
        required=False,
        write_only=True,
        help_text="Single media file upload (1 image [JPG/JPEG/PNG/WEBP <=10MB] or 1 video [MP4/MOV <=200MB]). media_type is auto-detected.",
    )
    lifetime_hours = _FlexibleLifetimeField(
        required=False,
        allow_null=True,
        help_text="Story lifetime in hours: 6, 12, 18 (default), 24, or 48.",
    )
    lifetime = _FlexibleLifetimeField(
        required=False,
        allow_null=True,
        help_text="Alias for lifetime_hours (6, 12, 18 [default], 24, or 48).",
    )
    privacy = StrictCharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default=StoryPrivacyEnum.PUBLIC,
        help_text="Public users: public, followers, private. Gyms: public, followers, members_only, private.",
    )
    caption = StrictCharField(
        max_length=500,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    background_color = StrictCharField(
        max_length=20,
        required=False,
        allow_blank=True,
        allow_null=True,
    )

    def validate(self, attrs):
        attrs.pop("file", None)
        lh = attrs.get("lifetime_hours")
        lt = attrs.pop("lifetime", None)
        if lh is not None and lt is not None and str(lh).strip() != str(lt).strip():
            raise serializers.ValidationError("Provide either 'lifetime_hours' or 'lifetime', not conflicting values.")
        if lh is None and lt is not None:
            attrs["lifetime_hours"] = lt
        return attrs


class StoryUpdateSerializer(serializers.Serializer):
    caption = StrictCharField(
        max_length=500,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    background_color = StrictCharField(
        max_length=20,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    privacy = StrictCharField(required=False, allow_null=False)
    lifetime_hours = _FlexibleLifetimeField(required=False, allow_null=False)
    lifetime = _FlexibleLifetimeField(required=False, allow_null=False)
    is_archived = StrictBooleanField(required=False)

    def validate(self, attrs):
        lh = attrs.get("lifetime_hours")
        lt = attrs.pop("lifetime", None)
        if lh is not None and lt is not None and str(lh).strip() != str(lt).strip():
            raise serializers.ValidationError("Provide either 'lifetime_hours' or 'lifetime', not conflicting values.")
        if lh is None and lt is not None:
            attrs["lifetime_hours"] = lt
        return attrs


class StorySourcePostSummarySerializer(serializers.ModelSerializer):
    owner_type = serializers.CharField(read_only=True)
    gym_id = serializers.UUIDField(read_only=True, allow_null=True)
    gym_name = serializers.SerializerMethodField()
    author_user_id = serializers.UUIDField(read_only=True)
    author_name = serializers.SerializerMethodField()
    is_repost = serializers.BooleanField(read_only=True)
    source_post_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = GymPost
        fields = [
            "id",
            "owner_type",
            "gym_id",
            "gym_name",
            "author_user_id",
            "author_name",
            "content_text",
            "privacy",
            "is_repost",
            "source_post_id",
            "published_at",
        ]

    def get_gym_name(self, obj) -> str | None:
        return obj.gym.name if obj.gym else None

    def get_author_name(self, obj) -> str:
        u = obj.author_user
        if u:
            full_name = f"{u.first_name} {u.last_name}".strip()
            return full_name or u.email
        return "Unknown"


class StorySerializer(serializers.ModelSerializer):
    owner_type = serializers.CharField(read_only=True)
    user_id = serializers.UUIDField(read_only=True)
    user_name = serializers.SerializerMethodField()
    user_avatar_url = serializers.SerializerMethodField()
    gym_id = serializers.UUIDField(read_only=True, allow_null=True)
    gym_name = serializers.SerializerMethodField()
    gym_avatar_url = serializers.SerializerMethodField()
    source_post_id = serializers.UUIDField(read_only=True, allow_null=True)
    source_post = StorySourcePostSummarySerializer(read_only=True, allow_null=True)

    media_url = AbsoluteMediaURLField(source="resolved_media_url", read_only=True)
    original_url = AbsoluteMediaURLField(read_only=True, allow_null=True)
    optimized_url = AbsoluteMediaURLField(read_only=True, allow_null=True)
    thumbnail_url = AbsoluteMediaURLField(source="resolved_thumbnail_url", read_only=True, allow_null=True)
    lifetime_label = serializers.CharField(source="get_lifetime_hours_display", read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    has_viewed = serializers.SerializerMethodField()

    class Meta:
        model = Story
        fields = [
            "id",
            "owner_type",
            "user_id",
            "user_name",
            "user_avatar_url",
            "gym_id",
            "gym_name",
            "gym_avatar_url",
            "source_post_id",
            "source_post",
            "media_url",
            "original_url",
            "optimized_url",
            "thumbnail_url",
            "media_type",
            "processing_status",
            "file_size_bytes",
            "width",
            "height",
            "duration_seconds",
            "caption",
            "background_color",
            "lifetime_hours",
            "lifetime_label",
            "privacy",
            "published_at",
            "expires_at",
            "is_expired",
            "is_archived",
            "views_count",
            "has_viewed",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_user_name(self, obj) -> str:
        u = obj.user
        if u:
            full_name = f"{u.first_name} {u.last_name}".strip()
            return full_name or u.email
        return "Unknown"

    def get_user_avatar_url(self, obj) -> str | None:
        if obj.user and hasattr(obj.user, "profile") and obj.user.profile:
            return _resolve_url(self.context.get("request"), obj.user.profile.avatar_url)
        return None

    def get_gym_name(self, obj) -> str | None:
        return obj.gym.name if obj.gym else None

    def get_gym_avatar_url(self, obj) -> str | None:
        if obj.gym:
            return _resolve_url(self.context.get("request"), obj.gym.profile_picture_url)
        return None

    def get_has_viewed(self, obj) -> bool:
        return bool(getattr(obj, "has_viewed", False))


class StoryTrayBucketSerializer(serializers.Serializer):
    owner_type = serializers.ChoiceField(choices=StoryOwnerTypeEnum.choices)
    owner_id = serializers.UUIDField()
    owner_name = serializers.CharField()
    owner_avatar_url = AbsoluteMediaURLField(allow_null=True)
    latest_story_at = serializers.DateTimeField()
    has_unviewed = serializers.BooleanField()
    stories_count = serializers.IntegerField()
    stories = StorySerializer(many=True)


class StoryViewSerializer(serializers.ModelSerializer):
    viewer_user_id = serializers.UUIDField(read_only=True)
    viewer_name = serializers.SerializerMethodField()
    viewer_avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = StoryView
        fields = [
            "id",
            "viewer_user_id",
            "viewer_name",
            "viewer_avatar_url",
            "viewed_at",
        ]

    def get_viewer_name(self, obj) -> str:
        u = obj.viewer_user
        if u:
            full_name = f"{u.first_name} {u.last_name}".strip()
            return full_name or u.email
        return "Unknown"

    def get_viewer_avatar_url(self, obj) -> str | None:
        if obj.viewer_user and hasattr(obj.viewer_user, "profile") and obj.viewer_user.profile:
            return _resolve_url(self.context.get("request"), obj.viewer_user.profile.avatar_url)
        return None

