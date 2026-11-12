from rest_framework import serializers

from apps.posts.models import GymPost, GymPostMedia
from apps.posts.selectors import can_view_post_with_context, get_user_social_context
from common.enums import (
    MediaTypeEnum,
    PostOwnerTypeEnum,
    PostPrivacyEnum,
    RepostTargetEnum,
)
from common.serializers import (
    AbsoluteMediaURLField,
    StrictCharField,
    StrictIntegerField,
    StrictUUIDField,
    validate_uploaded_image,
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


class GymPostMediaSerializer(serializers.ModelSerializer):
    media_url = AbsoluteMediaURLField(source="resolved_media_url", read_only=True)
    thumbnail_url = AbsoluteMediaURLField(source="resolved_thumbnail_url", read_only=True)
    original_url = AbsoluteMediaURLField(read_only=True, allow_null=True)
    optimized_url = AbsoluteMediaURLField(read_only=True, allow_null=True)

    class Meta:
        model = GymPostMedia
        fields = [
            "id",
            "post_id",
            "media_url",
            "original_url",
            "optimized_url",
            "media_type",
            "thumbnail_url",
            "file_size_bytes",
            "order_index",
            "processing_status",
            "created_at",
        ]


class GymFeedFilterSerializer(serializers.Serializer):
    """
    Validates and normalizes query parameters for community & profile feed queries.
    """
    owner_type = serializers.ChoiceField(
        choices=PostOwnerTypeEnum.choices,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Optional filter by post owner type ('user' or 'gym').",
    )
    user_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Optional UUID of a public user to view their personal profile feed.",
    )
    gym_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Optional UUID of a specific gym to view its profile feed.",
    )
    feed_type = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Feed stream filter: 'all', 'followed', 'connected', or 'public'.",
    )
    source = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Alias for feed_type.",
    )
    privacy = serializers.ChoiceField(
        choices=PostPrivacyEnum.choices,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Filter by post privacy level.",
    )
    is_repost = serializers.BooleanField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Optional boolean filter: true for reposts only, false for original posts only.",
    )
    search = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=200,
        help_text="Keyword search matching post content, author name, or gym name.",
    )
    page = serializers.IntegerField(required=False, min_value=1, default=1)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=100, default=20)


class _PostAuthorMixin:
    def _get_social_context(self) -> dict:
        request = self.context.get("request")
        if not request or not getattr(request, "user", None) or not request.user.is_authenticated:
            return get_user_social_context(None)
        cached = getattr(request, "_user_social_context", None)
        if cached is None:
            cached = get_user_social_context(request.user)
            request._user_social_context = cached
        return cached

    def get_gym_name(self, obj) -> str | None:
        return obj.gym.name if obj.gym else None

    def get_gym_avatar_url(self, obj) -> str | None:
        if obj.gym and obj.gym.profile_picture_url:
            return _resolve_url(self.context.get("request"), obj.gym.profile_picture_url)
        return None

    def get_author_name(self, obj) -> str:
        if obj.author_user:
            u = obj.author_user
            name = f"{u.first_name} {u.last_name}".strip()
            return name or u.email
        return "Unknown"

    def get_author_avatar_url(self, obj) -> str | None:
        if obj.author_user and hasattr(obj.author_user, "profile") and obj.author_user.profile:
            return _resolve_url(self.context.get("request"), obj.author_user.profile.avatar_url)
        return None

    def get_media_count(self, obj) -> int:
        if hasattr(obj, "media_count"):
            return obj.media_count
        if hasattr(obj, "_prefetched_objects_cache") and "media_attachments" in obj._prefetched_objects_cache:
            return len(obj.media_attachments.all())
        return obj.media_attachments.count()


class SourcePostSummarySerializer(_PostAuthorMixin, serializers.ModelSerializer):
    owner_type = serializers.CharField(read_only=True)
    gym_id = serializers.UUIDField(read_only=True, allow_null=True)
    gym_name = serializers.SerializerMethodField()
    gym_avatar_url = serializers.SerializerMethodField()
    author_user_id = serializers.UUIDField(read_only=True)
    author_name = serializers.SerializerMethodField()
    author_avatar_url = serializers.SerializerMethodField()
    media_count = serializers.SerializerMethodField()
    media_attachments = GymPostMediaSerializer(many=True, read_only=True)
    is_repost = serializers.BooleanField(read_only=True)
    source_post_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = GymPost
        fields = [
            "id",
            "owner_type",
            "gym_id",
            "gym_name",
            "gym_avatar_url",
            "author_user_id",
            "author_name",
            "author_avatar_url",
            "content_text",
            "privacy",
            "is_repost",
            "source_post_id",
            "reposts_count",
            "comments_count",
            "published_at",
            "media_count",
            "media_attachments",
            "created_at",
            "updated_at",
        ]


