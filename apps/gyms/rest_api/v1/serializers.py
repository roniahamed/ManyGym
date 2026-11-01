from rest_framework import serializers
from apps.gyms.models import (
    Gym,
    GymLocation,
    GymOpeningHours,
    GymGallery,
    GymSetting,
    GymBlockedUser,
)
from apps.users.models import User
from common.serializers import StrictCharField, StrictBooleanField, StrictUUIDField, validate_uploaded_image
from common.enums import (
    GymTypeEnum,
    GymGenderRequired,
    GalleryCategoryEnum,
    MediaTypeEnum,
    AudienceMessagingEnum,
    AudienceJoiningRequestEnum,
    AudienceMembersVisibilityEnum,
    AudienceFollowingVisibilityEnum,
    PostsAgeRestrictionEnum,
)


class GymLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = GymLocation
        fields = [
            "id",
            "address",
            "latitude",
            "longitude",
            "city",
            "country",
            "postal_code",
            "is_primary",
            "updated_at",
        ]
        read_only_fields = ["id", "updated_at"]


class GymOpeningHoursItemSerializer(serializers.ModelSerializer):
    day_name = serializers.CharField(source="get_day_of_week_display", read_only=True)

    class Meta:
        model = GymOpeningHours
        fields = [
            "id",
            "day_of_week",
            "day_name",
            "start_time",
            "end_time",
            "is_closed",
        ]
        read_only_fields = ["id", "day_name"]


class GymOpeningHoursBulkItemSerializer(serializers.Serializer):
    day_of_week = serializers.IntegerField(min_value=0, max_value=6)
    start_time = serializers.TimeField(required=False, allow_null=True, input_formats=["%H:%M:%S", "%H:%M"])
    end_time = serializers.TimeField(required=False, allow_null=True, input_formats=["%H:%M:%S", "%H:%M"])
    is_closed = StrictBooleanField(default=False)


class GymOpeningHoursBulkUpdateSerializer(serializers.Serializer):
    hours = serializers.ListField(
        child=GymOpeningHoursBulkItemSerializer(),
        allow_empty=False,
    )


class GymGalleryItemSerializer(serializers.ModelSerializer):
    resolved_media_url = serializers.CharField(read_only=True)
    resolved_thumbnail_url = serializers.CharField(read_only=True)

    class Meta:
        model = GymGallery
        fields = [
            "id",
            "media_url",
            "original_url",
            "optimized_url",
            "thumbnail_url",
            "resolved_media_url",
            "resolved_thumbnail_url",
            "media_type",
            "category",
            "caption",
            "order_index",
            "processing_status",
            "width",
            "height",
            "size_bytes",
            "optimized_size_bytes",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "original_url",
            "optimized_url",
            "thumbnail_url",
            "resolved_media_url",
            "resolved_thumbnail_url",
            "processing_status",
            "width",
            "height",
            "size_bytes",
            "optimized_size_bytes",
            "created_at",
        ]


class GymGalleryCreateSerializer(serializers.Serializer):
    file = serializers.FileField(required=False, help_text="Direct file upload (picture or video)")
    media_url = StrictCharField(max_length=1000, required=False, help_text="Media URL or local path")
    media_type = serializers.ChoiceField(
        choices=MediaTypeEnum.choices,
        default=MediaTypeEnum.PICTURE,
        required=False,
    )
    category = serializers.ChoiceField(
        choices=GalleryCategoryEnum.choices,
        default=GalleryCategoryEnum.GENERAL,
        required=False,
    )
    caption = StrictCharField(
        max_length=200,
        required=False,
        allow_blank=True,
    )

    def validate(self, attrs):
        if not attrs.get("file") and not attrs.get("media_url"):
            raise serializers.ValidationError("Either 'file' or 'media_url' must be provided.")
        return attrs


class GymGalleryReorderItemSerializer(serializers.Serializer):
    id = serializers.UUIDField(required=True)
    order_index = serializers.IntegerField(required=True, min_value=0)


