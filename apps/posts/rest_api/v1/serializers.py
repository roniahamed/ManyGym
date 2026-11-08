import uuid
from rest_framework import serializers

from apps.posts.models import GymPost, GymPostMedia
from common.enums import PostPrivacyEnum, MediaTypeEnum
from common.serializers import validate_uploaded_image, AbsoluteMediaURLField


class StrictCharField(serializers.CharField):
    """CharField that enforces strict string types, preventing silent coercion of numbers or booleans."""
    def to_internal_value(self, data):
        if not isinstance(data, str):
            raise serializers.ValidationError("This field must be a valid string.")
        return super().to_internal_value(data)


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


class GymPostListSerializer(serializers.ModelSerializer):
    gym_name = serializers.CharField(source="gym.name", read_only=True)
    author_name = serializers.SerializerMethodField()
    author_avatar_url = serializers.SerializerMethodField()
    media_count = serializers.SerializerMethodField()
    media_attachments = GymPostMediaSerializer(many=True, read_only=True)
    is_following_gym = serializers.SerializerMethodField()
    is_following_author = serializers.SerializerMethodField()
    is_connected_gym = serializers.SerializerMethodField()

    class Meta:
        model = GymPost
        fields = [
            "id",
            "gym_id",
            "gym_name",
            "author_user_id",
            "author_name",
            "author_avatar_url",
            "content_text",
            "privacy",
            "published_at",
            "media_count",
            "media_attachments",
            "is_following_gym",
            "is_following_author",
            "is_connected_gym",
            "created_at",
            "updated_at",
        ]

    def get_author_name(self, obj) -> str:
        if obj.author_user:
            u = obj.author_user
            name = f"{u.first_name} {u.last_name}".strip()
            return name or u.email
        return "Unknown"

    def get_author_avatar_url(self, obj) -> str | None:
        if obj.author_user and hasattr(obj.author_user, "profile"):
            return obj.author_user.profile.avatar_url
        return None

    def get_media_count(self, obj) -> int:
        if hasattr(obj, "media_count"):
            return obj.media_count
        if hasattr(obj, "_prefetched_objects_cache") and "media_attachments" in obj._prefetched_objects_cache:
            return len(obj.media_attachments.all())
        return obj.media_attachments.count()

    def get_is_following_gym(self, obj) -> bool:
        followed_gym_ids = self.context.get("followed_gym_ids")
        if followed_gym_ids is not None:
            return obj.gym_id in followed_gym_ids
        request = self.context.get("request")
        if request and getattr(request, "user", None) and request.user.is_authenticated:
            from apps.gyms.models import GymFollow
            return GymFollow.objects.filter(user=request.user, gym_id=obj.gym_id).exists()
        return False

    def get_is_following_author(self, obj) -> bool:
        followed_user_ids = self.context.get("followed_user_ids")
        if followed_user_ids is not None:
            return obj.author_user_id in followed_user_ids
        request = self.context.get("request")
        if request and getattr(request, "user", None) and request.user.is_authenticated:
            from apps.users.models import UserFollow
            return UserFollow.objects.filter(follower=request.user, followed_user_id=obj.author_user_id).exists()
        return False

    def get_is_connected_gym(self, obj) -> bool:
        connected_gym_ids = self.context.get("connected_gym_ids")
        if connected_gym_ids is not None:
            return obj.gym_id in connected_gym_ids
        request = self.context.get("request")
        if request and getattr(request, "user", None) and request.user.is_authenticated:
            from apps.members.models import Member
            from apps.access_control.models import GymStaffAssignment
            from common.enums import StaffStatus
            from django.db.models import Q
            u = request.user
            if obj.gym.owner_user_id == u.id or u.is_superuser:
                return True
            if GymStaffAssignment.objects.filter(gym_id=obj.gym_id, user=u, status=StaffStatus.ACTIVE).exists():
                return True
            return Member.objects.filter(gym_id=obj.gym_id).filter(Q(user=u) | Q(email=u.email)).exists()
        return False


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
    privacy = serializers.ChoiceField(
        choices=PostPrivacyEnum.choices,
        default=PostPrivacyEnum.PUBLIC,
    )
    media_items = MediaItemInputSerializer(many=True, required=False, default=list)
    files = serializers.ListField(
        child=serializers.FileField(),
        required=False,
        write_only=True,
        help_text="Direct file upload (pictures or videos) in multipart/form-data. Multiple files accepted under 'files', 'media_files', or 'file'.",
    )

    def validate(self, attrs):
        attrs.pop("files", None)
        content_text = (attrs.get("content_text") or "").strip()
        media_items = attrs.get("media_items") or []

        # If files are passed in request.FILES, view will validate them
        request = self.context.get("request")
        has_files = bool(request and request.FILES)

        if not content_text and not media_items and not has_files:
            raise serializers.ValidationError(
                "A post must contain either text or at least one media attachment."
            )
        return attrs


class GymPostUpdateSerializer(serializers.Serializer):
    content_text = StrictCharField(required=False, allow_blank=True, allow_null=True)
    privacy = serializers.ChoiceField(choices=PostPrivacyEnum.choices, required=False)
    media_order = MediaOrderItemSerializer(many=True, required=False)


class CustomVideoThumbnailSerializer(serializers.Serializer):
    thumbnail_image = serializers.FileField(
        required=True,
        help_text="Custom video poster image (multipart/form-data). Max size: 10MB. Formats: JPEG, PNG, WebP, BMP, GIF, HEIC, TIFF. Automatically corrects orientation and converts directly to WebP.",
    )

    def validate(self, attrs):
        validate_uploaded_image(attrs.get("thumbnail_image"), field_name="thumbnail_image")
        return attrs