class GymPostListSerializer(_PostAuthorMixin, serializers.ModelSerializer):
    owner_type = serializers.CharField(read_only=True)
    gym_id = serializers.UUIDField(read_only=True, allow_null=True)
    gym_name = serializers.SerializerMethodField()
    gym_avatar_url = serializers.SerializerMethodField()
    author_user_id = serializers.UUIDField(read_only=True)
    author_name = serializers.SerializerMethodField()
    author_avatar_url = serializers.SerializerMethodField()
    is_repost = serializers.BooleanField(read_only=True)
    source_post_id = serializers.UUIDField(read_only=True, allow_null=True)
    source_post = serializers.SerializerMethodField()
    source_post_unavailable = serializers.SerializerMethodField()
    media_count = serializers.SerializerMethodField()
    media_attachments = GymPostMediaSerializer(many=True, read_only=True)
    is_following_gym = serializers.SerializerMethodField()
    is_following_author = serializers.SerializerMethodField()
    is_connected_gym = serializers.SerializerMethodField()

    class Meta:
        model = GymPost
        fields = [
            "id",
            "owner_type",
            "gym_id",
            "gym_name",
            "gym_avatar_url",
            "author_user_id",
            "author_name",
            "author_avatar_url",
            "content_text",
            "privacy",
            "is_repost",
            "source_post_id",
            "source_post",
            "source_post_unavailable",
            "reposts_count",
            "comments_count",
            "published_at",
            "media_count",
            "media_attachments",
            "is_following_gym",
            "is_following_author",
            "is_connected_gym",
            "created_at",
            "updated_at",
        ]

    def _can_view_source(self, obj) -> bool:
        if not obj.is_repost or not obj.source_post_id or not obj.source_post:
            return False
        request = self.context.get("request")
        requesting_user = getattr(request, "user", None) if request else None
        social_ctx = self._get_social_context()
        return can_view_post_with_context(obj.source_post, requesting_user, social_ctx)

    def get_source_post(self, obj):
        if not self._can_view_source(obj):
            return None
        return SourcePostSummarySerializer(obj.source_post, context=self.context).data

    def get_source_post_unavailable(self, obj) -> bool:
        if not obj.is_repost:
            return False
        return not self._can_view_source(obj)

    def get_is_following_gym(self, obj) -> bool:
        if not obj.gym_id:
            return False
        followed_gym_ids = self.context.get("followed_gym_ids")
        if followed_gym_ids is None:
            followed_gym_ids = self._get_social_context().get("followed_gym_ids", set())
        return obj.gym_id in followed_gym_ids

    def get_is_following_author(self, obj) -> bool:
        followed_user_ids = self.context.get("followed_user_ids")
        if followed_user_ids is None:
            followed_user_ids = self._get_social_context().get("followed_user_ids", set())
        return obj.author_user_id in followed_user_ids

    def get_is_connected_gym(self, obj) -> bool:
        if not obj.gym_id:
            return False
        connected_gym_ids = self.context.get("connected_gym_ids")
        if connected_gym_ids is None:
            connected_gym_ids = self._get_social_context().get("connected_gym_ids", set())
        return obj.gym_id in connected_gym_ids


class GymPostDetailSerializer(GymPostListSerializer):
    class Meta(GymPostListSerializer.Meta):
        fields = GymPostListSerializer.Meta.fields


class MediaItemInputSerializer(serializers.Serializer):
    media_url = StrictCharField(max_length=1000, required=True)
    media_type = serializers.ChoiceField(choices=MediaTypeEnum.choices, default=MediaTypeEnum.PICTURE)
    thumbnail_url = StrictCharField(max_length=1000, required=False, allow_blank=True, allow_null=True)
    file_size_bytes = serializers.IntegerField(required=False, default=0, min_value=0)
    order_index = serializers.IntegerField(required=False, default=0, min_value=0)


class MediaOrderItemSerializer(serializers.Serializer):
    media_id = serializers.UUIDField(required=True)
    order_index = serializers.IntegerField(required=True, min_value=0)


