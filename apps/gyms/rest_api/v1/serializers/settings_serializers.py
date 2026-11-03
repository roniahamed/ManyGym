from rest_framework import serializers
from apps.gyms.models import GymSetting, GymBlockedUser
from apps.users.models import User
from common.serializers import StrictCharField, StrictBooleanField, StrictUUIDField
from common.enums import (
    AudienceMessagingEnum,
    AudienceJoiningRequestEnum,
    AudienceMembersVisibilityEnum,
    AudienceFollowingVisibilityEnum,
    PostsAgeRestrictionEnum,
)


class GymSettingSerializer(serializers.ModelSerializer):
    """
    Read-only presentation serializer for complete Gym Configuration & Privacy Settings.
    """
    gym_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = GymSetting
        fields = [
            "id",
            "gym_id",
            "language",
            "video_autoplay",
            "dark_mode",
            "admin_logs_alerts",
            "issues_alerts",
            "who_can_message",
            "who_can_send_joining_request",
            "who_can_see_members",
            "who_can_see_followers",
            "who_can_see_following",
            "posts_age_restriction",
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
    """
    language = StrictCharField(required=False, max_length=20)
    video_autoplay = StrictBooleanField(required=False)
    dark_mode = StrictBooleanField(required=False)

    admin_logs_alerts = StrictBooleanField(required=False)
    issues_alerts = StrictBooleanField(required=False)

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
    who_can_see_followers = serializers.ChoiceField(
        choices=AudienceFollowingVisibilityEnum.choices,
        required=False,
        help_text="Visibility of gym followers: 'everyone', 'only_members', 'private'",
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

    is_deactivated = StrictBooleanField(required=False)
    is_published = StrictBooleanField(required=False)
    is_deleted = StrictBooleanField(required=False)

    def validate_language(self, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("Language code cannot be empty.")
        return cleaned


class GymBlockedUserSerializer(serializers.ModelSerializer):
    """
    Serializer representing a blocked user record within a gym's workspace context.
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
    """
    user_id = StrictUUIDField(required=True, help_text="Valid UUID string of the user to block.")
    reason = StrictCharField(
        required=False,
        allow_blank=True,
        max_length=255,
        help_text="Optional administrative rationale for blocking.",
    )

    def validate_reason(self, value: str | None) -> str:
        if value is None:
            return ""
        return value.strip()


class GymUserSearchToBlockSerializer(serializers.ModelSerializer):
    """
    Lightweight projection serializer for searching active users to block.
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
    For 'delete' action, requires account password and confirmation keyword 'delete'.
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
    password = serializers.CharField(
        required=False,
        write_only=True,
        help_text="Account password required for delete confirmation.",
    )
    confirmation = serializers.CharField(
        required=False,
        help_text="Confirmation keyword ('delete') required for delete confirmation.",
    )

    def validate(self, attrs):
        action = attrs.get("action")
        if action == "delete":
            password = attrs.get("password")
            confirmation = attrs.get("confirmation")
            if not password:
                raise serializers.ValidationError({"password": "Password is required to delete gym."})
            if not confirmation:
                raise serializers.ValidationError({"confirmation": "Confirmation text is required. Please type 'delete' to confirm."})
            if confirmation.strip().lower() != "delete":
                raise serializers.ValidationError({"confirmation": "Please type 'delete' to confirm deletion."})
        return attrs