class GymGalleryReorderSerializer(serializers.Serializer):
    items = serializers.ListField(
        child=GymGalleryReorderItemSerializer(),
        allow_empty=False,
    )


class GymCreateSerializer(serializers.Serializer):
    name = StrictCharField(max_length=255, required=True)
    primary_type = serializers.ChoiceField(
        choices=GymTypeEnum.choices,
        default=GymTypeEnum.GENERAL_FITNESS,
    )
    secondary_type = serializers.ChoiceField(
        choices=GymTypeEnum.choices,
        required=False,
        allow_null=True,
    )
    short_description = StrictCharField(
        required=False,
        allow_blank=True,
        min_length=120,
    )
    profile_picture_url = StrictCharField(required=False, allow_blank=True, max_length=1000)
    profile_picture = serializers.FileField(
        required=False,
        allow_null=True,
        help_text="Direct profile picture upload (multipart/form-data). Max size: 10MB. Formats: JPEG, PNG, WebP, BMP, GIF, HEIC, TIFF. Automatically corrects orientation and converts directly to WebP.",
    )
    cover_photo_url = StrictCharField(required=False, allow_blank=True, max_length=1000)
    cover_photo = serializers.FileField(
        required=False,
        allow_null=True,
        help_text="Direct cover photo upload (multipart/form-data). Max size: 10MB. Formats: JPEG, PNG, WebP, BMP, GIF, HEIC, TIFF. Automatically corrects orientation and converts directly to WebP.",
    )
    gender_required = serializers.ChoiceField(
        choices=GymGenderRequired.choices,
        default=GymGenderRequired.EVERYONE,
    )
    min_age = serializers.IntegerField(default=1, min_value=1, max_value=99)
    timezone = StrictCharField(default="UTC", max_length=100)
    address = StrictCharField(required=False, default="Unspecified Location")
    latitude = serializers.DecimalField(max_digits=10, decimal_places=8, default=0.0)
    longitude = serializers.DecimalField(max_digits=11, decimal_places=8, default=0.0)
    city = StrictCharField(required=False, allow_blank=True, max_length=100)
    country = StrictCharField(required=False, allow_blank=True, max_length=100)
    postal_code = StrictCharField(required=False, allow_blank=True, max_length=30)

    def validate(self, attrs):
        validate_uploaded_image(attrs.get("profile_picture"), field_name="profile_picture")
        validate_uploaded_image(attrs.get("cover_photo"), field_name="cover_photo")
        return attrs


class GymOverviewUpdateSerializer(serializers.Serializer):
    name = StrictCharField(max_length=255, required=False)
    primary_type = serializers.ChoiceField(choices=GymTypeEnum.choices, required=False)
    secondary_type = serializers.ChoiceField(choices=GymTypeEnum.choices, required=False, allow_null=True)
    short_description = StrictCharField(required=False, min_length=120)
    profile_picture_url = StrictCharField(required=False, allow_blank=True, max_length=1000)
    profile_picture = serializers.FileField(
        required=False,
        allow_null=True,
        help_text="Direct profile picture upload (multipart/form-data). Max size: 10MB. Formats: JPEG, PNG, WebP, BMP, GIF, HEIC, TIFF. Automatically corrects orientation and converts directly to WebP.",
    )
    cover_photo_url = StrictCharField(required=False, allow_blank=True, max_length=1000)
    cover_photo = serializers.FileField(
        required=False,
        allow_null=True,
        help_text="Direct cover photo upload (multipart/form-data). Max size: 10MB. Formats: JPEG, PNG, WebP, BMP, GIF, HEIC, TIFF. Automatically corrects orientation and converts directly to WebP.",
    )
    gender_required = serializers.ChoiceField(choices=GymGenderRequired.choices, required=False)
    min_age = serializers.IntegerField(required=False, min_value=1, max_value=99)
    timezone = StrictCharField(required=False, max_length=100)

    def validate(self, attrs):
        validate_uploaded_image(attrs.get("profile_picture"), field_name="profile_picture")
        validate_uploaded_image(attrs.get("cover_photo"), field_name="cover_photo")
        return attrs