class GymPostCreateSerializer(serializers.Serializer):
    content_text = StrictCharField(required=False, allow_blank=True, allow_null=True)
    privacy = StrictCharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default=PostPrivacyEnum.PUBLIC,
        help_text="Public users: public, followers, private. Gyms: public, followers, members_only, private.",
    )
    source_post_id = StrictUUIDField(
        required=False,
        allow_null=True,
        help_text="Optional UUID of an existing post to repost/share.",
    )
    target = StrictCharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default=RepostTargetEnum.PROFILE,
        help_text="Destination when source_post_id is provided: 'profile' (default) or 'story'.",
    )
    caption = StrictCharField(max_length=500, required=False, allow_blank=True, allow_null=True)
    background_color = StrictCharField(max_length=20, required=False, allow_blank=True, allow_null=True)
    lifetime_hours = _FlexibleLifetimeField(required=False, allow_null=True)
    lifetime = _FlexibleLifetimeField(required=False, allow_null=True)
    media_url = StrictCharField(max_length=1000, required=False, allow_blank=True, allow_null=True)
    thumbnail_url = StrictCharField(max_length=1000, required=False, allow_blank=True, allow_null=True)
    file_size_bytes = StrictIntegerField(required=False, default=0, min_value=0)
    duration_seconds = serializers.FloatField(required=False, allow_null=True, min_value=0.0)
    media_items = MediaItemInputSerializer(many=True, required=False, default=list)
    files = serializers.ListField(
        child=serializers.FileField(),
        required=False,
        write_only=True,
        help_text="Direct file upload (pictures or videos) in multipart/form-data. Multiple files accepted under 'files', 'media_files', or 'file'.",
    )

    def validate(self, attrs):
        attrs.pop("files", None)
        lh = attrs.get("lifetime_hours")
        lt = attrs.pop("lifetime", None)
        if lh is not None and lt is not None and str(lh).strip() != str(lt).strip():
            raise serializers.ValidationError("Provide either 'lifetime_hours' or 'lifetime', not conflicting values.")
        if lh is None and lt is not None:
            attrs["lifetime_hours"] = lt

        content_text = (attrs.get("content_text") or "").strip()
        media_items = attrs.get("media_items") or []
        source_post_id = attrs.get("source_post_id")

        request = self.context.get("request")
        has_files = bool(request and request.FILES)

        if not source_post_id and not content_text and not media_items and not has_files:
            raise serializers.ValidationError(
                "A post must contain either text, at least one media attachment, or a source_post_id."
            )
        return attrs


class RepostCreateSerializer(serializers.Serializer):
    source_post_id = StrictUUIDField(
        required=False,
        allow_null=True,
        help_text="UUID of the post being reposted (optional if passed in URL path).",
    )
    target = StrictCharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default=RepostTargetEnum.PROFILE,
        help_text="Where to share: 'profile' (showing on profile feed) or 'story' (share on Story).",
    )
    privacy = StrictCharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default=PostPrivacyEnum.PUBLIC,
        help_text="Public users: public, followers, private. Gyms: public, followers, members_only, private.",
    )
    content_text = StrictCharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Optional commentary text added when reposting to profile feed.",
    )
    # Optional Story fields when target='story'
    caption = StrictCharField(
        max_length=500,
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Optional Story overlay caption (falls back to content_text if omitted).",
    )
    background_color = StrictCharField(
        max_length=20,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    lifetime_hours = _FlexibleLifetimeField(required=False, allow_null=True)
    lifetime = _FlexibleLifetimeField(required=False, allow_null=True)
    media_url = StrictCharField(max_length=1000, required=False, allow_blank=True, allow_null=True)
    thumbnail_url = StrictCharField(max_length=1000, required=False, allow_blank=True, allow_null=True)
    file_size_bytes = StrictIntegerField(required=False, default=0, min_value=0)
    duration_seconds = serializers.FloatField(required=False, allow_null=True, min_value=0.0)
    file = serializers.FileField(required=False, write_only=True)

    def validate(self, attrs):
        attrs.pop("file", None)
        lh = attrs.get("lifetime_hours")
        lt = attrs.pop("lifetime", None)
        if lh is not None and lt is not None and str(lh).strip() != str(lt).strip():
            raise serializers.ValidationError("Provide either 'lifetime_hours' or 'lifetime', not conflicting values.")
        if lh is None and lt is not None:
            attrs["lifetime_hours"] = lt
        return attrs


class GymPostUpdateSerializer(serializers.Serializer):
    content_text = StrictCharField(required=False, allow_blank=True, allow_null=True)
    privacy = StrictCharField(required=False, allow_null=False)
    media_order = MediaOrderItemSerializer(many=True, required=False)


class CustomVideoThumbnailSerializer(serializers.Serializer):
    thumbnail_image = serializers.FileField(
        required=True,
        help_text="Custom video poster image (multipart/form-data). Max size: 10MB. Formats: JPEG, PNG, WebP, BMP, GIF, HEIC, TIFF. Automatically corrects orientation and converts directly to WebP.",
    )

    def validate(self, attrs):
        validate_uploaded_image(attrs.get("thumbnail_image"), field_name="thumbnail_image")
        return attrs
