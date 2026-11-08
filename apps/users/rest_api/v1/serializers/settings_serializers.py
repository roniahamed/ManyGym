from rest_framework import serializers
from apps.users.models import User, UserSetting, UserBlockedUser
from common.serializers import StrictCharField, StrictBooleanField, StrictUUIDField
from common.enums import UserAudienceMessagingEnum, UserAudienceVisibilityEnum


class UserSettingSerializer(serializers.ModelSerializer):
    """
    Read-only presentation serializer for comprehensive User Profile & Privacy Settings.
    """
    user_id = serializers.UUIDField(read_only=True)
    is_private = serializers.BooleanField(source="user.profile.is_private", read_only=True)

    class Meta:
        model = UserSetting
        fields = [
            "id",
            "user_id",
            "language",
            "dark_mode",
            "is_private",
            "require_follow_approval",
            "who_can_message",
            "who_can_see_followers",
            "who_can_see_following",
            "is_deactivated",
            "deactivated_at",
            "is_deleted",
            "deleted_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "user_id",
            "is_private",
            "deactivated_at",
            "deleted_at",
            "created_at",
            "updated_at",
        ]


class UserSettingUpdateSerializer(serializers.Serializer):
    """
    Validation and deserialization serializer for updating User Settings.
    """
    language = StrictCharField(required=False, max_length=20)
    dark_mode = StrictBooleanField(required=False)
    is_private = StrictBooleanField(required=False, help_text="Toggle private profile state.")
    require_follow_approval = StrictBooleanField(required=False, help_text="Require approval before someone can follow you.")

    who_can_message = serializers.ChoiceField(
        choices=UserAudienceMessagingEnum.choices,
        required=False,
        help_text="Controls messaging permission: 'everyone', 'followers', 'no_one'",
    )
    who_can_see_followers = serializers.ChoiceField(
        choices=UserAudienceVisibilityEnum.choices,
        required=False,
        help_text="Visibility of followers list: 'everyone', 'followers', 'private'",
    )
    who_can_see_following = serializers.ChoiceField(
        choices=UserAudienceVisibilityEnum.choices,
        required=False,
        help_text="Visibility of followed pages/users: 'everyone', 'followers', 'private'",
    )

    def validate_language(self, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("Language code cannot be empty.")
        return cleaned


class UserBlockedUserSerializer(serializers.ModelSerializer):
    """
    Serializer representing a blocked user record for a user profile.
    """
    user_id = serializers.UUIDField(source="blocked_user.id", read_only=True)
    email = serializers.EmailField(source="blocked_user.email", read_only=True)
    first_name = serializers.CharField(source="blocked_user.first_name", read_only=True)
    last_name = serializers.CharField(source="blocked_user.last_name", read_only=True)
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = UserBlockedUser
        fields = [
            "id",
            "user_id",
            "email",
            "first_name",
            "last_name",
            "avatar_url",
            "reason",
            "created_at",
        ]
        read_only_fields = fields

    def get_avatar_url(self, obj: UserBlockedUser) -> str | None:
        if hasattr(obj.blocked_user, "profile") and obj.blocked_user.profile:
            return obj.blocked_user.profile.avatar_url
        return None


class UserBlockUserCreateSerializer(serializers.Serializer):
    """
    Request serializer for blocking another user.
    """
    user_id = StrictUUIDField(required=True, help_text="Valid UUID string of the user to block.")
    reason = StrictCharField(
        required=False,
        allow_blank=True,
        max_length=255,
        help_text="Optional rationale for blocking.",
    )

    def validate_reason(self, value: str | None) -> str:
        if value is None:
            return ""
        return value.strip()


class UserFollowerBlockCreateSerializer(serializers.Serializer):
    """
    Request payload serializer for blocking directly from the followers list.
    """
    reason = StrictCharField(
        required=False,
        allow_blank=True,
        default="Blocked from followers list",
        max_length=255,
        help_text="Optional rationale for blocking from followers list.",
    )

    def validate_reason(self, value: str | None) -> str:
        if value is None:
            return "Blocked from followers list"
        cleaned = value.strip()
        return cleaned if cleaned else "Blocked from followers list"


class UserSearchToBlockSerializer(serializers.ModelSerializer):
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


class UserAccessControlActionSerializer(serializers.Serializer):
    """
    Request payload serializer for user profile lifecycle state transitions.
    For 'delete' action, requires account password and confirmation keyword 'delete'.
    """
    action = serializers.ChoiceField(
        choices=[
            "deactivate",
            "reactivate",
            "delete",
            "restore",
        ],
        required=True,
        help_text="Lifecycle state transition action.",
    )
    password = serializers.CharField(
        required=False,
        write_only=True,
        help_text="Account password required for delete or restore confirmation.",
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
                raise serializers.ValidationError({"password": "Password is required to delete account."})
            if not confirmation:
                raise serializers.ValidationError({"confirmation": "Confirmation text is required. Please type 'delete' to confirm."})
            if confirmation.strip().lower() != "delete":
                raise serializers.ValidationError({"confirmation": "Please type 'delete' to confirm deletion."})
        elif action == "restore":
            password = attrs.get("password")
            if not password:
                raise serializers.ValidationError({"password": "Password is required to restore account."})
        return attrs