class GymLocationUpdateSerializer(serializers.Serializer):
    address = StrictCharField(required=True)
    latitude = serializers.DecimalField(max_digits=10, decimal_places=8, required=True)
    longitude = serializers.DecimalField(max_digits=11, decimal_places=8, required=True)
    city = StrictCharField(required=False, allow_blank=True, max_length=100)
    country = StrictCharField(required=False, allow_blank=True, max_length=100)
    postal_code = StrictCharField(required=False, allow_blank=True, max_length=30)


class GymDetailSerializer(serializers.ModelSerializer):
    location = serializers.SerializerMethodField()
    opening_hours_count = serializers.SerializerMethodField()
    gallery_count = serializers.SerializerMethodField()
    owner_email = serializers.CharField(source="owner_user.email", read_only=True)

    class Meta:
        model = Gym
        fields = [
            "id",
            "name",
            "owner_email",
            "profile_picture_url",
            "cover_photo_url",
            "short_description",
            "primary_type",
            "secondary_type",
            "gender_required",
            "min_age",
            "timezone",
            "location",
            "opening_hours_count",
            "gallery_count",
            "created_at",
            "updated_at",
        ]

    def get_location(self, obj):
        prefetched = getattr(obj, "prefetched_primary_locations", None)
        if prefetched is not None:
            primary_loc = prefetched[0] if prefetched else None
        else:
            primary_loc = obj.locations.filter(is_primary=True).first()
        return GymLocationSerializer(primary_loc).data if primary_loc else None

    def get_opening_hours_count(self, obj):
        count = getattr(obj, "annotated_opening_hours_count", None)
        if count is not None:
            return count
        return obj.opening_hours.count()

    def get_gallery_count(self, obj):
        count = getattr(obj, "annotated_gallery_count", None)
        if count is not None:
            return count
        return obj.gallery_items.count()


class GymSettingSerializer(serializers.ModelSerializer):
    """
    Read-only presentation serializer for complete Gym Configuration & Privacy Settings.

    Exposes preferences across:
    - Display (language, video autoplay, dark mode)
    - Alerts (admin logs, issue reports)
    - Audience & Sharing (messages, join requests, member visibility, followee visibility, age restrictions)
    - Access & Control (deactivation, publishing, soft deletion lifecycle state)
    """
    gym_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = GymSetting
        fields = [
            "id",
            "gym_id",
            # Preference -> Display
            "language",
            "video_autoplay",
            "dark_mode",
            # Privacy and Sharing -> Alerts
            "admin_logs_alerts",
            "issues_alerts",
            # Privacy and Sharing -> Audience
            "who_can_message",
            "who_can_send_joining_request",
            "who_can_see_members",
            "who_can_see_following",
            "posts_age_restriction",
            # Visibility -> Access & Control
            "is_deactivated",
            "deactivated_at",
            "is_published",
            "unpublished_at",
            "is_deleted",
            "deleted_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "gym_id",
            "deactivated_at",
            "unpublished_at",
            "deleted_at",
            "created_at",
            "updated_at",
        ]


class GymSettingUpdateSerializer(serializers.Serializer):
    """
    Validation and deserialization serializer for updating Gym Settings.

    Supports partial PATCH updates across Preference (Display), Privacy & Sharing (Alerts, Audience),
    and Visibility (Access & Control).
    """
    # Preference -> Display
    language = StrictCharField(required=False, max_length=20)
    video_autoplay = StrictBooleanField(required=False)
    dark_mode = StrictBooleanField(required=False)

    # Privacy and Sharing -> Alerts
    admin_logs_alerts = StrictBooleanField(required=False)
    issues_alerts = StrictBooleanField(required=False)

    # Privacy and Sharing -> Audience
    who_can_message = serializers.ChoiceField(
        choices=AudienceMessagingEnum.choices,
        required=False,
        help_text="Controls messaging permission: 'everyone', 'followers_and_members', 'members_only'",
    )
    who_can_send_joining_request = serializers.ChoiceField(
        choices=AudienceJoiningRequestEnum.choices,
        required=False,
        help_text="Controls who can submit a membership request: 'everyone', 'no_one'",
    )
    who_can_see_members = serializers.ChoiceField(
        choices=AudienceMembersVisibilityEnum.choices,
        required=False,
        help_text="Visibility of gym member roster: 'everyone', 'only_members'",
    )
    who_can_see_following = serializers.ChoiceField(
        choices=AudienceFollowingVisibilityEnum.choices,
        required=False,
        help_text="Visibility of followed pages/people: 'everyone', 'only_members', 'private'",
    )
    posts_age_restriction = serializers.ChoiceField(
        choices=PostsAgeRestrictionEnum.choices,
        required=False,
        help_text="Age restriction filter for gym posts: 'any_age', '17_plus', '18_plus', '19_plus', '20_plus'",
    )

    # Visibility -> Access & Control
    is_deactivated = StrictBooleanField(required=False)
    is_published = StrictBooleanField(required=False)
    is_deleted = StrictBooleanField(required=False)

    def validate_language(self, value: str) -> str:
        """Sanitizes language code by stripping leading/trailing whitespace."""
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("Language code cannot be empty.")
        return cleaned


class GymBlockedUserSerializer(serializers.ModelSerializer):
    """
    Serializer representing a blocked user record within a gym's workspace context.

    Includes user identity details, blocking staff identity, and optional blocking justification.
    """
    user_id = serializers.UUIDField(read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    first_name = serializers.CharField(source="user.first_name", read_only=True)
    last_name = serializers.CharField(source="user.last_name", read_only=True)
    avatar_url = serializers.SerializerMethodField()
    blocked_by_email = serializers.EmailField(source="blocked_by.email", read_only=True, default=None)

    class Meta:
        model = GymBlockedUser
        fields = [
            "id",
            "user_id",
            "email",
            "first_name",
            "last_name",
            "avatar_url",
            "blocked_by_email",
            "reason",
            "created_at",
        ]
        read_only_fields = fields

    def get_avatar_url(self, obj: GymBlockedUser) -> str | None:
        if hasattr(obj.user, "profile") and obj.user.profile:
            return obj.user.profile.avatar_url
        return None


class GymBlockUserCreateSerializer(serializers.Serializer):
    """
    Request serializer for blocking a user from a gym.

    Strictly validates user_id as a UUID string, rejecting integers/floats/booleans.
    """
    user_id = StrictUUIDField(required=True, help_text="Valid UUID string of the user to block.")
    reason = StrictCharField(
        required=False,
        allow_blank=True,
        max_length=255,
        help_text="Optional administrative rationale for blocking.",
    )

    def validate_reason(self, value: str | None) -> str:
        """Strips surrounding whitespace from optional blocking reason."""
        if value is None:
            return ""
        return value.strip()


class GymUserSearchToBlockSerializer(serializers.ModelSerializer):
    """
    Lightweight projection serializer for searching active users to block.

    Omits sensitive user profile fields and only returns minimal identity attributes.
    """
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "avatar_url",
        ]
        read_only_fields = fields

    def get_avatar_url(self, obj: User) -> str | None:
        if hasattr(obj, "profile") and obj.profile:
            return obj.profile.avatar_url
        return None


class GymAccessControlActionSerializer(serializers.Serializer):
    """
    Request payload serializer for gym lifecycle state transitions.

    Supported transitions:
    - `deactivate`: Temporarily suspend gym activities.
    - `reactivate`: Re-enable gym activities from suspended state.
    - `unpublish`: Hide gym profile and listings from public discovery.
    - `publish`: Make gym profile and listings visible to the public.
    - `delete`: Soft-delete gym workspace.
    - `restore`: Restore soft-deleted gym workspace.
    """
    action = serializers.ChoiceField(
        choices=[
            "deactivate",
            "reactivate",
            "unpublish",
            "publish",
            "delete",
            "restore",
        ],
        required=True,
        help_text="Lifecycle state transition action.",
    )
